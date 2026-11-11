"""Pure translation of `hermes kanban show --json` into facts (spec §4, ADR-023 D3).

The event list has no ids: the position (from 1) of an event is its `seq`, the cursor is the
position of the last event consumed. Nothing here reads the disk or calls Hermes: attachments
read as proofs (§4.4) come in as an argument. An unexpected event or field is consumed without a
fact, never raised: the list of Hermes event kinds grows with every version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nexus.adapters.base import RunEvent
from nexus.adapters.text import cut

SEQ_WATCHDOG = 1_000_000  # reserved: the maximum duration (no Hermes event carries it)
SEQ_MISSING = 1_000_001  # reserved: the task vanished from Hermes
GRACE_SECONDS = 120  # one dispatcher turn and a margin
FILES_MAX = 20
COMMIT_CHARS = 12
COMMIT_SHA = re.compile(r"[0-9a-fA-F]{7,40}")
UNTAKEN = frozenset({"triage", "todo", "ready", "scheduled"})
INTERRUPTED = frozenset({"timed_out", "crashed", "stale", "spawn_failed", "reclaimed",
                         "worker_lost"})
REFUSED = frozenset({"completion_blocked_hallucination", "completion_blocked_empty_result"})
NO_REASON = "Helios a bloqué la tâche sans dire pourquoi"
PLAN = ("Nexus ne suit plus cette tâche Hermes : réponds dans un nouveau brief et confie la "
        "tâche à nouveau, ou abandonne-la")


@dataclass(frozen=True)
class Translation:
    events: tuple[RunEvent, ...]
    cursor: str
    native_status: str | None
    needs_proofs: bool = False  # a completion was met: read the attachments and translate again
    archive: bool = False  # the close asks for the Hermes task to be archived first (§4.6)


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _first_text(payload: dict, *keys: str) -> str | None:
    for key in keys:
        text = cut(payload.get(key))
        if text:
            return text
    return None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _fact(seq: int, at: datetime, kind: str, subject: str, body: str | None = None,
          payload: dict | None = None, evidence: list[str] | None = None) -> RunEvent:
    # `seq` in the payload keeps two identical progress facts distinct (anti-noise). A progress
    # needs a body (`progress_empty` otherwise): its subject stands in when Hermes gave no text.
    if kind == "progress" and not body:
        body = subject
    return RunEvent(seq=seq, at=at, kind=kind, subject=subject, body=body,
                    payload={"seq": seq} | (payload or {}), evidence=evidence or [])


def _native_status(task: dict, runs: list) -> str | None:
    status = task.get("status")
    if not isinstance(status, str):
        return None
    last = _dict(runs[-1]) if runs else {}
    outcome = last.get("outcome")
    return f"{status}/{outcome}" if isinstance(outcome, str) and outcome else status


def _completion(seq: int, at: datetime, ev: dict, show: dict, task_id: str,
                proofs: list[str]) -> RunEvent:
    row = next((_dict(r) for r in show.get("runs") or []
                if isinstance(r, dict) and r.get("id") == ev.get("run_id")), {})
    metadata = _dict(row.get("metadata"))
    summary = (_first_text(row, "summary") or _first_text(_dict(ev.get("payload")), "summary")
               or cut(show.get("latest_summary")))
    info: dict[str, Any] = {}
    files = metadata.get("changed_files")
    if isinstance(files, list):
        info["changed_files"] = [c for c in (cut(f) for f in files[:FILES_MAX]) if c]
    if _int(metadata.get("tests_run")) is not None:
        info["tests_run"] = metadata["tests_run"]
    commit = metadata.get("commit")
    # Only a hexadecimal hash, then shortened: a full hash would be masked, and cutting any
    # other text before the scanner could leave a secret's prefix in clear.
    if isinstance(commit, str) and COMMIT_SHA.fullmatch(commit.strip()):
        info["commit"] = commit.strip()[:COMMIT_CHARS]
    where = f"hermes:nexus/{task_id}"
    if proofs:
        return _fact(seq, at, "done", "Helios a terminé (Hermes)", summary, info, [*proofs, where])
    body = "Hermes a terminé sans livrable relu : à relire" + (f"\n{summary}" if summary else "")
    return _fact(seq, at, "review", "Helios a terminé sans livrable relu", body, info, [where])


def _one(seq: int, at: datetime, ev: dict, kind: str, counts: dict, show: dict, task_id: str,
         proofs: list[str]) -> RunEvent | None:
    payload = _dict(ev.get("payload"))
    if kind == "claimed" and counts["claimed"] == 1:
        return _fact(seq, at, "claimed", "Helios a pris la tâche (Hermes)")
    if kind == "spawned":
        if counts["spawned"] == 1:
            return _fact(seq, at, "working", "Helios travaille")
        return _fact(seq, at, "progress", "nouvelle tentative de Hermes")
    if kind == "review_requested":
        return _fact(seq, at, "progress", "relecture Hermes en cours")
    if kind == "changes_requested":
        return _fact(seq, at, "progress", "le relecteur Hermes demande des changements",
                     _first_text(payload, "reason", "summary"))
    if kind in INTERRUPTED:
        return _fact(seq, at, "progress", f"tentative interrompue ({kind})",
                     _first_text(payload, "error", "reason"))
    if kind in REFUSED:
        return _fact(seq, at, "progress", "Hermes a refusé la fin annoncée")
    if kind == "completed":
        return _completion(seq, at, ev, show, task_id, proofs)
    if kind == "blocked":
        cause = _first_text(payload, "reason", "cause") or NO_REASON
        return _fact(seq, at, "blocked", "Helios a bloqué la tâche", None,
                     {"cause": cause, "plan": PLAN})
    if kind == "gave_up":
        trigger = _first_text(payload, "trigger_outcome") or "cause inconnue"
        detail = _first_text(payload, "error", "reason") or "sans détail"
        cause = cut(f"Hermes a abandonné après un échec ({trigger}) : {detail}")
        return _fact(seq, at, "failed", "Hermes a abandonné la tâche", None,
                     {"cause": cause or "Hermes a abandonné la tâche"})
    if kind == "archived":
        return _fact(seq, at, "failed", "Tâche archivée dans Hermes", None,
                     {"cause": "tâche archivée dans Hermes, hors de Nexus"})
    return None


def translate(show: dict, after: int, *, proofs: list[str], now: datetime,
              max_seconds: float) -> Translation:
    """The facts at positions after `after`, the new cursor, and what the adapter must still do."""
    task = _dict(show.get("task"))
    raw = show.get("events")
    events = raw if isinstance(raw, list) else []
    runs = show.get("runs") if isinstance(show.get("runs"), list) else []
    task_id = task.get("id") if isinstance(task.get("id"), str) else "?"
    counts = {"claimed": 0, "spawned": 0}
    facts: list[RunEvent] = []
    cursor, closed, needs_proofs, archive = after, False, False, False
    for position, ev in enumerate(events, 1):
        kind = _dict(ev).get("kind")
        if isinstance(kind, str) and kind in counts:
            counts[kind] += 1  # counted before the cursor: "first" means first ever
        if position <= after:
            continue
        if closed:
            break
        cursor = position
        stamp = _dict(ev).get("created_at")
        if not isinstance(kind, str) or _int(stamp) is None:
            continue
        try:
            at = datetime.fromtimestamp(stamp, UTC)
        except (OverflowError, OSError, ValueError):  # out of range: a malformed event
            continue
        fact = _one(position, at, ev, kind, counts, show, task_id, proofs)
        if fact is None:
            continue
        facts.append(fact)
        if kind in ("completed", "blocked", "gave_up", "archived"):
            closed = True
            needs_proofs = kind == "completed"
            archive = kind in ("blocked", "gave_up")
    created = _int(task.get("created_at"))
    if (not closed and created is not None
            and now.timestamp() - created > max_seconds + GRACE_SECONDS):
        if task.get("status") in UNTAKEN:
            cause = "Hermes n'a pas pris la tâche dans le délai (passerelle arrêtée ?)"
        else:
            cause = f"durée maximale dépassée ({max_seconds / 60:g} min) : tâche Hermes archivée"
        facts.append(_fact(SEQ_WATCHDOG, now, "failed", "Durée maximale dépassée", None,
                           {"cause": cause}))
        archive = True
    return Translation(tuple(facts), str(cursor), _native_status(task, runs), needs_proofs,
                       archive)
