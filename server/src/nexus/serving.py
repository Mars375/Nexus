"""Serving Nexus on the loopback and, when asked, on the tailnet (ADR-021).

One `uvicorn.Server` serves every listening socket. The loopback sockets are opened before
the server starts and a failure there is fatal. The tailnet address is never bound here
without a check: a watch task opens it once Tailscale confirms the address, reopens it when
it is lost, and closes it when Tailscale stops confirming it.

No message written here repeats the tailnet address, `str(exc)`, `exc_info` or anything
Tailscale printed: only fixed words, the type of an exception and its `errno` (ADR-006).
"""

from __future__ import annotations

import asyncio
import errno
import ipaddress
import logging
import socket
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import partial

import uvicorn

from nexus import nodes
from nexus.config import Settings

log = logging.getLogger("nexus.serving")

# States of a listener (ADR-021 D10).
SERVED = "served"
FIRST_CHECK = "first-check"  # tailnet only: not yet checked, not a failure
WAITING = "waiting"

Bind = Callable[[str, int, socket.AddressFamily, int], socket.socket]

# A fixed table, never `getaddrinfo`: a hosts file must not choose the listening address.
LOOPBACK_SOCKETS: dict[str, tuple[tuple[str, socket.AddressFamily], ...]] = {
    "127.0.0.1": (("127.0.0.1", socket.AF_INET),),
    "::1": (("::1", socket.AF_INET6),),
    "localhost": (("127.0.0.1", socket.AF_INET), ("::1", socket.AF_INET6)),
}
# IPv6 is missing on this machine: `localhost` then serves 127.0.0.1 only.
_NO_IPV6 = frozenset({errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL})


class LoopbackBindError(Exception):
    """A loopback socket could not be opened; `__cause__` is the `OSError`."""


@dataclass
class Listener:
    address: str
    family: socket.AddressFamily
    tailnet: bool
    state: str = WAITING
    # Why it is not served, as a hashable key: a change of key is a change of state (journal).
    reason: tuple | None = None
    sock: socket.socket | None = None
    server: asyncio.Server | None = None
    # Bound but not yet served: closed by `_fail_closed` if the watch task dies in between.
    pending_sock: socket.socket | None = field(default=None, repr=False)
    # Whether it was ever served: the first tailnet bind is "ouverte", the next ones "reprise".
    opened: bool = False


def create_listener(
    address: str, port: int, family: socket.AddressFamily, backlog: int
) -> socket.socket:
    return socket.create_server((address, port), family=family, backlog=backlog)


def open_loopback(settings: Settings, bind: Bind, backlog: int) -> list[Listener]:
    """Open the loopback sockets of `NEXUS_HOST`; any failure but a missing IPv6 is fatal."""
    listeners: list[Listener] = []
    try:
        for address, family in LOOPBACK_SOCKETS[settings.loopback_host]:
            try:
                sock = bind(address, settings.port, family, backlog)
            except OSError as exc:
                if family == socket.AF_INET6 and listeners and exc.errno in _NO_IPV6:
                    log.debug("IPv6 absent : localhost n'écoute que 127.0.0.1")
                    continue
                raise LoopbackBindError from exc
            listeners.append(
                Listener(address, family, tailnet=False, state=SERVED, sock=sock, opened=True)
            )
    except BaseException:
        for listener in listeners:
            if listener.sock is not None:
                listener.sock.close()
        raise
    return listeners


async def check_tailnet(
    runner: nodes.Runner,
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    timeout: float,
) -> str | None:
    """None if Tailscale confirms `address`, else a fixed-word reason. Fails closed.

    The runner is synchronous: `wait_for` frees this task at the deadline but cannot stop the
    thread, so an injected runner must return by itself in bounded time.
    """
    try:
        output = await asyncio.wait_for(asyncio.to_thread(runner), timeout)
        return nodes.tailnet_address_reason(output, address)
    # TimeoutError is an OSError subclass: it must come before the OSError clause.
    except (TimeoutError, subprocess.TimeoutExpired):
        return nodes.NO_ANSWER
    except subprocess.CalledProcessError:
        return nodes.UNREADABLE
    except OSError:
        return nodes.NOT_FOUND
    except Exception as exc:
        # Deliberate gap from the review checklist's narrow-except rule (ADR-021): the check must
        # fail closed whatever an injected runner does, and an exception that escaped would stop
        # the watch of every listener. The bug stays visible: its type is logged by the caller.
        return f"{nodes.CHECK_FAILED} ({type(exc).__name__})"



# Seams the tests replace.


def listener_lost(sock: socket.socket) -> bool:
    """A dead listening socket has `fileno() == -1`, whatever `Server.is_serving()` says.

    Under the Windows proactor loop the accept loop closes the socket for good on the first
    `AcceptEx` error; under uvloop a listen-callback error closes and detaches it. In both
    cases the `Server` object keeps reporting that it serves.
    """
    return sock.fileno() == -1


async def _create_server(
    loop: asyncio.AbstractEventLoop,
    factory: Callable[[], asyncio.Protocol],
    sock: socket.socket,
    backlog: int,
) -> asyncio.Server:
    return await loop.create_server(factory, sock=sock, backlog=backlog, start_serving=False)


async def _start_serving(server: asyncio.Server) -> None:
    await server.start_serving()


def _where(listener: Listener) -> str:
    return "du tailnet" if listener.tailnet else "de la boucle locale"


class NexusServer(uvicorn.Server):
    """One `uvicorn.Server` for all the listeners, plus a task that tends them (ADR-021).

    It relies on uvicorn internals (`servers`, `server_state`, `lifespan`, the signature of
    `http_protocol_class`); the real-server tests are the guard on each uvicorn upgrade.
    """

    def __init__(
        self,
        config: uvicorn.Config,
        listeners: list[Listener],
        *,
        port: int,
        tailnet_status: nodes.Runner,
        bind: Bind = create_listener,
        check_timeout: float = 6.0,
        interval: float = 30.0,
        between_rounds: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(config)
        self._listeners = listeners  # loopback ones first, then the tailnet one
        self._port = port
        self._status = tailnet_status
        self._bind = bind
        self._check_timeout = check_timeout
        self._interval = interval
        # A factory, not a coroutine: a coroutine can only be awaited once. When given, it alone
        # does the waiting and `interval` only feeds the messages.
        self._between_rounds = between_rounds or (lambda: asyncio.sleep(interval))
        self._watch: asyncio.Task | None = None

    @property
    def _tail(self) -> Listener | None:
        return next((x for x in self._listeners if x.tailnet), None)

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets)
        if not self.started:
            return
        loopback = [x for x in self._listeners if not x.tailnet]
        for listener, server in zip(loopback, self.servers, strict=True):
            listener.server = server
        watching = not self.should_exit
        if watching:
            self._watch = asyncio.create_task(self._watch_listeners())
        line = "Nexus en service sur le port %d (%d écoute(s) de boucle locale)"
        if watching and self._tail is not None:
            line += " ; tailnet : contrôle auprès de Tailscale à venir"
        log.info(line, self._port, len(loopback))

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        try:
            if self._watch is not None:
                self._watch.cancel()
                # `wait` neither re-raises the cancellation nor the task's own exception.
                await asyncio.wait({self._watch})
        finally:
            await super().shutdown(sockets)

    # --- the watch task -----------------------------------------------------------------

    async def _watch_listeners(self) -> None:
        try:
            first = True
            while not self.should_exit:
                if not first:
                    await self._between_rounds()
                    if self.should_exit:
                        break
                first = False
                await self._round()
        except asyncio.CancelledError:
            log.debug("surveillance des écoutes annulée")
            raise
        except Exception as exc:
            # Whatever failed, an unwatched tailnet listener would stay open for good: close it.
            self._fail_closed(type(exc).__name__)

    async def _round(self) -> None:
        for listener in self._listeners:
            await self._tend(listener)

    async def _tend(self, listener: Listener) -> None:
        if listener.state == SERVED:
            if not self._tend_lost(listener):
                if listener.tailnet:
                    reason = await self._check(listener)
                    if reason is not None:
                        self._drop(listener)
                        self._enter(
                            listener, ("unconfirmed", reason),
                            "écoute du tailnet fermée : adresse non confirmée par Tailscale (%s)",
                            reason,
                        )
                return  # a listener closed here was just checked: no second call this round
        await self._reopen(listener)

    def _tend_lost(self, listener: Listener) -> bool:
        """Close and forget a served listener whose socket died; True if it was lost."""
        if not listener_lost(listener.sock):
            return False
        self._drop(listener)
        self._enter(
            listener, ("lost",), "écoute perdue sur %s : reprise toutes les %d s",
            "le tailnet" if listener.tailnet else "la boucle locale", int(self._interval),
        )
        return True

    async def _check(self, listener: Listener) -> str | None:
        address = ipaddress.ip_address(listener.address)
        return await check_tailnet(self._status, address, self._check_timeout)

    async def _reopen(self, listener: Listener) -> None:
        if listener.tailnet:
            reason = await self._check(listener)
            if reason is not None:
                self._enter(
                    listener, ("unconfirmed", reason),
                    "écoute du tailnet en attente : adresse non confirmée par Tailscale (%s) ; "
                    "nouvel essai toutes les %d s", reason, int(self._interval),
                )
                return
        # Checked right before the bind, with no `await` between the two.
        if self.should_exit:
            return
        try:
            sock = self._bind(listener.address, self._port, listener.family, self.config.backlog)
        except OSError as exc:
            self._bind_failed(listener, exc)
            return
        listener.pending_sock = sock
        config = self.config
        try:
            server = await _create_server(
                asyncio.get_running_loop(),
                lambda: config.http_protocol_class(
                    config=config, server_state=self.server_state, app_state=self.lifespan.state
                ),
                sock,
                config.backlog,
            )
        except OSError as exc:
            sock.close()
            listener.pending_sock = None
            self._serving_failed(listener, exc)
            return
        except BaseException:
            sock.close()  # `pending_sock` stays set: the last resort knows it was being opened
            raise
        # No `await` from here to the append.
        if self.should_exit:
            server.close()
            sock.close()
            listener.pending_sock = None
            return
        self.servers.append(server)
        listener.server, listener.sock, listener.pending_sock = server, sock, None
        try:
            await _start_serving(server)
        except OSError as exc:
            self._drop(listener)
            self._serving_failed(listener, exc)
            return
        # uvloop closes and detaches the socket on a `listen` error without raising.
        if listener_lost(sock):
            self._drop(listener)
            self._serving_failed(listener, None)
            return
        self._served(listener)

    def _drop(self, listener: Listener) -> None:
        server = listener.server
        if server is not None:
            try:
                server.close()
            except (OSError, ValueError):
                # An asyncio server whose socket is already dead raises ValueError here.
                pass
            if server in self.servers:
                self.servers.remove(server)
        if listener.sock is not None:
            listener.sock.close()
        listener.server = listener.sock = None

    # --- journal, one line per change of state --------------------------------------------

    def _enter(self, listener: Listener, reason: tuple, message: str, *args: object) -> None:
        """WARNING on entering a failure or changing its reason, DEBUG when it repeats."""
        level = logging.WARNING if listener.reason != reason else logging.DEBUG
        listener.state, listener.reason = WAITING, reason
        log.log(level, message, *args)

    def _bind_failed(self, listener: Listener, exc: OSError) -> None:
        reason = ("bind", exc.errno)
        if exc.errno == errno.EADDRINUSE and not listener.tailnet:
            self._enter(
                listener, reason,
                "port de la boucle locale pris par un autre processus : les clients locaux "
                "(proxy Vite) peuvent lui envoyer leur jeton ; nouvel essai toutes les %d s",
                int(self._interval),
            )
            return
        self._enter(
            listener, reason, "écoute %s en attente : bind en échec (%s, errno %s) ; "
            "nouvel essai toutes les %d s",
            _where(listener), type(exc).__name__, exc.errno, int(self._interval),
        )

    def _serving_failed(self, listener: Listener, exc: OSError | None) -> None:
        if exc is None:
            self._enter(
                listener, ("serving",),
                "écoute %s en attente : mise en service en échec ; nouvel essai toutes les %d s",
                _where(listener), int(self._interval),
            )
            return
        self._enter(
            listener, ("serving", type(exc).__name__, exc.errno),
            "écoute %s en attente : mise en service en échec (%s, errno %s) ; "
            "nouvel essai toutes les %d s",
            _where(listener), type(exc).__name__, exc.errno, int(self._interval),
        )

    def _served(self, listener: Listener) -> None:
        listener.state, listener.reason = SERVED, None
        if not listener.opened:
            listener.opened = True
            log.info("écoute %s ouverte", _where(listener))
        else:
            log.info("écoute %s reprise", _where(listener))

    def _fail_closed(self, type_name: str) -> None:
        """The watch task died: stop serving the tailnet, which nothing checks any more."""
        tail = self._tail
        if tail is not None and (tail.server is not None or tail.pending_sock is not None):
            self._drop(tail)
            if tail.pending_sock is not None:
                tail.pending_sock.close()
                tail.pending_sock = None
            tail.state = WAITING
            log.error(
                "surveillance des écoutes arrêtée : écoute du tailnet fermée (%s)", type_name
            )
        else:
            log.error("surveillance des écoutes arrêtée (%s)", type_name)


async def serve(
    config: uvicorn.Config,
    settings: Settings,
    *,
    tailnet_status: nodes.Runner | None = None,
    bind: Bind = create_listener,
    check_timeout: float = 6.0,
    interval: float = 30.0,
    between_rounds: Callable[[], Awaitable[None]] | None = None,
) -> bool:
    """Serve Nexus until it is told to stop; True if it started (uvicorn's `started`).

    Writes nothing before `server.serve()`. A loopback bind failure raises `LoopbackBindError`.
    """
    listeners = open_loopback(settings, bind, config.backlog)
    try:
        if (tailnet := settings.tailnet_host) is not None:
            family = socket.AF_INET6 if ":" in tailnet else socket.AF_INET
            listeners.append(Listener(tailnet, family, tailnet=True, state=FIRST_CHECK))
        if tailnet_status is None:
            tailnet_status = partial(nodes.run_tailscale_self, settings.tailscale_bin)
        server = NexusServer(
            config, listeners, port=settings.port, tailnet_status=tailnet_status, bind=bind,
            check_timeout=check_timeout, interval=interval,
            between_rounds=between_rounds,
        )
        await server.serve(sockets=[x.sock for x in listeners if not x.tailnet])
        return server.started
    finally:
        for listener in listeners:
            for sock in (listener.sock, listener.pending_sock):
                if sock is not None:
                    sock.close()
