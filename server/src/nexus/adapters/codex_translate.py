"""Pure translation of `codex exec --json` lines into facts (ADR-023, D3).

TO BE CONFIRMED ON THE FIRST REAL RUN OF LOÏC: the shapes below (`thread.started`,
`turn.started`, `item.completed` with `agent_message` / `command_execution` / `file_change`,
`turn.completed`, `turn.failed`, `error`) are those of codex-cli 0.166 as far as they are known
without running a model. Everything uncertain is isolated here: an unexpected line is ignored,
never raised, and the raw output (command output, reasoning) is never read into a fact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

TEXT_MAX = 500

FactKind = Literal["claimed", "working", "progress", "finished", "failed"]


@dataclass(frozen=True)
class Fact:
    """What one line says. `finished` is the end of a turn: the adapter judges the proof."""

    kind: FactKind
    subject: str
    body: str | None = None


def _cut(text: object) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    return text.strip()[:TEXT_MAX]


def _item(item: dict) -> Fact | None:
    match item.get("type"):
        case "agent_message":
            return Fact("progress", "Message de Codex", _cut(item.get("text")))
        case "command_execution":
            # The command only: its output may hold anything and is never kept.
            return Fact("progress", "Commande exécutée", _cut(item.get("command")))
        case "file_change":
            changes = item.get("changes")
            paths = [c.get("path") for c in changes if isinstance(c, dict)] if isinstance(
                changes, list) else []
            names = ", ".join(p for p in paths if isinstance(p, str))
            return Fact("progress", "Fichiers modifiés", _cut(names))
    return None  # reasoning and anything new: ignored


def translate_line(line: str) -> Fact | None:
    """The fact a JSONL line carries, or None for a line to ignore."""
    try:
        event = json.loads(line)
    except ValueError:
        return None
    if not isinstance(event, dict):
        return None
    match event.get("type"):
        case "thread.started":
            return Fact("claimed", "Codex a ouvert une session")
        case "turn.started":
            return Fact("working", "Codex travaille")
        case "item.completed":
            item = event.get("item")
            return _item(item) if isinstance(item, dict) else None
        case "turn.completed":
            return Fact("finished", "Codex a terminé son tour")
        case "turn.failed":
            error = event.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            return Fact("failed", "Codex a échoué", _cut(message) or "échec sans détail")
        case "error":
            return Fact("failed", "Codex a signalé une erreur",
                        _cut(event.get("message")) or "erreur sans détail")
    return None
