"""Fake source trees, an audit recorder and link helpers for the confinement tests (ADR-025 D2).

Everything lives under `tmp_path`: no test ever reads Loïc's real `~/.claude` or `~/.codex`.
The content of the fake credential files is invented and built at runtime.
"""

from __future__ import annotations

import os
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest

WINDOWS = sys.platform == "win32"
needs_windows = pytest.mark.skipif(not WINDOWS, reason="jonctions : Windows seulement")


def junction(link: Path, target: Path) -> None:
    """An NTFS junction `link` -> `target` (no admin right needed)."""
    import _winapi

    _winapi.CreateJunction(str(target), str(link))


def symlink_or_skip(link: Path, target: Path, *, directory: bool) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("liens symboliques : droit absent sous Windows (winerror 1314)")
        raise


def fake_secret() -> str:
    return "ghp_" + "A" * 36


def new_uuid() -> str:
    return str(uuid.uuid4())


def write(path: Path, text: str = "{}\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@dataclass
class ClaudeTree:
    home: Path
    root: Path
    slug: str
    sessions: list[str] = field(default_factory=list)  # expected path keys

    def slug_dir(self) -> Path:
        return self.root / self.slug


def fake_claude_home(tmp_path: Path) -> ClaudeTree:
    home = tmp_path / ".claude"
    write(home / ".credentials.json", '{"token": "' + fake_secret() + '"}')
    write(home / "settings.json", '{"model": "inventé"}')
    root = home / "projects"
    slug = "-F-Projet-Exemple"
    tree = ClaudeTree(home, root, slug)
    for _ in range(2):
        name = f"{new_uuid()}.jsonl"
        write(root / slug / name)
        tree.sessions.append(f"{slug}/{name}")
    session = new_uuid()
    write(root / slug / session / "subagents" / f"{new_uuid()}.jsonl")
    (root / slug / session / "tool-results").mkdir()
    write(root / slug / "memory" / "MEMORY.md", "note\n")
    write(root / slug / "notes.txt", "note\n")
    write(root / slug / f"{new_uuid().upper()}.jsonl")
    write(root / slug / f"{new_uuid()}.jsonl.bak")
    (root / slug / f"{new_uuid()}.jsonl").mkdir()
    write(root / "slug avec espace" / f"{new_uuid()}.jsonl")
    write(root / f"{new_uuid()}.jsonl")  # a session name at level 1: never listed
    return tree


@dataclass
class CodexTree:
    home: Path
    root: Path
    rollouts: list[str] = field(default_factory=list)  # expected path keys


def rollout_name(suffix: str = ".jsonl.zst") -> str:
    return f"rollout-2026-11-03T10-22-33-{new_uuid()}{suffix}"


def fake_codex_home(tmp_path: Path) -> CodexTree:
    home = tmp_path / ".codex"
    write(home / "auth.json", '{"OPENAI_API_KEY": "' + fake_secret() + '"}')
    write(home / "config.toml", 'model = "inventé"\n')
    write(home / "history.jsonl")
    root = home / "sessions"
    tree = CodexTree(home, root)
    day = root / "2026" / "11" / "03"
    name = rollout_name()
    write(day / name)
    tree.rollouts.append(f"2026/11/03/{name}")
    write(day / name.removesuffix(".zst"))  # the same rollout in clear: not admitted (C7)
    write(root / "2026" / "11" / rollout_name())  # a rollout at the month level
    write(root / "26" / "11" / "03" / rollout_name())
    write(root / "archive" / "11" / "03" / rollout_name())
    write(day / "sub" / rollout_name())
    write(root / "2026" / "11" / "2026" / rollout_name())  # a year folder under the month
    return tree


class _Recorder:
    """One audit hook for the session (it cannot be removed), active only inside `recording()`."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] | None = None
        sys.addaudithook(self._hook)

    def _hook(self, event: str, args: tuple) -> None:
        if self.events is None or event not in ("open", "os.scandir", "os.listdir"):
            return
        target = args[0] if args else None
        if isinstance(target, int) or target is None:
            return
        try:
            self.events.append((event, os.fsdecode(target)))
        except TypeError:
            return


_recorder: _Recorder | None = None


@contextmanager
def recording():
    """Yields the list of (`open` | `os.scandir` | `os.listdir`, path) seen inside the block."""
    global _recorder
    if _recorder is None:
        _recorder = _Recorder()
    events: list[tuple[str, str]] = []
    _recorder.events = events
    try:
        yield events
    finally:
        _recorder.events = None


def under(events: list[tuple[str, str]], base: Path) -> list[tuple[str, Path]]:
    """The recorded events whose path lies under `base` (Python opens its own files too)."""
    base = Path(os.path.normcase(os.path.abspath(base)))
    found = []
    for event, raw in events:
        path = Path(os.path.normcase(os.path.abspath(raw)))
        if path == base or path.is_relative_to(base):
            found.append((event, path))
    return found


def norm(path: Path) -> Path:
    return Path(os.path.normcase(os.path.abspath(path)))
