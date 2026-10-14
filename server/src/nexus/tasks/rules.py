"""Règles des tâches Nexus — logique pure, sans base de données.

Statuts et transitions : DATA-MODEL §3. Politiques : PRD §10, ADR-004.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nexus.secrets import is_blank

STATUSES = ("backlog", "todo", "in_progress", "blocked", "review", "done", "dropped")

# Tâche active : doit toujours porter une prochaine action (DATA-MODEL §2.4).
ACTIVE = frozenset({"todo", "in_progress", "blocked", "review"})

TRANSITIONS: dict[str, frozenset[str]] = {
    "backlog": frozenset({"todo", "in_progress", "dropped"}),
    "todo": frozenset({"backlog", "in_progress", "dropped"}),
    "in_progress": frozenset({"todo", "blocked", "review", "done", "dropped"}),
    "blocked": frozenset({"todo", "in_progress", "dropped"}),
    "review": frozenset({"in_progress", "done", "dropped"}),
    "done": frozenset(),  # final (ADR-022): a mistake is fixed in a follow-up task
    "dropped": frozenset({"backlog"}),  # reprise explicite
}

INITIAL_STATUSES = frozenset({"backlog", "todo"})

# Une tâche n'entre dans ces statuts que si toutes ses dépendances sont traitées.
GATED_BY_DEPENDENCIES = frozenset({"in_progress", "review", "done"})
DEPENDENCY_RESOLVED = frozenset({"done", "dropped"})
PRIORITIES = ("low", "normal", "high", "critical")
ROLES = ("main", "auxiliary")


# One message for every mutation refused on a done task. It carries no received value and is not
# one of the « already there » wordings that `demo_agent.landed` reads as a success.
DONE_IS_FINAL = (
    "tâche terminée : elle ne se modifie plus ; commente-la, joins-lui une preuve ou ouvre "
    "une tâche de suite"
)


@dataclass
class RuleViolation(Exception):
    """Une règle produit refuse l'opération. `code` est stable, `message` s'affiche à Loïc."""

    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def check_transition(current: str, target: str) -> None:
    if target not in STATUSES:
        raise RuleViolation("unknown_status", "status : statut inconnu")
    if target == current:
        raise RuleViolation("same_status", f"la tâche est déjà en {target}")
    if current == "done":
        check_not_done(current)
    if target not in TRANSITIONS[current]:
        raise RuleViolation(
            "transition_refused", f"passage de {current} à {target} non autorisé"
        )


def check_not_done(status: str) -> None:
    """A done task is final (ADR-022): only comments and evidence can still be added to it."""
    if status == "done":
        raise RuleViolation("task_done", DONE_IS_FINAL)


def check_identity(title: str | None, objective: str | None) -> None:
    """Titre et objectif disent de quoi il s'agit : un secret masqué n'en tient pas lieu."""
    if is_blank(title):
        raise RuleViolation("title_required", "une tâche doit avoir un titre lisible")
    if is_blank(objective):
        raise RuleViolation("objective_required", "une tâche doit avoir un objectif lisible")


def check_next_action(status: str, next_action: str | None) -> None:
    if status in ACTIVE and is_blank(next_action):
        raise RuleViolation(
            "next_action_required", "une tâche active doit avoir une prochaine action"
        )


def check_block(cause: str | None, plan: str | None, follow_up_at: datetime | None) -> None:
    """Un blocage dit sa cause, et soit sa relance prévue, soit ce qui le débloquerait."""
    if is_blank(cause):
        raise RuleViolation("block_cause_required", "un blocage doit donner sa cause")
    if follow_up_at is None and is_blank(plan):
        raise RuleViolation(
            "block_follow_up_required",
            "un blocage doit prévoir une relance ou dire ce qui le débloquerait",
        )


def check_drop(reason: str | None) -> None:
    if is_blank(reason):
        raise RuleViolation("drop_reason_required", "un abandon doit être motivé")


def check_dependencies(target: str, pending: list[str]) -> None:
    """`pending` : dépendances non traitées, déjà formatées pour l'affichage."""
    if target in GATED_BY_DEPENDENCIES and pending:
        raise RuleViolation(
            "dependencies_pending", f"en attente de : {', '.join(pending)}"
        )


def resolve_done(expected_evidence: str | None, evidence: list[str]) -> str:
    """Preuve ou review : une clôture qui attend une preuve et n'en a pas passe en review.

    Seules les tâches qui déclarent une preuve attendue l'exigent (PRD §10 : « une tâche
    importante se clôt avec preuve »). Les agents, eux, doivent toujours joindre une preuve
    à un événement `done` (EVENT-PROTOCOL §4).
    """
    if expected_evidence and expected_evidence.strip() and not evidence:
        return "review"
    return "done"


def resolve_role(requested: str | None, other_main_in_progress: bool) -> str:
    """Une seule opération principale en cours par humain (ADR-004).

    `requested` : rôle demandé à la transition, sinon celui préparé sur la tâche ; s'il n'y en
    a aucun, la première opération en cours devient principale, les suivantes auxiliaires.
    """
    if requested == "main" and other_main_in_progress:
        raise RuleViolation(
            "main_operation_taken",
            "une autre opération principale est déjà en cours pour cet humain",
        )
    if requested is not None:
        return requested
    return "auxiliary" if other_main_in_progress else "main"
