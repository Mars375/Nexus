"""Pure translation of `claude -p --output-format stream-json` lines into facts (ADR-023, D3).

Shapes as observed on claude 2.1.322 (spec 2026-11-11, §5.2 and §12.0): everything uncertain is
isolated here. An unexpected line is ignored, never raised, and neither the content of a file nor
the result of a tool is ever read into a fact. The isolation check lives on `system/init` and fails
closed: a departure is a `breach`, a field that cannot be read leaves the isolation unknown.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from nexus.adapters.claude_code_cli import EXPECTED_TOOLS
from nexus.adapters.text import cut

FactKind = Literal[
    "claimed", "working", "progress", "finished", "failed", "breach", "isolation_unknown"
]

FILE_TOOLS = frozenset({"Edit", "Write"})
KNOWN_ERRORS = frozenset({
    "success", "error_during_execution", "error_max_turns", "error_max_budget_usd",
    "error_max_structured_output_retries",
})
BREACH = "isolation non respectée"


@dataclass(frozen=True)
class Fact:
    """What one line says. `breach` and `isolation_unknown` stop the run; `finished` and `failed`
    come from the `result` line and are judged by the adapter once the process has exited."""

    kind: FactKind
    subject: str
    body: str | None = None
    payload: dict = field(default_factory=dict)


def _init(event: dict) -> tuple[Fact, ...]:
    tools, servers, mode = event.get("tools"), event.get("mcp_servers"), event.get("permissionMode")
    if (not isinstance(tools, list) or not all(isinstance(t, str) for t in tools)
            or not isinstance(servers, list) or not isinstance(mode, str)):
        return (Fact("isolation_unknown", "isolement de la session non vérifié"),)
    names = set(tools)
    if servers:
        why = "serveur MCP chargé"
    elif names - EXPECTED_TOOLS:
        why = "outil inattendu"  # the name is not copied
    elif EXPECTED_TOOLS - names:
        why = "outils inattendus"
    elif mode != "dontAsk":
        why = "mode de permission inattendu"
    else:
        model = cut(event.get("model"))
        return (Fact("claimed", "Claude Code a ouvert une session",
                     payload={"model": model} if model else {}),)
    return (Fact("breach", BREACH, f"{BREACH} : {why}"),)


def _is_file_tool(name: object) -> bool:
    return isinstance(name, str) and name in FILE_TOOLS  # a list or dict would be unhashable


def _assistant(event: dict) -> tuple[Fact, ...]:
    facts = [Fact("working", "Claude Code travaille")]
    message = event.get("message")
    blocks = message.get("content") if isinstance(message, dict) else None
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            body = cut(block.get("text"))
            if body:
                facts.append(Fact("progress", "Message de Claude Code", body))
        elif block.get("type") == "tool_use" and _is_file_tool(block.get("name")):
            given = block.get("input")
            body = cut(given.get("file_path")) if isinstance(given, dict) else None
            if body:
                facts.append(Fact("progress", "Fichier modifié", body))
    return tuple(facts)


def _int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _failure(event: dict) -> str:
    cause = cut(event.get("result"))
    errors = event.get("errors")
    if cause is None and isinstance(errors, list):
        cause = cut("; ".join(e for e in errors if isinstance(e, str)))
    if cause is not None:
        return cause
    subtype = event.get("subtype")
    known = isinstance(subtype, str) and subtype in KNOWN_ERRORS
    return f"échec sans détail ({subtype})" if known else "échec sans détail"


def _denials(event: dict) -> tuple[Fact, ...]:
    denials = event.get("permission_denials")
    names = []
    for denial in denials if isinstance(denials, list) else []:
        name = denial.get("tool_name") if isinstance(denial, dict) else None
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    body = cut(", ".join(names))
    return (Fact("progress", "Outils refusés", body),) if body else ()


def _result(event: dict) -> tuple[Fact, ...]:
    if event.get("is_error") is False and event.get("subtype") == "success":
        payload = {k: event[k] for k in ("num_turns", "duration_ms") if _int(event.get(k))}
        end = Fact("finished", "Claude Code a terminé son tour", payload=payload)
    else:
        end = Fact("failed", "Claude Code a échoué", _failure(event))
    return (end, *_denials(event))


def translate_line(text: str) -> tuple[Fact, ...]:
    """The facts a line carries, or `()` for a line to ignore."""
    try:
        event = json.loads(text)
    except (ValueError, RecursionError):  # not JSON, or nested beyond what Python can hold
        return ()
    if not isinstance(event, dict):
        return ()
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        return _init(event)
    if kind == "assistant":
        return _assistant(event)
    if kind == "result":
        return _result(event)
    return ()
