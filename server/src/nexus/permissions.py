"""Permission matrix (SECURITY §3, ADR-020): who may assign, drop or hand over a task.

Pure functions, no database, like `tasks/rules.py`: the callers pass what they already know.
A refusal is a `Forbidden` (HTTP 403 for a request; for an event effect, the effect is recorded
as not applied). No message ever repeats a received value.
"""

from __future__ import annotations

from collections.abc import Iterable

from nexus.actors import EXECUTORS, HUMANS
from nexus.tasks.rules import RuleViolation


class Forbidden(Exception):
    """A right this actor never has (as opposed to a state-dependent RuleViolation, 409)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _assign_forbidden(field: str, allowed: str) -> Forbidden:
    return Forbidden(
        "assign_forbidden", f"{field} : un exécutant ne peut désigner que {allowed}"
    )


def check_create(actor: str, *, lead_agent: str | None, collaborators: Iterable[str]) -> None:
    """An executor creates tasks for itself or for nobody; others assign freely."""
    if actor not in EXECUTORS:
        return
    if lead_agent not in (None, actor):
        raise _assign_forbidden("lead_agent", "lui-même (ou laisser vide)")
    if any(name != actor for name in collaborators):
        raise _assign_forbidden("collaborators", "lui-même")


def check_update(
    actor: str,
    *,
    lead_before: str | None,
    lead_after: str | None,
    collaborators_before: Iterable[str],
    collaborators_after: Iterable[str],
) -> None:
    """Only what changes is checked; an executor may hand a task back to a human.

    A new lead must be the executor itself, a human, or nobody. Collaborators: those added
    must be the executor itself or a human; removing someone adds nobody.
    """
    if actor not in EXECUTORS:
        return
    if not isinstance(collaborators_after, (list, tuple, set, frozenset)):
        raise RuleViolation(
            "invalid_collaborators", "collaborators : une liste de noms est attendue"
        )
    if lead_after != lead_before and lead_after not in (None, actor) and lead_after not in HUMANS:
        raise _assign_forbidden("lead_agent", "lui-même, un humain ou personne")
    added = set(collaborators_after) - set(collaborators_before)
    if any(name != actor and name not in HUMANS for name in added):
        raise _assign_forbidden("collaborators", "lui-même ou un humain")


def check_status(actor: str, target: str) -> None:
    """Dropping a task is the product's deletion: humans only; an agent asks with needs_human."""
    if target == "dropped" and actor not in HUMANS:
        raise Forbidden(
            "human_only",
            "statut dropped : réservé aux humains ; propose l'abandon avec un événement "
            "needs_human",
        )
