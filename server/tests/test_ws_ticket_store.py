"""WebSocket ticket store (#57): shape, single use, lifetime on two clocks, cap, races."""

import re
import sys
import threading

import pytest

from nexus.auth import tickets, tokens
from nexus.auth.tickets import Grant, TicketStore


class Clocks:
    """Injectable monotonic and wall clocks, moved by hand."""

    def __init__(self, monotonic=1000.0, wall=1_792_000_000.0):
        self.m = monotonic
        self.w = wall

    def monotonic(self):
        return self.m

    def wall(self):
        return self.w

    def store(self):
        return TicketStore(monotonic=self.monotonic, wall=self.wall)


def test_issue_gives_prefix_and_43_url_safe_characters():
    store = TicketStore()
    ticket = store.issue(1, "loic")
    assert re.fullmatch(r"nxw_[A-Za-z0-9_-]{43}", ticket)
    assert store.issue(1, "loic") != ticket


@pytest.mark.parametrize("bad", [
    "nxw_" + "A" * 42, "nxw_" + "A" * 44, "nxw_" + "١" * 43, "nxw_" + "A" * 42 + "=",
    "nxt_" + "A" * 43, "NXW_" + "A" * 43, "nxw_" + "A" * 43 + "\n", "", None, 42, b"nxw_",
])
def test_malformed_tickets_are_not_well_formed(bad):
    assert tickets.is_well_formed(bad) is False


def test_a_generated_ticket_is_well_formed():
    assert tickets.is_well_formed(TicketStore().issue(1, "loic")) is True


def test_consume_grants_once():
    store = TicketStore()
    ticket = store.issue(7, "codex")
    assert store.consume(ticket) == Grant(7, "codex")
    assert store.consume(ticket) is None


def test_consume_refuses_unknown_tickets():
    store = TicketStore()
    store.issue(1, "loic")
    assert store.consume("nxw_" + "Z" * 43) is None


def test_consume_never_hashes_a_malformed_value(monkeypatch):
    calls = []
    monkeypatch.setattr(tokens, "digest", lambda value: calls.append(value) or "x")
    store = TicketStore()
    for bad in ("", "nxw_short", "nxt_" + "A" * 43, "nxw_" + "A" * 44, None, 3):
        assert store.consume(bad) is None
    assert calls == []


def test_a_ticket_lives_just_under_thirty_seconds():
    clocks = Clocks()
    store = clocks.store()
    ticket = store.issue(1, "loic")
    clocks.m += 29.999
    clocks.w += 29.999
    assert store.consume(ticket) == Grant(1, "loic")


def test_a_ticket_of_exactly_thirty_seconds_is_refused():
    clocks = Clocks()
    store = clocks.store()
    ticket = store.issue(1, "loic")
    clocks.m += 30.0
    clocks.w += 30.0
    assert store.consume(ticket) is None


def test_a_wall_clock_set_back_refuses_the_ticket():
    clocks = Clocks()
    store = clocks.store()
    ticket = store.issue(1, "loic")
    clocks.m += 1
    clocks.w -= 1
    assert store.consume(ticket) is None


def test_a_suspended_machine_refuses_the_ticket():
    """The monotonic clock stops during sleep on Linux; the wall clock does not."""
    clocks = Clocks()
    store = clocks.store()
    ticket = store.issue(1, "loic")
    clocks.w += 31
    assert store.consume(ticket) is None


def test_the_autumn_clock_change_does_not_refuse_a_fresh_ticket():
    """UTC seconds: nothing jumps at 03:00 CEST -> 02:00 CET (2026-10-25, 01:00 UTC)."""
    clocks = Clocks(wall=1792889990.0)
    store = clocks.store()
    ticket = store.issue(1, "loic")
    clocks.m += 15
    clocks.w = 1792890005.0
    assert store.consume(ticket) == Grant(1, "loic")


def test_an_expired_ticket_is_removed_when_presented():
    clocks = Clocks()
    store = clocks.store()
    ticket = store.issue(1, "loic")
    clocks.m += 31
    clocks.w += 31
    assert store.consume(ticket) is None
    clocks.m -= 31
    clocks.w -= 31
    assert store.consume(ticket) is None


def test_the_seventeenth_ticket_evicts_the_first():
    store = TicketStore()
    other = store.issue(2, "codex")
    issued = [store.issue(1, "loic") for _ in range(17)]
    assert store.pending(1) == 16
    assert store.consume(issued[0]) is None
    assert store.consume(issued[1]) == Grant(1, "loic")
    assert store.pending(2) == 1
    assert store.consume(other) == Grant(2, "codex")


def test_expired_tickets_stop_counting():
    clocks = Clocks()
    store = clocks.store()
    for _ in range(5):
        store.issue(1, "loic")
    clocks.m += 31
    clocks.w += 31
    store.issue(1, "loic")
    assert store.pending(1) == 1
    other = store.issue(2, "codex")
    clocks.m += 31
    clocks.w += 31
    assert store.consume(other) is None
    assert store.pending(1) == 0


def test_the_store_keeps_digests_only():
    store = TicketStore()
    ticket = store.issue(1, "loic")
    entries = "".join(repr(vars(e)) for e in store._entries.values())
    dumped = repr(store) + repr(vars(store)) + entries
    assert ticket not in dumped
    assert ticket[len("nxw_"):] not in dumped
    assert tokens.digest(ticket) in store._entries


@pytest.fixture
def fast_switching():
    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(previous)


def _run_threads(count, target):
    barrier = threading.Barrier(count)
    errors = []

    def runner(index):
        barrier.wait()
        try:
            target(index)
        except BaseException as error:  # surfaced below
            errors.append(error)

    threads = [threading.Thread(target=runner, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors


def test_concurrent_issues_on_one_token_keep_exactly_16(fast_switching):
    store = TicketStore()
    issued: list[str] = []

    def work(_):
        mine = [store.issue(1, "loic") for _ in range(32)]
        issued.extend(mine)

    _run_threads(32, work)
    assert len(issued) == 1024
    assert store.pending(1) == 16
    assert sum(store.consume(t) is not None for t in issued) == 16


def test_a_second_token_keeps_its_16_under_concurrent_issues(fast_switching):
    store = TicketStore()
    first: list[str] = []
    second: list[str] = []

    def work(index):
        if index % 2:
            second.extend(store.issue(2, "codex") for _ in range(16))
        else:
            first.extend(store.issue(1, "loic") for _ in range(64))

    _run_threads(32, work)
    assert store.pending(1) == 16 and store.pending(2) == 16
    assert sum(store.consume(t) is not None for t in second) == 16
    assert sum(store.consume(t) is not None for t in first) == 16


def test_concurrent_consumes_never_grant_twice(fast_switching):
    store = TicketStore()
    handed = [store.issue(1, "loic") for _ in range(16)]
    granted: list[Grant] = []
    lock = threading.Lock()

    def work(index):
        if index % 2:
            for _ in range(8):
                store.issue(1, "loic")
        else:
            for ticket in handed:
                result = store.consume(ticket)
                if result is not None:
                    with lock:
                        granted.append((ticket, result))

    _run_threads(32, work)
    tickets_granted = [ticket for ticket, _ in granted]
    assert len(tickets_granted) == len(set(tickets_granted))
    assert store.pending(1) <= 16
