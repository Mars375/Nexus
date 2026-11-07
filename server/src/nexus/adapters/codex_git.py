"""Git side of the Codex adapter: one worktree and one branch per run, and the proof (D6).

Nexus never pushes or merges. Every call is bounded by a timeout.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

GIT_TIMEOUT = 60.0


def clean_env() -> dict[str, str]:
    """The environment without `GIT_*`: inside a git hook, `GIT_DIR` and `GIT_INDEX_FILE` would
    point every command at the repository being committed instead of the one asked for."""
    return {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=GIT_TIMEOUT,
        check=False, env=clean_env(),
    )


def toplevel(path: Path) -> Path | None:
    done = git(path, "rev-parse", "--show-toplevel")
    return Path(done.stdout.strip()).resolve() if done.returncode == 0 else None


def server_repo() -> Path | None:
    """The repository Nexus itself runs from: never a place to hand work to an agent."""
    return toplevel(Path(__file__).resolve().parent)


def choose_repo(workdirs: Sequence[Path], requested: str | None) -> Path:
    """The configured repository the run works in; ValueError otherwise (nothing echoed)."""
    configured = {p.resolve(): p.resolve() for p in workdirs}
    if requested:
        repo = Path(requested).resolve()
        if repo not in configured:
            raise ValueError("dossier de travail : absent de NEXUS_RUN_WORKDIRS")
    elif len(configured) == 1:
        repo = next(iter(configured))
    else:
        raise ValueError("dossier de travail : à préciser (plusieurs dépôts configurés)")
    top = toplevel(repo)
    if top is None or top != repo:
        raise ValueError("dossier de travail : ce n'est pas la racine d'un dépôt git")
    if top == server_repo():
        raise ValueError("dossier de travail : le dépôt du serveur n'est jamais confié")
    return repo


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    start: str  # the commit the branch started from


def create_worktree(repo: Path, base: Path, run_ref: str) -> Worktree:
    branch = f"nexus/{run_ref}"
    path = base / run_ref
    start = git(repo, "rev-parse", "HEAD")
    if start.returncode != 0:
        raise ValueError("dépôt sans commit : rien à partir de quoi travailler")
    path.parent.mkdir(parents=True, exist_ok=True)
    made = git(repo, "worktree", "add", "-b", branch, str(path), start.stdout.strip())
    if made.returncode != 0:
        raise ValueError("création du worktree impossible")
    return Worktree(path, branch, start.stdout.strip())


def proof(tree: Worktree) -> str | None:
    """The commit the run produced, only if it really is one (DONE is not proof, D6).

    It must exist, descend from the start commit, and be after it (`rev-parse` also succeeds
    for the start commit itself).
    """
    head = git(tree.path, "rev-parse", "--verify", "HEAD")
    if head.returncode != 0:
        return None
    produced = head.stdout.strip()
    if git(tree.path, "merge-base", "--is-ancestor", tree.start, produced).returncode != 0:
        return None
    count = git(tree.path, "rev-list", "--count", f"{tree.start}..{produced}")
    if count.returncode != 0 or not count.stdout.strip().isdigit() or int(count.stdout) < 1:
        return None
    return produced
