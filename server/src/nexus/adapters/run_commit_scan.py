"""Walk of a run's worktree before Nexus commits it (see `run_commit`, step 3).

Written by hand with `os.scandir`: `os.walk` follows NTFS junctions (Python 3.13), which would
let `git add -A` read outside the worktree. This walk never enters a link or a junction, and it
refuses at the first thing git must not be asked to add.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scan:
    files: dict[str, int] = field(default_factory=dict)  # relative "/" path -> size on disk
    refused: str | None = None  # a fixed French motive, or None when the tree is clean


def _refuse(motive: str) -> Scan:
    return Scan(refused=motive)


def is_link(info: os.stat_result) -> bool:
    """A symbolic link, or on Windows any reparse point (junction, link, cloud placeholder)."""
    reparse = getattr(info, "st_file_attributes", 0) & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
    )
    return stat.S_ISLNK(info.st_mode) or bool(reparse)


def _is_dot_git(name: str) -> bool:
    # NTFS ignores the case of a name and trailing dots and spaces: `.GIT` and `.git.` are `.git`
    return name.rstrip(". ").lower() == ".git"


def scan_worktree(root: str | os.PathLike[str]) -> Scan:
    """Every regular file of the worktree, or the first reason Nexus must not commit it."""
    files: dict[str, int] = {}
    pending: list[tuple[str, str]] = [("", os.fspath(root))]
    while pending:
        prefix, folder = pending.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if _is_dot_git(entry.name):
                    # the one `.git` allowed is the file of the worktree itself, at its root
                    if prefix or entry.name != ".git" or is_link(info) or not stat.S_ISREG(
                        info.st_mode
                    ):
                        return _refuse("dépôt git imbriqué")
                    continue
                if is_link(info):
                    return _refuse("lien ou point de jonction")
                if stat.S_ISDIR(info.st_mode):
                    pending.append((f"{prefix}{entry.name}/", entry.path))
                elif stat.S_ISREG(info.st_mode):
                    # the entry's own `st_nlink` is 0 on Windows (directory listing data)
                    if os.lstat(entry.path).st_nlink > 1:
                        return _refuse("lien physique")
                    files[f"{prefix}{entry.name}"] = info.st_size
    return Scan(files)
