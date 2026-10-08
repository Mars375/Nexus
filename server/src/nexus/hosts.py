"""Host header check against DNS rebinding (ADR-020, D6), for HTTP and WebSocket.

Starlette's TrustedHostMiddleware splits `[::1]:8765` on ':' and breaks IPv6, hence this one.
The port is ignored (the Vite proxy sends `Host: localhost:5173`). A refused value is never
sent back.
"""

from __future__ import annotations

import ipaddress
import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# ASCII only: `\d` and `$` would accept non-ASCII digits and a trailing newline.
_PORT = re.compile(r"[0-9]{1,5}")
_NAME = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?")


def normalize_host(value: str) -> str | None:
    """A lowercase DNS name, IPv4 address or IPv6 literal (compressed, no brackets), else None."""
    if not value or not value.isascii():
        return None
    value = value.lower()
    if ":" in value:
        if "%" in value:
            return None  # scoped addresses are not hostnames
        try:
            return ipaddress.IPv6Address(value).compressed
        except ValueError:
            return None
    return value if _NAME.fullmatch(value) else None


def hostname_of(header: str | None) -> str | None:
    """The normalized host of a `Host` header (brackets removed, port dropped), else None."""
    if not header or not header.isascii():
        return None
    if header.startswith("["):
        end = header.find("]")
        if end < 0:
            return None
        host, rest = header[1:end], header[end + 1:]
        if rest and not (rest[0] == ":" and _PORT.fullmatch(rest[1:])):
            return None
        return normalize_host(host) if ":" in host else None
    host, separator, port = header.partition(":")
    if separator and not _PORT.fullmatch(port):
        return None
    return None if ":" in host else normalize_host(host)


def host_allowed(header: str | None, extra: frozenset[str]) -> bool:
    host = hostname_of(header)
    return host is not None and (host in LOOPBACK_HOSTS or host in extra)


class HostCheckMiddleware:
    def __init__(self, app: ASGIApp, allowed_hosts: frozenset[str] = frozenset()) -> None:
        self.app = app
        # Same normal form as the header: `fd7a:0:0::1` must match `Host: [fd7a::1]:8765`.
        self.allowed_hosts = frozenset(normalize_host(h) or h.lower() for h in allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = [v.decode("latin-1") for k, v in scope["headers"] if k == b"host"]
        # More than one Host header is ambiguous: refused (RFC 9112 §3.2).
        header = headers[0] if len(headers) == 1 else None
        if host_allowed(header, self.allowed_hosts):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 1008})  # handshake refused
            return
        response = JSONResponse(status_code=400, content={"detail": {
            "code": "invalid_host",
            "message": "en-tête Host non autorisé (voir NEXUS_ALLOWED_HOSTS)",
        }})
        await response(scope, receive, send)
