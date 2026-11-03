"""Several listeners, loss and resumption of the tailnet listener (ADR-021)."""

import asyncio
import errno
import http.client
import importlib.util
import json
import logging
import socket

import fastapi
import pytest
import serving_support
import uvicorn
from conftest import issue_ticket_http, issue_token
from serving_support import (
    CONFIRM,
    GUARD,
    STOPPED,
    TAIL,
    Rounds,
    assert_accepts,
    assert_refuses,
    free_port,
    http_get,
    needs_ipv6,
    os_error,
    port_is_free,
    serving_warnings,
    settings_for,
)
from websockets.sync.client import connect

from nexus import serving
from nexus.live import LIVE_PROTOCOL

launch = serving_support.launch
records = serving_support.records


# --- several listeners, loss and resumption ---------------------------------------------------


@needs_ipv6
def test_localhost_serves_the_same_app_on_both_sockets(launch):
    run = launch(hosts=("localhost",), rounds=Rounds())
    assert http_get(run.port) == 200
    with socket.create_connection(("::1", run.port), timeout=5) as sock:
        sock.sendall(b"GET /api/health HTTP/1.1\r\nHost: [::1]\r\nConnection: close\r\n\r\n")
        assert sock.recv(64).startswith(b"HTTP/1.1 200")


def hello_on(port, run, ticket_port=None):
    """The `hello` frame served on `port`, with a ticket issued on `ticket_port`."""
    token = issue_token(run.app)
    ticket = issue_ticket_http(ticket_port or port, token)
    with connect(f"ws://127.0.0.1:{port}/api/ws", subprotocols=[LIVE_PROTOCOL, ticket]) as ws:
        return json.loads(ws.recv())


LOOPS = [
    "asyncio",
    pytest.param("uvloop", marks=pytest.mark.skipif(
        importlib.util.find_spec("uvloop") is None,
        reason="uvloop is not installed on this platform",
    )),
]


@pytest.mark.parametrize("loop", LOOPS)
def test_tailnet_listener_resumes_without_restart(launch, records, loop):
    unavailable = os_error(errno.EADDRNOTAVAIL)
    run = launch(rounds=Rounds(), loop=loop, tail_fail=[unavailable, unavailable, None])
    for index in range(3):
        run.rounds.next_end()
        assert http_get(run.port) == 200  # the loopback answered at every round
        if index < 2:
            run.rounds.go()
    warnings = serving_warnings(records)
    assert len(warnings) == 1 and TAIL not in warnings[0]
    assert records.serving(level=logging.INFO).count("écoute du tailnet ouverte") == 1
    first = hello_on(run.port, run)
    second = hello_on(run.tail_port, run, ticket_port=run.port)  # a loopback ticket works here
    assert first["instance"] == second["instance"] == run.app.state.live_instance
    assert first["type"] == second["type"] == "hello"


@pytest.fixture
def isolated_logging():
    """Restore every logger uvicorn's dictConfig touches (it sets `nexus.propagate = False`)."""
    names = ("", "uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi", "nexus",
             "nexus.access")
    saved = {}
    for name in names:
        logger = logging.getLogger(name)
        saved[name] = (logger.level, list(logger.handlers), list(logger.filters),
                       logger.propagate, logger.disabled)
    try:
        yield
    finally:
        for name, (level, handlers, filters, propagate, disabled) in saved.items():
            logger = logging.getLogger(name)
            logger.setLevel(level)
            logger.handlers[:] = handlers
            logger.filters[:] = filters
            logger.propagate = propagate
            logger.disabled = disabled


def test_after_resume_websocket_lines_keep_no_query(launch, isolated_logging):
    import io

    from nexus.logs import uvicorn_log_config

    stream = io.StringIO()
    config = uvicorn_log_config()
    for handler in config["handlers"].values():
        handler["stream"] = stream
    unavailable = os_error(errno.EADDRNOTAVAIL)
    # dictConfig removes the `records` handler: the rounds are the only synchronisation here.
    run = launch(rounds=Rounds(), log_config=config, tail_fail=[unavailable, None], wait=False)
    run.rounds.next_end()  # round 1: the tailnet address is unavailable
    run.rounds.go()
    run.rounds.next_end()  # round 2: opened without a restart
    cursors = "history_after=987654321098&events_after=876543210987"
    token = issue_token(run.app)
    ticket = issue_ticket_http(run.port, token)
    url = f"ws://127.0.0.1:{run.tail_port}/api/ws?{cursors}"
    with connect(url, subprotocols=[LIVE_PROTOCOL, ticket]) as ws:
        assert "hello" in ws.recv()
    run.stop()
    output = stream.getvalue()
    assert '"WebSocket /api/ws"' in output
    assert "987654321098" not in output and "876543210987" not in output
    assert "history_after" not in output
    assert ticket not in output and TAIL not in output
    assert 'HTTP/1.1"' not in output  # uvicorn.access stays mute


@pytest.mark.parametrize("loop", LOOPS)
@pytest.mark.parametrize("which", ["tailnet", "loopback"])
def test_a_lost_listener_is_reopened_in_the_same_round(launch, records, loop, which):
    run = launch(rounds=Rounds(), loop=loop)
    run.rounds.next_end()
    listener = run.tail if which == "tailnet" else run.loopback
    port = run.tail_port if which == "tailnet" else run.port
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    assert http_get(port, conn=connection) == 200
    old = listener.server
    run.on_loop(old.close)  # the listening socket is gone, the server object is not served
    assert serving.listener_lost(listener.sock)
    mark = len(records.items)

    run.rounds.go()
    run.rounds.next_end()
    warnings = records.serving(mark, logging.WARNING)
    assert len(warnings) == 1 and "perdue" in warnings[0]
    assert TAIL not in records.text()
    assert not run.on_loop(lambda: old in run.server.servers)
    assert listener.server is not old and listener.state == serving.SERVED
    assert http_get(port, conn=connection) == 200  # the connection it had accepted goes on
    assert http_get(port) == 200  # and the listener answers again, in the same round
    connection.close()


def unstarted(tmp_path, bind=serving.create_listener, hosts=("127.0.0.1", TAIL)):
    """A NexusServer that never runs, to drive one step of the watch task by hand."""
    settings = settings_for(tmp_path, *hosts)
    config = uvicorn.Config(fastapi.FastAPI(), log_config=None, port=settings.port)
    listeners = [serving.Listener(
        "127.0.0.1", socket.AF_INET, tailnet=False, state=serving.SERVED
    ), serving.Listener(TAIL, socket.AF_INET, tailnet=True, state=serving.FIRST_CHECK)]
    server = serving.NexusServer(
        config, listeners, port=settings.port, tailnet_status=lambda: CONFIRM, bind=bind
    )
    server.servers = []
    return server, listeners[1], settings


def test_a_dead_socket_is_lost_even_if_the_server_still_serves(tmp_path, records):
    class StillServing:
        def is_serving(self):
            return True

        def close(self):
            pass

    server, _, _ = unstarted(tmp_path)
    dead = socket.socket()
    dead.close()
    fake = StillServing()
    listener = serving.Listener(
        "127.0.0.1", socket.AF_INET, tailnet=False, state=serving.SERVED, sock=dead, server=fake
    )
    server.servers = [fake]
    assert server._tend_lost(listener) is True
    assert server.servers == []
    assert listener.state == serving.WAITING and listener.reason == ("lost",)
    assert len(records.serving(level=logging.WARNING)) == 1


def test_closing_a_dead_asyncio_server_is_absorbed(launch, records):
    run = launch(rounds=Rounds())
    run.rounds.next_end()
    # The socket dies under a server that still serves: `Server.close()` then raises ValueError
    # on the asyncio selector loop.
    run.on_loop(run.tail.sock.close)
    mark = len(records.items)
    run.rounds.go()
    run.rounds.next_end()  # the task survived the ValueError
    warnings = records.serving(mark, logging.WARNING)
    assert len(warnings) == 1 and "perdue" in warnings[0]
    assert records.serving(mark, logging.ERROR) == []


@pytest.mark.parametrize("which", ["loopback", "tailnet"])
def test_repeated_resume_failures_warn_once_per_state(launch, records, which):
    run = launch(rounds=Rounds())
    run.rounds.next_end()
    listener, address = (run.loopback, "127.0.0.1") if which == "loopback" else (run.tail, TAIL)
    in_use, unavailable = os_error(errno.EADDRINUSE), os_error(errno.EADDRNOTAVAIL)
    run.bind.fail(address, in_use, in_use, in_use, unavailable, None)
    run.on_loop(listener.server.close)

    def advance():
        mark = len(records.items)
        run.rounds.go()
        run.rounds.next_end()
        return records.lines(mark)

    taken = "port de la boucle locale pris par un autre processus"
    first = advance()
    assert [lvl for lvl, _ in first] == [logging.WARNING, logging.WARNING]
    assert "perdue" in first[0][1]
    assert (taken in first[1][1]) == (which == "loopback")
    if which == "tailnet":
        assert f"bind en échec (OSError, errno {errno.EADDRINUSE})" in first[1][1]
    assert [lvl for lvl, _ in advance()] == [logging.DEBUG]
    assert [lvl for lvl, _ in advance()] == [logging.DEBUG]
    changed = advance()
    assert [lvl for lvl, _ in changed] == [logging.WARNING]
    assert f"errno {errno.EADDRNOTAVAIL}" in changed[0][1]
    resumed = advance()
    assert [lvl for lvl, _ in resumed] == [logging.INFO] and "reprise" in resumed[0][1]
    assert TAIL not in records.text()


def _flaky_create_server(real):
    state = {"left": 1}

    async def flaky(loop, factory, sock, backlog):
        if state["left"]:
            state["left"] -= 1
            raise OSError(errno.EMFILE, "injected " + TAIL)
        return await real(loop, factory, sock, backlog)

    return flaky


def _flaky_start_serving(real):
    state = {"left": 1}

    async def flaky(server):
        if state["left"]:
            state["left"] -= 1
            raise OSError(errno.EMFILE, "injected " + TAIL)
        await real(server)

    return flaky


@pytest.mark.parametrize("seam,make", [
    ("_create_server", _flaky_create_server), ("_start_serving", _flaky_start_serving),
])
def test_serving_failures_close_the_socket_and_retry(launch, records, monkeypatch, seam, make):
    monkeypatch.setattr(serving, seam, make(getattr(serving, seam)))
    run = launch(rounds=Rounds())
    run.rounds.next_end()
    assert run.on_loop(lambda: len(run.server.servers)) == 1
    assert port_is_free(run.tail_port)
    warnings = records.serving(level=logging.WARNING)
    assert len(warnings) == 1 and f"mise en service en échec (OSError, errno {errno.EMFILE})" in (
        warnings[0]
    )
    assert TAIL not in records.text()
    run.rounds.go()
    run.rounds.next_end()  # the next round reopens it
    assert_accepts(run.tail_port)
    assert run.on_loop(lambda: len(run.server.servers)) == 2


def test_a_listener_that_dies_in_start_serving_is_not_reported_as_resumed(
    launch, records, monkeypatch
):
    """The uvloop way: `start_serving` returns normally after closing and detaching the socket."""

    async def dies(server):
        server.close()

    monkeypatch.setattr(serving, "_start_serving", dies)
    run = launch(rounds=Rounds())
    run.rounds.next_end()
    assert records.serving(level=logging.WARNING) == [
        "écoute du tailnet en attente : mise en service en échec ; nouvel essai toutes les 30 s"
    ]
    assert run.on_loop(lambda: len(run.server.servers)) == 1
    run.rounds.go()
    run.rounds.next_end()  # the same failure again: DEBUG only
    assert len(records.serving(level=logging.WARNING)) == 1
    assert not any("ouverte" in m or "reprise" in m for m in records.serving())


def _bound(opened):
    def bind(address, port, family, backlog):
        sock = serving.create_listener("127.0.0.1", free_port(), socket.AF_INET, backlog)
        opened.append(sock)
        return sock

    return bind


def test_reopen_absorbs_only_oserror(tmp_path, records, monkeypatch):
    def raising(address, port, family, backlog):
        raise RuntimeError("injected " + TAIL)

    server, tail, _ = unstarted(tmp_path, bind=raising)
    with pytest.raises(RuntimeError):
        asyncio.run(server._reopen(tail))
    assert records.serving(level=logging.WARNING) == []


@pytest.mark.parametrize("exc", [RuntimeError("injected"), asyncio.CancelledError()])
def test_a_failing_create_server_closes_the_bound_socket_and_raises(
    tmp_path, records, monkeypatch, exc
):
    opened: list[socket.socket] = []
    server, tail, _ = unstarted(tmp_path, bind=_bound(opened))

    async def failing(loop, factory, sock, backlog):
        raise exc

    monkeypatch.setattr(serving, "_create_server", failing)
    with pytest.raises(type(exc)):
        asyncio.run(server._reopen(tail))
    assert [s.fileno() for s in opened] == [-1]
    assert records.serving(level=logging.WARNING) == []
    assert server.servers == []


def test_shutdown_between_bind_and_append(launch):
    def raise_the_flag(bind):
        bind.run.server.should_exit = True

    run = launch(rounds=Rounds(), on_bind=raise_the_flag)
    assert run.done.wait(GUARD)
    assert run.bind.tail_count == 1
    assert len(run.server.servers) == 1  # the server created for the tailnet was closed, unused
    assert port_is_free(run.tail_port)


def _lost_socket(sock):
    raise RuntimeError("injected " + TAIL + " secret")


async def _broken_start_serving(server):
    raise RuntimeError("injected " + TAIL + " secret")


@pytest.mark.parametrize("scenario", ["served", "resuming", "waiting", "no-tailnet"])
def test_dead_watch_task_closes_the_tailnet(launch, records, monkeypatch, scenario):
    options = {"rounds": Rounds()}
    if scenario == "resuming":
        options["tail_fail"] = [os_error(errno.EADDRNOTAVAIL), None]
    if scenario == "waiting":
        options["default"] = STOPPED
    if scenario == "no-tailnet":
        options["hosts"] = ("127.0.0.1",)
    run = launch(**options)
    run.rounds.next_end()
    connection = http.client.HTTPConnection("127.0.0.1", run.tail_port, timeout=5)
    if scenario == "served":
        assert http_get(run.tail_port, conn=connection) == 200
        monkeypatch.setattr(serving, "listener_lost", _lost_socket)
    elif scenario == "resuming":
        monkeypatch.setattr(serving, "_start_serving", _broken_start_serving)
    else:
        monkeypatch.setattr(serving, "listener_lost", _lost_socket)
    mark = len(records.items)
    run.rounds.go()
    assert records.wait_for("surveillance des écoutes arrêtée")
    errors = records.serving(mark, logging.ERROR)
    closed = scenario in ("served", "resuming")
    assert errors == [
        "surveillance des écoutes arrêtée"
        + (" : écoute du tailnet fermée" if closed else "") + " (RuntimeError)"
    ]
    assert TAIL not in records.text() and "secret" not in records.text()
    assert all(item[3] is None for item in records.items)
    assert http_get(run.port) == 200  # the loopback keeps serving
    if closed:
        assert run.on_loop(lambda: len(run.server.servers)) == 1
        assert_refuses(run.tail_port)
        if scenario == "served":
            assert http_get(run.tail_port, conn=connection) == 200  # accepted before: goes on
    connection.close()
    # `stop()` (fixture) checks the shutdown completes and every port is free afterwards.


class Fatal(BaseException):
    """Not an `Exception`: nothing in the watch task catches it."""


def test_a_watch_task_killed_by_a_base_exception_does_not_block_the_shutdown(launch, monkeypatch):
    run = launch(rounds=Rounds())
    run.rounds.next_end()

    def fatal(sock):
        raise Fatal

    monkeypatch.setattr(serving, "listener_lost", fatal)
    run.rounds.go()
    watch = run.server._watch
    asyncio.run_coroutine_threadsafe(asyncio.wait({watch}), run.loop).result(GUARD)
    assert watch.done()
    # `stop()` (fixture) checks that `shutdown` still closed every listener.
    run.stop()
    assert run.done.is_set()


def test_no_rebind_while_the_address_stays_unconfirmed_after_a_close(launch):
    """D9: the check precedes EVERY bind, a reopening after a close included."""
    run = launch(rounds=Rounds(), script=[CONFIRM, STOPPED, STOPPED])
    run.rounds.next_end()  # round 1: opened
    assert (run.runner.count, run.bind.tail_count) == (1, 1)
    for expected_calls in (2, 3):  # round 2 closes, round 3 must not reopen
        run.rounds.go()
        run.rounds.next_end()
        assert run.runner.count == expected_calls  # one runner call per round
        assert run.bind.tail_count == 1
        assert_refuses(run.tail_port)


def test_a_lost_tailnet_listener_is_not_rebound_when_unconfirmed(launch):
    run = launch(rounds=Rounds())
    run.rounds.next_end()
    assert run.bind.tail_count == 1
    run.runner.default = STOPPED
    run.on_loop(run.tail.server.close)  # the socket dies
    run.rounds.go()
    run.rounds.next_end()
    assert run.bind.tail_count == 1
    assert run.runner.count == 2
    assert_refuses(run.tail_port)
