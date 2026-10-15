"""`nexus` and `nexus-dev` as processes: exit codes and signals (ADR-021)."""

import contextlib
import http.client
import json
import logging
import os
import queue
import signal
import socket
import subprocess
import sys
import textwrap
import threading

import pytest
import uvicorn
from sqlalchemy.orm import Session
from test_serving import GUARD, TAIL, assert_refuses, free_port, http_get
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

import nexus
from nexus import serving
from nexus.auth import tokens
from nexus.config import Settings
from nexus.db import make_engine
from nexus.live import LIVE_PROTOCOL

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")


class Child:
    """A child process whose stderr is read by a thread; always killed by its exact PID."""

    def __init__(self, argv, env):
        self.proc = subprocess.Popen(
            argv, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            encoding="utf-8",
        )
        self.lines: list[str] = []
        self._new: queue.Queue = queue.Queue()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self):
        for line in self.proc.stderr:
            self.lines.append(line)
            self._new.put(line)
        self._new.put(None)

    def wait_line(self, text: str) -> None:
        seen = [line for line in self.lines if text in line]
        while not seen:
            try:
                line = self._new.get(timeout=GUARD)
            except queue.Empty:
                pytest.fail(f"no line with {text!r} on stderr:\n" + "".join(self.lines))
            if line is None:
                pytest.fail(f"the process ended before {text!r}:\n" + "".join(self.lines))
            seen = [line] if text in line else []

    def finish(self) -> tuple[int, str]:
        code = self.proc.wait(timeout=GUARD * 2)
        self._reader.join(GUARD)
        return code, "".join(self.lines)

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()  # this child only, by its PID
            self.proc.wait()
        self._reader.join(GUARD)
        self.proc.stderr.close()


@pytest.fixture
def child(tmp_path):
    started: list[Child] = []

    def start(argv, **env):
        full = {**os.environ, "NEXUS_DATA_DIR": str(tmp_path / "data"),
                "NEXUS_TAILSCALE_BIN": str(tmp_path / "no-such-tailscale"), **env}
        started.append(Child(argv, full))
        return started[-1]

    try:
        yield start
    finally:
        for process in started:
            process.close()


MAIN = [sys.executable, "-c", "import nexus; nexus.main()"]


def test_main_exits_3_when_the_loopback_port_is_taken(child):
    port = free_port()
    with socket.create_server(("127.0.0.1", port)):
        process = child(MAIN, NEXUS_PORT=str(port))
        code, stderr = process.finish()
    assert code == 3
    assert any(line.startswith("ERROR") for line in stderr.splitlines())
    assert "Traceback" not in stderr


def test_main_maps_a_loopback_bind_error_to_exit_3(monkeypatch, tmp_path, caplog):
    async def refusing(config, settings):
        raise serving.LoopbackBindError from OSError(98, "Address already in use")

    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(serving, "serve", refusing)
    monkeypatch.setattr("nexus.logs.uvicorn_log_config", lambda: None)
    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        with pytest.raises(SystemExit) as exit_info:
            nexus.main()
    assert exit_info.value.code == 3
    assert [r.name for r in caplog.records if r.levelno == logging.ERROR] == ["uvicorn.error"]


@posix_only
def test_main_exits_0_on_sigint_without_traceback(child):
    port = free_port()
    process = child(MAIN, NEXUS_PORT=str(port))
    process.wait_line("Nexus en service")
    assert http_get(port) == 200
    process.proc.send_signal(signal.SIGINT)
    code, stderr = process.finish()
    assert code == 0
    assert "Traceback" not in stderr and "KeyboardInterrupt" not in stderr


SCRIPT = textwrap.dedent('''
    import asyncio, socket, sys
    from pathlib import Path

    import uvicorn

    from nexus import serving
    from nexus.app import create_app
    from nexus.config import Settings
    from nexus.logs import uvicorn_log_config

    port, tail_port, tail = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    settings = Settings(
        data_dir=Path(sys.argv[4]), hosts=("127.0.0.1", tail), port=port,
    )


    def bind(address, p, family, backlog):
        if address == tail:  # the "tailnet" address is served by a socket on the loopback
            return serving.create_listener("127.0.0.1", tail_port, socket.AF_INET, backlog)
        return serving.create_listener(address, p, family, backlog)


    log_config = uvicorn_log_config()
    log_config["loggers"]["nexus"]["level"] = "DEBUG"
    config = uvicorn.Config(
        create_app(settings, nodes_runner=lambda: "{}"), port=port, access_log=False,
        log_config=log_config,
    )
    confirming = '{"BackendState": "Running", "TailscaleIPs": ["%s"]}' % tail
    asyncio.run(
        serving.serve(config, settings, tailnet_status=lambda: confirming, bind=bind),
        loop_factory=config.get_loop_factory(),
    )
''')


@posix_only
def test_sigterm_closes_both_listeners(child, tmp_path):
    script = tmp_path / "serve_both.py"
    script.write_text(SCRIPT, encoding="utf-8")
    port, tail_port = free_port(), free_port()
    data_dir = tmp_path / "data"
    process = child([sys.executable, str(script), str(port), str(tail_port), TAIL, str(data_dir)])
    process.wait_line("écoute du tailnet ouverte")

    engine = make_engine(Settings(data_dir=data_dir).db_url)
    with Session(engine) as session:
        _, token = tokens.issue(session, "loic", "test")
        session.commit()
    engine.dispose()

    stack = contextlib.ExitStack()
    sockets = []
    for target in (port, tail_port):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", "/api/ws-ticket", headers={"Authorization": f"Bearer {token}"})
        ticket = json.loads(conn.getresponse().read())["ticket"]
        conn.close()
        ws = stack.enter_context(
            connect(f"ws://127.0.0.1:{target}/api/ws", subprotocols=[LIVE_PROTOCOL, ticket])
        )
        assert json.loads(ws.recv())["type"] == "hello"
        sockets.append(ws)

    process.proc.send_signal(signal.SIGTERM)
    for ws in sockets:
        with pytest.raises(ConnectionClosed) as closed:
            ws.recv(timeout=GUARD)
        assert closed.value.rcvd.code == 1012
    stack.close()
    code, stderr = process.finish()
    assert code == -signal.SIGTERM
    assert "Cancel" not in stderr
    assert stderr.index("surveillance des écoutes annulée") < stderr.index("Shutting down")
    assert_refuses(port)
    assert_refuses(tail_port)


def test_dev_refuses_a_tailnet_address(monkeypatch, tmp_path):
    def must_not_run(*args, **kwargs):
        raise AssertionError("uvicorn.run must not be reached")

    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_HOST", f"127.0.0.1,{TAIL}")
    monkeypatch.setattr(uvicorn, "run", must_not_run)
    with pytest.raises(SystemExit) as refused:
        nexus.dev()
    assert "nexus-dev" in str(refused.value) and TAIL not in str(refused.value)


def test_dev_runs_on_the_loopback_entry(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_HOST", "localhost")
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))
    nexus.dev()
    assert captured["host"] == "localhost" and captured["reload"] is True
