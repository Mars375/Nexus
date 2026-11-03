"""Shared helpers and the NexusServer harness for the serving tests (ADR-021)."""

import asyncio
import collections
import http.client
import json
import logging
import queue
import socket
import threading

import pytest
import uvicorn
from conftest import tailscale_json

from nexus import serving
from nexus.app import create_app
from nexus.config import Settings


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def has_ipv6() -> bool:
    try:
        with socket.socket(socket.AF_INET6) as probe:
            probe.bind(("::1", 0))
    except OSError:
        return False
    return True


needs_ipv6 = pytest.mark.skipif(not has_ipv6(), reason="IPv6 loopback unavailable")


def close_all(listeners):
    for listener in listeners:
        if listener.sock is not None:
            listener.sock.close()


def settings_for(tmp_path, *hosts, port=None):
    return Settings(data_dir=tmp_path / "data", hosts=hosts, port=port or free_port())


def port_is_free(port, family=socket.AF_INET, address="127.0.0.1") -> bool:
    try:
        socket.create_server((address, port), family=family).close()
    except OSError:
        return False
    return True


# --- harness for a real NexusServer -----------------------------------------------------------
# No test waits for a duration: rounds are driven through `Rounds`, actions on the loop go through
# `Running.on_loop`, a blocked runner is a `threading.Event` released by the fixture's teardown.
# Every delay below is only a guard followed by an assertion.

TAIL = "100.101.102.103"
TAIL6 = "fd7a:115c:a1e0::1"
GUARD = 10


def status(state="Running", ips=(TAIL, TAIL6)) -> str:
    return json.dumps({"BackendState": state, "TailscaleIPs": list(ips)})


CONFIRM = status()
STOPPED = status("Stopped")


class Records(logging.Handler):
    """Every record of the `nexus` loggers, with a thread-safe wait for a message."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.items: list[tuple[str, int, str, object]] = []
        self.cond = threading.Condition()

    def emit(self, record):
        with self.cond:
            self.items.append((record.name, record.levelno, record.getMessage(), record.exc_info))
            self.cond.notify_all()

    def wait_for(self, text: str, count: int = 1) -> bool:
        with self.cond:
            return self.cond.wait_for(
                lambda: sum(text in item[2] for item in self.items) >= count, GUARD
            )

    def serving(self, start: int = 0, level: int | None = None) -> list[str]:
        return [
            message for name, lvl, message, _ in self.items[start:]
            if name == "nexus.serving" and (level is None or lvl == level)
        ]

    def lines(self, start: int = 0) -> list[tuple[int, str]]:
        return [
            (lvl, message) for name, lvl, message, _ in self.items[start:]
            if name == "nexus.serving"
        ]

    def text(self) -> str:
        return "\n".join(item[2] for item in self.items)


@pytest.fixture
def records():
    handler = Records()
    logger = logging.getLogger("nexus")
    level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)


class Rounds:
    """`between_rounds` factory: reports the end of each round, then waits for the test's go."""

    def __init__(self):
        self._ends: queue.Queue = queue.Queue()
        self._last = None

    async def __call__(self):
        gate = asyncio.Event()
        self._ends.put((asyncio.get_running_loop(), gate))
        await gate.wait()

    def next_end(self):
        try:
            self._last = self._ends.get(timeout=GUARD)
        except queue.Empty:
            pytest.fail("the round did not end: the watch task is dead or stopped")

    def go(self):
        loop, gate = self._last
        loop.call_soon_threadsafe(gate.set)  # never `gate.set()` from this thread


class FakeRunner:
    """Scripted `tailscale status` output; the last item repeats. Exceptions are raised."""

    def __init__(self, calls, script=(), default=CONFIRM):
        self.calls = calls
        self.script = collections.deque(script)
        self.default = default
        self.gate: threading.Event | None = None
        self.entered = threading.Event()
        self.on_call = None
        self.run = None

    @property
    def count(self) -> int:
        return self.calls.count("runner")

    def __call__(self):
        self.calls.append("runner")
        if self.on_call is not None:
            self.on_call(self)
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(30)  # guard only: the fixture releases it
        item = self.script.popleft() if self.script else self.default
        if isinstance(item, BaseException):
            raise item
        return item


class FakeBind:
    """The tailnet address is served by a socket on 127.0.0.1 at `tail_port`."""

    def __init__(self, calls, tail_address, tail_port):
        self.calls = calls
        self.tail_address = tail_address
        self.tail_port = tail_port
        self.failures: dict[str, collections.deque] = {}
        self.on_bind = None
        self.run = None

    def fail(self, address, *outcomes):
        """Next binds of `address`: an exception to raise, or None to succeed."""
        self.failures.setdefault(address, collections.deque()).extend(outcomes)

    @property
    def tail_count(self) -> int:
        return self.calls.count("bind:tail")

    def __call__(self, address, port, family, backlog):
        label = "tail" if address == self.tail_address else "loop"
        self.calls.append(f"bind:{label}")
        pending = self.failures.get(address)
        if pending:
            outcome = pending.popleft()
            if outcome is not None:
                raise outcome
        if label == "tail":
            if self.on_bind is not None:
                self.on_bind(self)
            return serving.create_listener("127.0.0.1", self.tail_port, socket.AF_INET, backlog)
        return serving.create_listener(address, port, family, backlog)


def os_error(code: int) -> OSError:
    return OSError(code, "injected " + TAIL)


def http_get(port, path="/api/health", conn=None) -> int:
    own = conn is None
    conn = conn or http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        response.read()
        return response.status
    finally:
        if own:
            conn.close()


def assert_refuses(port):
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", port), timeout=5).close()


def assert_accepts(port):
    socket.create_connection(("127.0.0.1", port), timeout=5).close()


class Running:
    def __init__(self, server, settings, app, runner, bind, rounds, calls, port, tail_port):
        self.server, self.settings, self.app = server, settings, app
        self.runner, self.bind, self.rounds, self.calls = runner, bind, rounds, calls
        self.port, self.tail_port = port, tail_port
        self.done = threading.Event()
        self.loop = None
        self.thread = None
        self._stopped = False

    @property
    def loopback(self):
        return self.server._listeners[0]

    @property
    def tail(self):
        return next((x for x in self.server._listeners if x.tailnet), None)

    def on_loop(self, fn):
        async def call():
            return fn()

        return asyncio.run_coroutine_threadsafe(call(), self.loop).result(GUARD)

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        if self.runner.gate is not None:
            self.runner.gate.set()  # a blocked runner would hold the executor's thread
        self.server.should_exit = True
        assert self.done.wait(GUARD), "serve did not return"
        self.thread.join(GUARD)
        assert not self.thread.is_alive()
        for port in (self.port, self.tail_port):
            assert port_is_free(port), "a port is still held after the shutdown"


@pytest.fixture
def launch(tmp_path, records):
    started: list[Running] = []

    def start(
        *, hosts=("127.0.0.1", TAIL), script=(), default=CONFIRM, rounds=None, loop="asyncio",
        check_timeout=6.0, app=None, log_config=None, wait=True, on_call=None, on_bind=None,
        tail_fail=(), **config_options,
    ) -> Running:
        port = free_port()
        tail_port = free_port()
        while tail_port == port:
            tail_port = free_port()
        settings = Settings(data_dir=tmp_path / "data", hosts=hosts, port=port)
        calls: list[str] = []
        runner = FakeRunner(calls, script, default)
        bind = FakeBind(calls, settings.tailnet_host, tail_port)
        runner.on_call, bind.on_bind = on_call, on_bind
        if tail_fail:
            bind.fail(settings.tailnet_host, *tail_fail)
        app = app or create_app(settings, nodes_runner=tailscale_json)
        options = {"log_config": log_config, "access_log": False, "loop": loop,
                   "port": port, "timeout_keep_alive": 60}
        options.update(config_options)
        config = uvicorn.Config(app, **options)
        listeners = serving.open_loopback(settings, bind, config.backlog)
        if settings.tailnet_host:
            listeners.append(serving.Listener(
                settings.tailnet_host,
                socket.AF_INET6 if ":" in settings.tailnet_host else socket.AF_INET,
                tailnet=True, state=serving.FIRST_CHECK,
            ))
        server = serving.NexusServer(
            config, listeners, port=port, tailnet_status=runner, bind=bind,
            check_timeout=check_timeout, between_rounds=rounds,
        )
        run = Running(server, settings, app, runner, bind, rounds, calls, port, tail_port)
        runner.run = bind.run = run
        started.append(run)

        async def wrapper():
            run.loop = asyncio.get_running_loop()
            try:
                await server.serve(sockets=[x.sock for x in listeners if not x.tailnet])
            finally:
                run.done.set()  # no socket is closed here: only `shutdown` may free the ports

        run.thread = threading.Thread(
            target=lambda: asyncio.run(wrapper(), loop_factory=config.get_loop_factory()),
            daemon=True,
        )
        run.thread.start()
        if wait:
            assert records.wait_for("Nexus en service"), "the server did not start"
            if loop == "uvloop":
                assert "uvloop" in type(run.loop).__module__
        return run

    try:
        yield start
    finally:
        for run in started:
            run.stop()


def serving_warnings(records):
    return records.serving(level=logging.WARNING)
