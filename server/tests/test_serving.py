"""Loopback sockets and the watch of the listeners (ADR-021)."""

import asyncio
import collections
import contextlib
import errno
import http.client
import importlib.util
import json
import logging
import queue
import socket
import subprocess
import threading

import fastapi
import pytest
import uvicorn
from conftest import issue_ticket_http, issue_token, tailscale_json
from websockets.sync.client import connect

from nexus import nodes, serving
from nexus.app import create_app
from nexus.config import Settings
from nexus.live import LIVE_PROTOCOL


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


# --- check against Tailscale ------------------------------------------------------------------


def serving_warnings(records):
    return records.serving(level=logging.WARNING)


UNCONFIRMED = [
    status(ips=("100.101.102.104",)),
    status(ips=()),
    json.dumps({"BackendState": "Running", "TailscaleIPs": None}),
    json.dumps({"BackendState": "Running"}),
    status(ips=("not-an-address",)),
    "not json at all",
    json.dumps({"BackendState": "Running", "TailscaleIPs": TAIL}),
    json.dumps([]),
    status("Stopped"),
    status("NeedsLogin"),
    status("Starting"),
]


@pytest.mark.parametrize("output", UNCONFIRMED)
def test_unconfirmed_outputs_never_bind(launch, records, output):
    run = launch(rounds=Rounds(), default=output)
    for index in range(3):
        run.rounds.next_end()
        if index < 2:
            run.rounds.go()
    assert run.bind.tail_count == 0
    assert len(serving_warnings(records)) == 1
    assert len([m for m in records.serving(level=logging.DEBUG) if "non confirmée" in m]) == 2
    assert TAIL not in records.text() and "BackendState" not in records.text()
    assert output not in records.text()
    assert http_get(run.port) == 200
    assert_refuses(run.tail_port)


FAILURES = [
    (FileNotFoundError("tailscale " + TAIL), nodes.NOT_FOUND),
    (PermissionError("denied " + TAIL), nodes.NOT_FOUND),
    (subprocess.CalledProcessError(1, "tailscale"), nodes.UNREADABLE),
    (subprocess.TimeoutExpired("tailscale", 5), nodes.NO_ANSWER),
    (TimeoutError("late " + TAIL), nodes.NO_ANSWER),
    (RuntimeError(TAIL + " secret"), f"{nodes.CHECK_FAILED} (RuntimeError)"),
]


@pytest.mark.parametrize("exc,reason", FAILURES)
def test_runner_failures_keep_watching(launch, records, exc, reason):
    run = launch(rounds=Rounds(), script=[exc])
    run.rounds.next_end()
    warnings = serving_warnings(records)
    assert len(warnings) == 1 and reason in warnings[0]
    assert TAIL not in records.text() and "secret" not in records.text()
    assert "Traceback" not in records.text()
    assert all(item[3] is None for item in records.items)  # no exc_info anywhere
    run.rounds.go()
    run.rounds.next_end()  # the task is still alive at round 2
    assert run.bind.tail_count == 1  # and the default (confirming) runner opened the listener


def test_ipv6_tailnet_address_is_confirmed(launch, records):
    spelled_out = '{"BackendState": "Running", "TailscaleIPs": ["fd7a:115c:a1e0:0:0:0:0:1"]}'
    run = launch(hosts=(TAIL6,), default=spelled_out, rounds=Rounds())
    run.rounds.next_end()
    assert run.bind.tail_count == 1
    assert records.wait_for("écoute du tailnet ouverte")
    assert_accepts(run.tail_port)


def test_a_served_tailnet_address_stays_bound_across_five_confirmed_rounds(launch, records):
    """D9: every round checks a served address, but a confirmation never rebinds it."""
    run = launch(rounds=Rounds())
    for index in range(5):
        run.rounds.next_end()  # round `index + 1` has checked the address
        if index < 4:
            run.rounds.go()
    assert run.runner.count == 5
    assert run.bind.tail_count == 1
    assert run.on_loop(lambda: run.tail.state) == serving.SERVED
    assert_accepts(run.tail_port)
    assert records.serving(level=logging.WARNING) == []


def test_a_served_tailnet_address_no_longer_confirmed_is_closed(launch, records):
    run = launch(rounds=Rounds(), script=[CONFIRM, STOPPED, CONFIRM])
    run.rounds.next_end()  # round 1: opened
    connection = http.client.HTTPConnection("127.0.0.1", run.tail_port, timeout=5)
    assert http_get(run.tail_port, conn=connection) == 200
    assert run.runner.count == 1 and run.bind.tail_count == 1
    mark = len(records.items)

    run.rounds.go()
    run.rounds.next_end()  # round 2: Stopped
    assert run.runner.count == 2  # one call in the round
    assert run.bind.tail_count == 1  # and no reopening in the same round
    assert run.on_loop(lambda: len(run.server.servers)) == 1  # loopback only
    assert_refuses(run.tail_port)
    assert http_get(run.tail_port, conn=connection) == 200  # the accepted connection goes on
    assert records.serving(mark, logging.WARNING) == [
        "écoute du tailnet fermée : adresse non confirmée par Tailscale (Tailscale pas connecté)"
    ]
    mark = len(records.items)

    run.rounds.go()
    run.rounds.next_end()  # round 3: confirmed again
    assert run.bind.tail_count == 2
    assert "écoute du tailnet reprise" in records.serving(mark, logging.INFO)
    assert_accepts(run.tail_port)
    connection.close()


def test_reason_changes_warn_once_each(launch, records):
    run = launch(
        rounds=Rounds(),
        script=[status("NeedsLogin"), status("NeedsLogin"), FileNotFoundError("x")],
    )
    for index in range(3):
        run.rounds.next_end()
        if index < 2:
            run.rounds.go()
    levels = [
        lvl for name, lvl, message, _ in records.items
        if name == "nexus.serving" and "non confirmée" in message
    ]
    assert levels == [logging.WARNING, logging.DEBUG, logging.WARNING]


def test_loopback_is_tended_before_the_tailnet(launch, records):
    run = launch(rounds=Rounds())
    run.rounds.next_end()  # round 1: both open
    started = []
    real = serving._start_serving

    async def recording(server):
        started.append(1)
        run.calls.append("start_serving")
        await real(server)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(serving, "_start_serving", recording)
        run.on_loop(lambda: run.loopback.server.close())  # the loopback listener is lost
        run.runner.gate = threading.Event()
        run.runner.entered.clear()
        mark = len(run.calls)
        run.rounds.go()
        assert run.runner.entered.wait(GUARD)
        assert run.calls[mark:] == ["bind:loop", "start_serving", "runner"]
        assert http_get(run.port) == 200  # the reopened loopback answers, the runner still blocked
        run.runner.gate.set()
        run.rounds.next_end()


def test_shutdown_during_a_check_does_not_wait_for_the_runner(launch, records):
    gate = threading.Event()
    run = launch(rounds=Rounds(), on_call=lambda runner: setattr(runner, "gate", gate))
    assert run.runner.entered.wait(GUARD)
    run.server.should_exit = True
    # `serve` returned without waiting for the runner (nor for the 30 s interval).
    assert run.done.wait(GUARD)
    assert "surveillance des écoutes annulée" in records.serving(level=logging.DEBUG)
    gate.set()
    run.thread.join(GUARD)
    assert not run.thread.is_alive()
    assert run.bind.tail_count == 0


def test_shutdown_right_after_a_check_never_binds(launch):
    def stop_then_confirm(runner):
        runner.run.server.should_exit = True

    run = launch(rounds=Rounds(), on_call=stop_then_confirm)
    assert run.done.wait(GUARD)
    assert run.bind.tail_count == 0
    assert len(run.server.servers) == 1


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
