"""Confinement of the conversation readers (spec §5.1, §5.2; ADR-025 D1, D2).

A whitelist, never a deny list: a root is checked as configured before it is resolved, the walk
goes level by level at a fixed depth (`os.scandir`, never `rglob` nor `os.walk`), each
intermediate directory is checked before it is listed, and only names that match a reader's
pattern entirely are candidates. A candidate is opened read-only and its identity checked again
on the open descriptor. Messages and logs carry fixed codes and counts, never a path, a slug,
a session id or a content.
"""

from __future__ import annotations

import logging
import os
import re
import stat
import sys
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from nexus.adapters.run_commit_scan import is_link

log = logging.getLogger("nexus.conversations")

# source -> (expected name of the root, the root is a directory)
ROOTS = {
    "claude-code": ("projects", True),
    "codex": ("sessions", True),
    "hermes": ("state.db", False),
}
MESSAGES = {
    "root_not_absolute": "racine de conversations refusée : un chemin absolu est attendu",
    "root_missing": "racine de conversations refusée : introuvable",
    "root_unreadable": "racine de conversations refusée : illisible",
    "root_wrong_kind": "racine de conversations refusée : type de fichier inattendu",
    "root_is_link": "racine de conversations refusée : lien ou point de jonction",
    "root_hard_linked": "racine de conversations refusée : lien physique",
    "root_badly_named": (
        "racine de conversations refusée : le dossier doit s'appeler projects (Claude Code) "
        "ou sessions (Codex), la base Hermes state.db"
    ),
    "root_substituted": "racine de conversations refusée : remplacée pendant son contrôle",
    "substituted": "fichier de conversation refusé : remplacé entre son contrôle et sa lecture",
}


class SourceRefused(Exception):
    """A refusal with a fixed code and a fixed French message (never the path, ADR-006)."""

    def __init__(self, code: str) -> None:
        super().__init__(MESSAGES[code])
        self.code = code


@dataclass(frozen=True)
class Root:
    source: str
    path: Path  # resolved
    ident: tuple[int, int]  # (st_dev, st_ino) of the root as configured


def _ident(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def check_root(configured: Path, source: str) -> Root:
    """The root of `source`, resolved, or `SourceRefused`.

    Order matters: the link check runs on the configured path, before any resolution (a
    resolved path loses the reparse attribute, so the reverse order would never see a
    junction). Only `is_absolute()` and `os.lstat` touch the configured path before that.
    """
    name, is_dir = ROOTS[source]
    if not configured.is_absolute():
        raise SourceRefused("root_not_absolute")
    info = _lstat_root(configured)
    if is_link(info):
        raise SourceRefused("root_is_link")
    if not (stat.S_ISDIR(info.st_mode) if is_dir else stat.S_ISREG(info.st_mode)):
        raise SourceRefused("root_wrong_kind")
    if not is_dir and info.st_nlink != 1:
        raise SourceRefused("root_hard_linked")
    if configured.name != name:  # exact case: `Projects` or `PROJEC~1` fail closed
        raise SourceRefused("root_badly_named")
    try:
        resolved = configured.resolve(strict=True)
        final = os.lstat(resolved)
    except OSError:
        raise SourceRefused("root_missing") from None
    if resolved.name != name:
        raise SourceRefused("root_badly_named")
    # Closes the window between the link check and `resolve`: a root swapped for a junction
    # in between resolves elsewhere, with another identity. A junction *above* the root keeps
    # the identity of the root itself, and is admitted (spec §5.1, R1).
    if _ident(final) != _ident(info):
        raise SourceRefused("root_substituted")
    return Root(source, resolved, _ident(info))


def _lstat_root(path: Path) -> os.stat_result:
    try:
        return os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        raise SourceRefused("root_missing") from None
    except OSError:
        raise SourceRefused("root_unreadable") from None


# Whole-name patterns (`fullmatch`), level by level (spec §5.1 rule 3). ASCII digits only.
_CLAUDE_LEVELS = (re.compile(r"[A-Za-z0-9._-]{1,200}"),)
_CLAUDE_FILE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl")
_CODEX_LEVELS = (re.compile(r"[0-9]{4}"), re.compile(r"[0-9]{2}"), re.compile(r"[0-9]{2}"))
# Compressed rollouts only (C7): a `.jsonl` in clear waits for a survey and its own PR.
_CODEX_FILE = re.compile(r"rollout-[0-9T:-]{10,40}-[0-9a-f-]{36}\.jsonl\.zst")

if sys.platform == "win32":
    OPEN_FLAGS = os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT
else:
    OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC


@dataclass(frozen=True)
class Candidate:
    path_key: str  # relative to the root, with `/` on every platform
    path: Path
    ident: tuple[int, int]  # (st_dev, st_ino) from os.lstat, never DirEntry.stat()
    size: int
    mtime_ns: int

    @property
    def file_id(self) -> str:
        return f"{self.ident[0]}:{self.ident[1]}"


@dataclass
class Listing:
    source: str
    candidates: list[Candidate] = field(default_factory=list)
    skipped: int = 0  # names outside the patterns, and refused files
    skipped_dirs: int = 0  # admitted names of folders refused before their listing
    codes: Counter = field(default_factory=Counter)


def iter_claude(root: Root) -> Listing:
    """`<slug>/<uuid>.jsonl` under `projects`, nothing deeper (subagents, tool results)."""
    return _walk(root, _CLAUDE_LEVELS, _CLAUDE_FILE)


def iter_codex(root: Root) -> Listing:
    """`AAAA/MM/JJ/rollout-….jsonl.zst` under `sessions`; never the parent folder."""
    return _walk(root, _CODEX_LEVELS, _CODEX_FILE)


def _walk(root: Root, levels: tuple[re.Pattern, ...], file_pattern: re.Pattern) -> Listing:
    listing = Listing(root.source)
    frontier = [("", root.path)]
    for depth, pattern in enumerate(levels):
        admitted = []
        for prefix, folder in frontier:
            for name in _names(folder, listing, is_root=depth == 0):
                if not pattern.fullmatch(name):
                    listing.skipped += 1
                    continue
                path = folder / name
                code = _check_level_dir(path, root)
                if code is None:
                    admitted.append((f"{prefix}{name}/", path))
                elif code == "not_a_dir":
                    listing.skipped += 1
                else:
                    listing.skipped_dirs += 1
                    listing.codes[code] += 1
        frontier = admitted
    for prefix, folder in frontier:
        for name in _names(folder, listing, is_root=not levels):
            if not file_pattern.fullmatch(name):
                listing.skipped += 1
                continue
            found = _check_candidate(folder / name, f"{prefix}{name}", root)
            if isinstance(found, Candidate):
                listing.candidates.append(found)
            else:
                listing.skipped += 1
                listing.codes[found] += 1
    log.info(
        "conversations %s : %d fichiers retenus, %d écartés, %d dossiers écartés (%s)",
        root.source, len(listing.candidates), listing.skipped, listing.skipped_dirs,
        ", ".join(f"{code}={n}" for code, n in sorted(listing.codes.items())) or "aucun code",
    )
    return listing


def _names(folder: Path, listing: Listing, *, is_root: bool) -> list[str]:
    """The entry names of one folder; only the name of a DirEntry is ever used."""
    try:
        with os.scandir(folder) as entries:
            return sorted(entry.name for entry in entries)
    except OSError:
        if is_root:
            raise SourceRefused("root_unreadable") from None
        listing.skipped_dirs += 1
        listing.codes["level_dir_unreadable"] += 1
        return []


def _check_level_dir(path: Path, root: Root) -> str | None:
    """None for a real folder under the root, else a fixed code; runs before it is listed.

    `DirEntry.is_dir(follow_symlinks=False)` is true for a junction on Windows: `os.lstat` and
    the reparse attribute are what tell it.
    """
    try:
        info = os.lstat(path)
    except OSError:
        return "level_dir_unreadable"
    if is_link(info):
        return "level_dir_is_link"
    if not stat.S_ISDIR(info.st_mode):
        return "not_a_dir"
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return "level_dir_unreadable"
    if not resolved.is_relative_to(root.path):
        return "level_dir_outside"
    return None


def _check_candidate(path: Path, path_key: str, root: Root) -> Candidate | str:
    try:
        info = os.lstat(path)  # DirEntry.stat() gives 0 for st_ino and st_nlink on Windows
    except OSError:
        return "file_unreadable"
    if is_link(info):
        return "file_is_link"
    if not stat.S_ISREG(info.st_mode):
        return "not_a_file"
    if info.st_nlink != 1:
        return "file_hard_linked"
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return "file_unreadable"
    if not resolved.is_relative_to(root.path):
        return "file_outside"
    return Candidate(path_key, path, _ident(info), info.st_size, info.st_mtime_ns)


def open_candidate(candidate: Candidate) -> int:
    """A read-only descriptor on the candidate, whose identity matches its `lstat`.

    The caller closes it, before any write transaction (spec §5.1 rule 5): use `opened`.
    """
    fd = os.open(candidate.path, OPEN_FLAGS)
    try:
        if _ident(os.fstat(fd)) != candidate.ident:
            raise SourceRefused("substituted")
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextmanager
def opened(candidate: Candidate) -> Iterator[int]:
    fd = open_candidate(candidate)
    try:
        yield fd
    finally:
        os.close(fd)
