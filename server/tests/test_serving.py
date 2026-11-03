"""Loopback sockets and start-up of the serving layer (ADR-021)."""

import asyncio
import contextlib
import errno
import logging
import socket
import threading

import fastapi
import pytest
import serving_support
import uvicorn
from serving_support import (
    GUARD,
    STOPPED,
    TAIL,
    FakeRunner,
    Rounds,
    assert_accepts,
    assert_refuses,
    close_all,
    http_get,
    needs_ipv6,
    port_is_free,
    settings_for,
)

from nexus import serving

launch = serving_support.launch
records = serving_support.records


# --- loopback sockets -------------------------------------------------------------------------


def test_ipv4_loopback_opens_one_socket(tmp_path):
    settings = settings_for(tmp_path, "127.0.0.1")
    listeners = serving.open_loopback(settings, serving.create_listener, 128)
    try:
        assert [(x.address, x.family, x.tailnet, x.state) for x in listeners] == [
            ("127.0.0.1", socket.AF_INET, False, serving.SERVED)
        ]
        assert listeners[0].sock.getsockname()[:2] == ("127.0.0.1", settings.port)
    finally:
        close_all(listeners)


@needs_ipv6
def test_ipv6_loopback_opens_one_socket(tmp_path):
    settings = settings_for(tmp_path, "::1")
    listeners = serving.open_loopback(settings, serving.create_listener, 128)
    try:
        assert [(x.address, x.family) for x in listeners] == [("::1", socket.AF_INET6)]
    finally:
        close_all(listeners)


@needs_ipv6
def test_localhost_opens_both_loopback_addresses(tmp_path):
    settings = settings_for(tmp_path, "localhost")
    listeners = serving.open_loopback(settings, serving.create_listener, 128)
    try:
        assert [x.address for x in listeners] == ["127.0.0.1", "::1"]
    finally:
        close_all(listeners)


def failing_ipv6(code):
    def bind(address, port, family, backlog):
        if address == "::1":
            raise OSError(code, "injected")
        return serving.create_listener(address, port, family, backlog)

    return bind


@pytest.mark.parametrize("code", [errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT])
def test_localhost_falls_back_to_ipv4_when_ipv6_is_missing(tmp_path, caplog, code):
    caplog.set_level(logging.DEBUG, logger="nexus")
    settings = settings_for(tmp_path, "localhost")
    listeners = serving.open_loopback(settings, failing_ipv6(code), 128)
    try:
        assert [x.address for x in listeners] == ["127.0.0.1"]
    finally:
        close_all(listeners)
    assert [r.levelno for r in caplog.records if r.name == "nexus.serving"] == [logging.DEBUG]


@pytest.mark.parametrize("code", [errno.EADDRINUSE, errno.EACCES])
def test_localhost_refuses_to_start_when_ipv6_loopback_fails_otherwise(tmp_path, code):
    settings = settings_for(tmp_path, "localhost")
    opened = []

    def bind(address, port, family, backlog):
        sock = failing_ipv6(code)(address, port, family, backlog)
        opened.append(sock)
        return sock

    with pytest.raises(serving.LoopbackBindError) as error:
        serving.open_loopback(settings, bind, 128)
    assert error.value.__cause__.errno == code
    assert [s.fileno() for s in opened] == [-1]
    assert port_is_free(settings.port)


def test_a_loopback_bind_failure_is_fatal(tmp_path):
    settings = settings_for(tmp_path, "127.0.0.1")
    with socket.create_server(("127.0.0.1", settings.port)):
        with pytest.raises(serving.LoopbackBindError) as error:
            serving.open_loopback(settings, serving.create_listener, 128)
    assert isinstance(error.value.__cause__, OSError)
    assert error.value.__cause__.errno == errno.EADDRINUSE


def test_no_getaddrinfo(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("getaddrinfo must not be called")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    settings = settings_for(tmp_path, "localhost")
    listeners = serving.open_loopback(settings, serving.create_listener, 128)
    try:
        assert listeners[0].address == "127.0.0.1"
    finally:
        close_all(listeners)


# --- start-up ---------------------------------------------------------------------------------


def test_loopback_serves_before_the_first_tailscale_check(launch, records):
    seen = {}

    def on_call(runner):
        seen["started"] = runner.run.server.started
        seen["status"] = http_get(runner.run.port)  # the loop is free during `to_thread`

    # No `rounds`: the real 30 s wait separates the rounds, so the tailnet listener can only
    # open on the immediate first round.
    run = launch(on_call=on_call)
    assert records.wait_for("écoute du tailnet ouverte")
    assert seen == {"started": True, "status": 200}
    assert_accepts(run.tail_port)
    assert records.serving(level=logging.WARNING) == []
    assert run.calls.count("runner") == 1  # the loopback never calls the runner


def test_unconfirmed_tailnet_at_startup_serves_loopback_only(launch, records):
    run = launch(rounds=Rounds(), default=STOPPED)
    run.rounds.next_end()
    assert len(records.serving(level=logging.WARNING)) == 1
    assert_refuses(run.tail_port)
    assert http_get(run.port) == 200


def test_startup_line_mentions_the_pending_tailnet_check_without_the_address(launch, records):
    gate = threading.Event()

    def hold(runner):
        runner.gate = gate

    run = launch(rounds=Rounds(), on_call=hold)
    assert run.runner.entered.wait(GUARD)
    lines = [m for m in records.serving(level=logging.INFO) if "Nexus en service" in m]
    assert len(lines) == 1
    assert "tailnet : contrôle auprès de Tailscale à venir" in lines[0]
    assert TAIL not in records.text()
    assert records.serving(level=logging.WARNING) == []  # nothing before round 1 ends


def test_startup_line_has_no_word_about_the_tailnet_without_an_address(launch, records):
    launch(hosts=("127.0.0.1",), rounds=Rounds())
    lines = [m for m in records.serving() if "Nexus en service" in m]
    assert len(lines) == 1 and "tailnet" not in lines[0]


def test_failed_lifespan_starts_no_watch_task(tmp_path, records):
    @contextlib.asynccontextmanager
    async def failing(_app):
        raise RuntimeError("startup failed")
        yield  # pragma: no cover

    settings = settings_for(tmp_path, "127.0.0.1", TAIL)
    calls: list[str] = []
    runner = FakeRunner(calls)
    config = uvicorn.Config(
        fastapi.FastAPI(lifespan=failing), log_config=None, lifespan="on", port=settings.port
    )
    listeners = serving.open_loopback(settings, serving.create_listener, config.backlog)
    listeners.append(
        serving.Listener(TAIL, socket.AF_INET, tailnet=True, state=serving.FIRST_CHECK)
    )
    server = serving.NexusServer(
        config, listeners, port=settings.port, tailnet_status=runner, bind=serving.create_listener
    )
    try:
        with pytest.raises(SystemExit) as exit_info:
            asyncio.run(server.serve(sockets=[listeners[0].sock]))
    finally:
        close_all(listeners)
    assert exit_info.value.code == 3
    assert server._watch is None
    assert calls == []
    assert not any("Nexus en service" in m for m in records.serving())
