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

from nexus.adapters.text import cut

FactKind = Literal["claimed", "working", "progress", "finished", "failed", "error", "breach"]
BREACH_SUBJECT = "Isolation de la session non respectée"
# Fixed words (spec #186, §5.4): neither the server nor the tool is copied.
MCP_BREACH = "isolation non respectée : outil MCP appelé"


@dataclass(frozen=True)
class Fact:
    """What one line says. `finished` is the end of a turn: the adapter judges the proof.

    `error` is a signal only (codex-cli prints one per reconnection attempt): `failed`, from
    `turn.failed`, is what decides a failure (#176). `breach` (an MCP tool called: no server
    should be in sight) stops the run at once.
    """

    kind: FactKind
    subject: str
    body: str | None = None


def _item(item: dict) -> Fact | None:
    match item.get("type"):
        case "mcp_tool_call":
            return Fact("breach", BREACH_SUBJECT, MCP_BREACH)
        case "agent_message":
            body = cut(item.get("text"))
            return Fact("progress", "Message de Codex", body) if body else None
        case "command_execution":
            # The command only: its output may hold anything and is never kept.
            body = cut(item.get("command"))
            return Fact("progress", "Commande exécutée", body) if body else None
        case "web_search":
            # Turned off in the argv (#202): shown if one still happens, with the query only.
            return Fact("progress", "Recherche web", cut(item.get("query")))
        case "file_change":
            changes = item.get("changes")
            paths = [c.get("path") for c in changes if isinstance(c, dict)] if isinstance(
                changes, list) else []
            names = ", ".join(p for p in paths if isinstance(p, str))
            body = cut(names)
            return Fact("progress", "Fichiers modifiés", body) if body else None
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
        case "item.started":  # only a breach is told this early; the rest waits for completion
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "mcp_tool_call":
                return _item(item)
        case "turn.completed":
            return Fact("finished", "Codex a terminé son tour")
        case "turn.failed":
            error = event.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            return Fact("failed", "Codex a échoué", cut(message) or "échec sans détail")
        case "error":
            return Fact("error", "Codex a signalé une erreur",
                        cut(event.get("message")) or "erreur sans détail")
    return None
