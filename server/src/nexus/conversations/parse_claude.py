"""Extraction of one Claude Code session line (spec §3.1, §6.5; ADR-025 D3, D5).

Pure: bytes in, a `ClaudeLine` out. Only `user` and `assistant` lines are read, and only their
human text or the model's `text` blocks; titles come from `custom-title` and `ai-title`. Every
other type is ignored without reading any other field of it, and the fields the spec forbids
(`toolUseResult`, `mcpMeta`, tool payloads, thinking, prompts, account ids) are never read.
Every kept text goes through `masking` before it leaves this module. Reasons are fixed codes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from nexus.conversations import masking
from nexus.conversations.masking import ParsedMessage

BOM = b"\xef\xbb\xbf"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# Lines Claude Code writes itself (API errors, "No response requested"): not model answers.
SYNTHETIC = "<synthetic>"
_TITLES = {"custom-title": ("customTitle", "custom"), "ai-title": ("aiTitle", "ai")}
AUTHORS = {"user": "loic", "assistant": "claude"}


@dataclass(frozen=True)
class ClaudeLine:
    kind: Literal["message", "title", "ignored", "skipped", "bad"]
    reason: str | None = None
    message: ParsedMessage | None = None
    title: str | None = None
    title_kind: Literal["custom", "ai"] | None = None
    workspace: str | None = None
    git_branch: str | None = None
    session_id_differs: bool = False


IGNORED = ClaudeLine("ignored")


def _bad(reason: str) -> ClaudeLine:
    return ClaudeLine("bad", reason)


def _skipped(reason: str) -> ClaudeLine:
    return ClaudeLine("skipped", reason)


def _instant(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        return None
    return at if at.tzinfo is not None else None


def _texts(blocks: list) -> str:
    return "\n\n".join(
        block["text"] for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    )


def _user_text(line: dict, content: object) -> tuple[str, str] | ClaudeLine:
    if "origin" not in line:
        author = "unknown"
    else:
        origin = line["origin"]
        if not (isinstance(origin, dict) and origin.get("kind") == "human"):
            return _skipped("origin")
        author = AUTHORS["user"]
    if isinstance(content, str):
        return author, content
    if not isinstance(content, list):
        return _bad("field")
    if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return _skipped("tool_result")
    return author, _texts(content)


def _assistant_text(content: object) -> str | ClaudeLine:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return _bad("field")
    return _texts(content)


def _decode(data: bytes, at_file_start: bool) -> dict | ClaudeLine:
    if at_file_start and data.startswith(BOM):
        data = data[len(BOM):]
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError:
        return _bad("utf8")
    if not raw.strip():
        return IGNORED
    try:
        line = json.loads(raw)
    except ValueError:
        return _bad("json")
    return line if isinstance(line, dict) else _bad("not_object")


def parse_line(data: bytes, *, at_file_start: bool, stem: str,
               not_before: datetime) -> ClaudeLine:
    """One line (without its `\\n`); `stem` is the session file name without `.jsonl`."""
    line = _decode(data, at_file_start)
    if isinstance(line, ClaudeLine):
        return line
    kind = line.get("type")
    if kind in _TITLES:
        key, title_kind = _TITLES[kind]
        title = masking.mask_field(line.get(key), masking.TITLE_MAX)
        return ClaudeLine("title", title=title, title_kind=title_kind) if title else IGNORED
    if kind not in AUTHORS:
        return IGNORED
    if line.get("isSidechain") is True:
        return _skipped("sidechain")
    if line.get("isMeta") is True:
        return _skipped("meta")
    line_id, at, message = line.get("uuid"), _instant(line.get("timestamp")), line.get("message")
    if not (isinstance(line_id, str) and _UUID.fullmatch(line_id)) or at is None:
        return _bad("field")
    if not isinstance(message, dict) or message.get("role") != kind:
        return _bad("field")
    model = None
    if kind == "user":
        found = _user_text(line, message.get("content"))
        if isinstance(found, ClaudeLine):
            return found
        author, text = found
    else:
        model = message.get("model")
        if model == SYNTHETIC:
            return _skipped("synthetic")
        text = _assistant_text(message.get("content"))
        if isinstance(text, ClaudeLine):
            return text
        author = AUTHORS["assistant"]
    if at < not_before:
        return _skipped("old")
    try:
        parsed = masking.make_message(external_id=line_id, role=kind, author=author, at=at,
                                      text=text, model=model)
    except ValueError:
        return _bad("field")
    if parsed is None:
        return _skipped("empty")
    return ClaudeLine(
        "message", message=parsed,
        workspace=masking.mask_field(line.get("cwd"), masking.WORKSPACE_MAX),
        git_branch=masking.mask_field(line.get("gitBranch"), masking.BRANCH_MAX),
        session_id_differs=line.get("sessionId") != stem,
    )
