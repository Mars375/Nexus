"""Shared helpers for the runs tests: a fake adapter (the only one that exists in this lot)."""

from __future__ import annotations

from datetime import UTC, datetime

from nexus.adapters.base import Dispatched, RunEvent, WatchResult

T1 = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 5, 9, 5, tzinfo=UTC)
T3 = datetime(2026, 11, 5, 9, 10, tzinfo=UTC)


def chain() -> list[RunEvent]:
    """claimed -> working -> done, with native instants (never the clock of the server)."""
    return [
        RunEvent(seq=1, at=T1, kind="claimed", subject="pris en charge"),
        RunEvent(seq=2, at=T2, kind="working", subject="au travail"),
        RunEvent(seq=3, at=T3, kind="done", subject="terminé", evidence=["commit:abc123"]),
    ]


class FakeAdapter:
    """Replays the same script on every `watch`, like an executor whose log is re-read."""

    name = "fake"

    def __init__(self, script: list[RunEvent] | None = None) -> None:
        self.script = chain() if script is None else script
        self.dispatched: list[str] = []
        self.cancelled: list[str] = []
        self.watched: list[str] = []
        self.fail_dispatch = False
        self.on_dispatch = None  # called while the executor is being reached, like a click
        self.on_watch = None
        self.fail_cancel = False
        self.external_ref = None  # overrides the reference given at dispatch

    def probe(self) -> bool:
        return True

    def dispatch(self, run) -> Dispatched:
        if self.on_dispatch:
            self.on_dispatch()
        if self.fail_dispatch:
            raise RuntimeError("boom token=secret")
        self.dispatched.append(run.ref)
        return Dispatched(
            external_ref=self.external_ref or f"ext-{run.run_id}", native_status="started")

    def watch(self, run) -> WatchResult:
        self.watched.append(run.ref)
        if self.on_watch:
            self.on_watch()
        return WatchResult(events=tuple(self.script), cursor="c1", native_status="seen")

    def cancel(self, run) -> None:
        if self.fail_cancel:
            raise RuntimeError("cancel failed")
        self.cancelled.append(run.ref)

    def recover(self, run):
        return None


def register(client, executor: str = "codex", adapter: FakeAdapter | None = None) -> FakeAdapter:
    adapter = adapter or FakeAdapter()
    client.app.state.adapters.register(executor, adapter)
    return adapter


def make_task(client, **fields) -> str:
    body = {"title": "Pont", "objective": "Lire", "next_action": "lancer"} | fields
    res = client.post("/api/tasks", json=body)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def dispatch(client, task: str, *, actor: str = "loic", **fields):
    body = {"executor": "codex", "agent": "codex", "client_key": "k1",
            "brief": "Fais le travail"} | fields
    return client.post(f"/api/tasks/{task}/runs", json=body, headers={"X-Nexus-Actor": actor})


def code_of(res) -> str:
    return res.json()["detail"]["code"]


def tick(client) -> None:
    from nexus.runs import supervisor

    supervisor.tick(client.app.state.sessionmaker, client.app.state.adapters)


def events_of(client, task: str) -> list[dict]:
    return list(reversed(client.get("/api/events", params={"task": task}).json()))
