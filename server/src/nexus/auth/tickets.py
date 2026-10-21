"""WebSocket tickets (#57): single-use, short-lived, bound to the token that asked for one.

A browser cannot set `Authorization` on a WebSocket, so the UI trades its bearer token for a
ticket over HTTP and offers the ticket as a subprotocol. The store keeps only the SHA-256
digest of each ticket, in memory: a restart forgets every ticket (the client asks for a new
one), and only one server process is supported (ARCHITECTURE §3.3).
"""

from __future__ import annotations

import base64
import re
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field

from nexus.auth import tokens

PREFIX = "nxw_"
TTL_SECONDS = 30
MAX_PENDING_PER_TOKEN = 16

# ASCII alphabet spelled out: `\d` and `\w` accept other scripts' digits and letters.
_FORMAT = re.compile(rf"nxw_[A-Za-z0-9_-]{{{tokens.BODY_LENGTH}}}")


def is_well_formed(value: object) -> bool:
    """Checked before any hashing: a value of any other shape is never looked up."""
    return isinstance(value, str) and value.isascii() and _FORMAT.fullmatch(value) is not None


@dataclass(frozen=True)
class Grant:
    """What a consumed ticket stands for: the token that asked for it and that token's actor."""

    # The digest identifies the token across id reuse; kept out of `repr` (never logged).
    token_hash: str = field(repr=False)
    actor: str


@dataclass(frozen=True)
class _Entry:
    token_hash: str
    actor: str
    monotonic_at: float
    wall_at: float


class TicketStore:
    """In-memory tickets, indexed by digest, at most 16 pending per token, 30 s each.

    A ticket is expired when the monotonic clock advanced 30 s or more, or when the wall clock
    (UTC epoch seconds) advanced 30 s or more or went back. Both are needed: on Linux the
    monotonic clock stops during suspend, the wall clock does not. `nexus.clock.now` is not
    used on purpose: it returns datetimes sharing one `ZoneInfo`, and Python subtracts those
    ignoring the UTC offset, so the October clock change would give -59 min and refuse a fresh
    ticket.

    Issuing runs in FastAPI's thread pool and consuming in the event loop, so a
    `threading.Lock` guards the state (an `asyncio.Lock` would not protect the threads).
    """

    def __init__(
        self,
        monotonic: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self._monotonic = monotonic
        self._wall = wall
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}
        # Ticket digests per token digest, in issue order (oldest first).
        self._by_token: dict[str, OrderedDict[str, None]] = {}

    def _expired(self, entry: _Entry, monotonic: float, wall: float) -> bool:
        return (
            monotonic - entry.monotonic_at >= TTL_SECONDS
            or wall - entry.wall_at >= TTL_SECONDS
            or wall < entry.wall_at
        )

    def _forget(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is None:
            return
        bucket = self._by_token.get(entry.token_hash)
        if bucket is not None:
            bucket.pop(key, None)
            if not bucket:
                del self._by_token[entry.token_hash]

    def _purge(self, monotonic: float, wall: float) -> None:
        """Drop every expired entry (caller holds the lock)."""
        for key in [k for k, e in self._entries.items() if self._expired(e, monotonic, wall)]:
            self._forget(key)

    def issue(self, token_hash: str, actor: str) -> str:
        """A new ticket for this token; the oldest one of the token goes beyond 16 pending."""
        body = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
        ticket = PREFIX + body
        key = tokens.digest(ticket)
        with self._lock:
            monotonic, wall = self._monotonic(), self._wall()
            self._purge(monotonic, wall)
            bucket = self._by_token.setdefault(token_hash, OrderedDict())
            while len(bucket) >= MAX_PENDING_PER_TOKEN:
                self._forget(next(iter(bucket)))
                bucket = self._by_token.setdefault(token_hash, OrderedDict())
            self._entries[key] = _Entry(token_hash, actor, monotonic, wall)
            bucket[key] = None
        return ticket

    def consume(self, ticket: object) -> Grant | None:
        """The grant of a live ticket, removed on the way; None for anything else.

        The ticket is removed even when expired. The lookup is a dictionary access by digest:
        its timing says something about a digest, not about the ticket.
        """
        if not is_well_formed(ticket):
            return None
        key = tokens.digest(ticket)  # type: ignore[arg-type]
        with self._lock:
            monotonic, wall = self._monotonic(), self._wall()
            entry = self._entries.get(key)
            self._forget(key)
            self._purge(monotonic, wall)
        if entry is None or self._expired(entry, monotonic, wall):
            return None
        return Grant(entry.token_hash, entry.actor)

    def pending(self, token_hash: str) -> int:
        """Number of tickets waiting for this token (test accessor; expired ones not counted)."""
        with self._lock:
            self._purge(self._monotonic(), self._wall())
            return len(self._by_token.get(token_hash, ()))
