"""Loopback listeners and the Tailscale check of the serving layer (ADR-021)."""

from __future__ import annotations

import asyncio
import errno
import ipaddress
import logging
import socket
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

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
