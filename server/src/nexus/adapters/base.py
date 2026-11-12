"""The contract of an adapter (ADR-023, D3): one per executor, no real one in this lot.

An adapter translates the native world of an executor (a process, a board, a log) into Nexus
events. Its methods block (a process, a network call): the supervisor calls them from a worker
thread, one run after the other, so each must return in bounded time. They never receive a
Nexus token (D4) and never echo a secret in an exception message: the supervisor logs only the
exception type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

# What `Adapter.name` may be, because it becomes the `origin` of the events: `publish()` accepts
# nothing else, and a free value could carry a secret.
ADAPTER_NAME = re.compile(r"[a-z][a-z0-9-]{0,31}")


@dataclass(frozen=True)
class RunInfo:
    """What an adapter may know about a run: a read-only snapshot, not the database row."""

    run_id: int
    ref: str  # nx-run-<n>
    task: str  # nx-task-<n>
    executor: str
    agent: str
    brief: str
    workdir: str | None
    external_ref: str | None
    status: str
    native_status: str | None
    watch_cursor: str | None
    # Row version when the snapshot was taken: the supervisor writes an end only from this state.
    version: int
    # Model alias chosen for the run (executors that serve models, ADR-023 addendum); else None.
    model: str | None = None


@dataclass(frozen=True)
class Dispatched:
    """The executor accepted the work: its own reference for it, and its own word for the state."""

    external_ref: str
    native_status: str | None = None


@dataclass(frozen=True)
class RunEvent:
    """One native fact already translated to the event protocol (a pure function of the log).

    `seq` is stable for a given fact (its position in the executor's log): the event id is
    derived from it (`nx-run-<n>-<seq>`), so reading the same fact again is a read-back.
    `at` is the instant the executor gives, never the clock of Nexus.
    """

    seq: int
    at: datetime
    kind: str
    subject: str
    body: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WatchResult:
    events: tuple[RunEvent, ...] = ()
    cursor: str | None = None  # opaque position to resume from; never a secret
    native_status: str | None = None


class LaunchUncertain(Exception):
    """`dispatch` could not tell whether the work started: the run is marked `unknown` and held
    until a human cancels it, and the launch is never repeated."""


class Adapter(Protocol):
    name: str  # origin of the events it publishes: matches ADAPTER_NAME (checked at registration)
    # Optional `agents: frozenset[str]` attribute: the agents this deployment serves, a subset of
    # what the executor works for (`runs.rules.AGENTS_OF`). Absent: all of them.
    # Optional `models` attribute, same idea: the model aliases this deployment serves, a subset
    # of `runs.rules.MODELS_OF`. Absent: all of them.

    def probe(self) -> bool:
        """Whether the executor is usable right now (binary present, service reachable)."""
        ...

    def dispatch(self, run: RunInfo) -> Dispatched:
        """Hand the work over. Called once per run, never again after a restart."""
        ...

    def watch(self, run: RunInfo) -> WatchResult:
        """Facts since `run.watch_cursor`; repeats are fine (publishing is idempotent)."""
        ...

    def cancel(self, run: RunInfo) -> None:
        """Stop the work. Raise if the stop is not confirmed: the run then stays open and the
        supervisor tries again, instead of freeing the executor while it may still be working."""
        ...

    def recover(self, run: RunInfo) -> str | None:
        """The native status of a run whose tracking was lost, or None when nothing is known."""
        ...
