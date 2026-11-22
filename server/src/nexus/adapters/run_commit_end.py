"""The end of a run that Nexus commits, shared by `claude-code` and Codex (spec #186, §7).

`closing` turns an outcome of `run_commit.commit_run` into the closing event's words (data only:
each adapter adds the event itself). `commit_wins` is the rule of a cancel that comes after Nexus
tried its commit: the commit wins, so a cancelled run never has a commit of Nexus on its branch.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from nexus.adapters import run_commit
from nexus.adapters.base import RunAlreadyCommitted

SHORT_SHA = 12


def closing(outcome: run_commit.Outcome, label: str, branch: str) -> tuple[str, str, dict]:
    """(kind, subject, fields of `Job.add`) of the closing event for this outcome."""
    evidence = [f"branch:{branch}"]
    match outcome:
        case run_commit.Committed(sha):
            # Abbreviated: the scanner masks a full 40-hex hash as a secret, and a masked proof
            # proves nothing.
            return "done", f"{label} a terminé ; Nexus a commité", {
                "evidence": [f"commit:{sha[:SHORT_SHA]}"]}
        case run_commit.NothingToCommit():
            return "review", f"{label} a terminé sans changement", {
                "body": "aucun fichier modifié : à relire", "evidence": evidence}
        case run_commit.Refused(motive):
            return "failed", "Commit refusé par Nexus", {
                "payload": {"cause": f"commit refusé par Nexus : {motive}"}, "evidence": evidence}
        case run_commit.GitFailed(step, timed_out):
            what = "délai dépassé" if timed_out else step
            return "failed", "Commit de Nexus impossible", {
                "payload": {"cause": f"commit de Nexus impossible ({what})"}, "evidence": evidence}
    raise TypeError("issue de commit inconnue")


class _Job(Protocol):
    commit_attempted: bool
    outcome: Any
    settled: bool


def commit_wins(job: _Job, settle: Callable[[Any], None]) -> None:
    """At a cancel, once the process tree is stopped. Nothing to do before any commit attempt.
    After one, the run is closed first (`commit_run` finds the same commit again); if Nexus did
    commit, `RunAlreadyCommitted` makes the supervisor publish that end instead of cancelling.
    A close that did not happen raises: the cancel is tried again, never done over a commit."""
    if not job.commit_attempted:
        return
    settle(job)
    if not job.settled:
        raise RuntimeError("fermeture du run non terminée")
    if isinstance(job.outcome, run_commit.Committed):
        raise RunAlreadyCommitted("run déjà commité par Nexus")
