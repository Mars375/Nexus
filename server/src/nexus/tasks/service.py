"""Opérations sur les tâches : applique les règles et journalise chaque mutation."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus import permissions, secrets
from nexus.clock import now
from nexus.events.limits import EVIDENCE_REF_MAX
from nexus.models import Task, TaskComment, TaskDependency, TaskHistory
from nexus.tasks import rules
from nexus.tasks.rules import RuleViolation
from nexus.validation import API_STRIP, has_unencodable

log = logging.getLogger("nexus.tasks")


class TaskNotFound(Exception):
    def __init__(self, ref: str) -> None:
        super().__init__(f"tâche introuvable : {ref}")
        self.ref = ref


UPDATABLE = frozenset({
    "title", "objective", "human_owner", "lead_agent", "collaborators", "next_action",
    "due_at", "follow_up_at", "expected_evidence", "priority", "operation_role", "origin",
    "context", "follows",
})


# Le rôle main/auxiliary se prépare avant le démarrage ou vaut pendant l'exécution.
ROLE_STATUSES = frozenset({"backlog", "todo", "in_progress"})


def _drop_blank_expectation(values: dict[str, Any]) -> dict[str, Any]:
    """Une preuve attendue réduite à un secret masqué n'exprime aucune attente : on l'efface."""
    if "expected_evidence" in values and secrets.is_blank(values["expected_evidence"]):
        values = values | {"expected_evidence": None}
    return values


_FOLLOWS = re.compile(r"nx-task-[0-9]{1,12}")


def parse_follows(value: Any) -> int | None:
    """The task id behind a `follows` reference, or None for no link.

    ASCII digits only, read as a number once: `nx-task-0007` is task 7, and everything after
    (comparison, lookup, history) works on that integer, never on the received text.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not _FOLLOWS.fullmatch(value):
        raise RuleViolation("invalid_follows", "follows : référence de tâche invalide")
    return int(value.removeprefix("nx-task-"))


def _follows_ref(task_id: int | None) -> str | None:
    return None if task_id is None else f"nx-task-{task_id}"


def _follows_target(session: Session, task_id: int) -> Task:
    """The task a follow-up links to: it must exist (404) and be done (409)."""
    target = get_task(session, task_id)
    if target.status != "done":
        raise RuleViolation(
            "follows_not_done",
            f"follows : {target.ref} n'est pas terminée ; une tâche de suite ne suit qu'une "
            "tâche terminée",
        )
    return target


def get_task(session: Session, task_id: int) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise TaskNotFound(f"nx-task-{task_id}")
    return task


def list_tasks(
    session: Session,
    *,
    statuses: list[str] | None = None,
    agent: str | None = None,
    owner: str | None = None,
    priority: str | None = None,
    role: str | None = None,
    due_before: datetime | None = None,
) -> list[Task]:
    query = select(Task).order_by(Task.updated_at.desc(), Task.id.desc())
    if statuses:
        query = query.where(Task.status.in_(statuses))
    if owner:
        query = query.where(Task.human_owner == owner)
    if priority:
        query = query.where(Task.priority == priority)
    if role:
        query = query.where(Task.operation_role == role)
    tasks = list(session.scalars(query))
    if agent:
        tasks = [t for t in tasks if t.lead_agent == agent or agent in t.collaborators]
    if due_before:
        tasks = [t for t in tasks if t.due_at is not None and t.due_at < due_before]
    return tasks


def create_task(session: Session, data: dict[str, Any], actor: str) -> Task:
    permissions.check_create(
        actor, lead_agent=data.get("lead_agent"), collaborators=data.get("collaborators") or []
    )
    redacted: dict[str, list[str]] = {}
    data = dict(data)
    raw_follows = data.pop("follows", None)  # not a column of Task
    data = _drop_blank_expectation(secrets.redact_fields(data, redacted.__setitem__))
    status = data.pop("status", "backlog")
    if status not in rules.INITIAL_STATUSES:
        raise RuleViolation(
            "initial_status", "une tâche se crée en backlog ou en todo, puis avance"
        )
    rules.check_identity(data.get("title"), data.get("objective"))
    rules.check_next_action(status, data.get("next_action"))
    follows_id = parse_follows(raw_follows)
    if follows_id is not None:
        _follows_target(session, follows_id)
    ts = now()
    task = Task(
        **data,
        follows_id=follows_id,
        status=status,
        evidence=[],
        created_by=actor,
        created_at=ts,
        updated_at=ts,
    )
    session.add(task)
    session.flush()
    _record(session, task, actor, "created", {
        k: [None, v] for k, v in data.items() if v not in (None, [], "")
    } | {"status": [None, status]} | (
        {"follows": [None, _follows_ref(follows_id)]} if follows_id is not None else {}
    ))
    _record_redactions(session, task, actor, redacted)
    return task


def update_task(session: Session, task: Task, changes: dict[str, Any], actor: str) -> Task:
    unknown = set(changes) - UPDATABLE
    if unknown:
        raise RuleViolation("not_updatable", f"champs non modifiables ici : {sorted(unknown)}")
    permissions.check_update(
        actor,
        lead_before=task.lead_agent,
        lead_after=changes.get("lead_agent", task.lead_agent),
        collaborators_before=task.collaborators,
        collaborators_after=changes.get("collaborators", task.collaborators),
    )
    redacted: dict[str, list[str]] = {}
    changes = dict(changes)
    has_follows = "follows" in changes
    raw_follows = changes.pop("follows", None)  # not an attribute of Task
    changes = _drop_blank_expectation(secrets.redact_fields(changes, redacted.__setitem__))
    role_before = task.operation_role
    # The diff is computed before anything is written: a refusal then leaves the task untouched.
    diff = {field: [getattr(task, field), value] for field, value in changes.items()
            if getattr(task, field) != value}
    follows_id = parse_follows(raw_follows) if has_follows else None
    if has_follows and follows_id != task.follows_id:
        diff["follows"] = [_follows_ref(task.follows_id), _follows_ref(follows_id)]
    # Tracé même si rien ne change : un secret recollé dans un champ déjà masqué reste une
    # exposition à signaler.
    _record_redactions(session, task, actor, redacted)
    if not diff:
        return task
    rules.check_not_done(task.status)  # before looking up a follows target: state first
    if "follows" in diff and follows_id is not None:
        _follows_target(session, follows_id)
    for field in changes:
        if field in diff:
            setattr(task, field, changes[field])
    if "follows" in diff:
        task.follows_id = follows_id
    rules.check_identity(task.title, task.objective)
    rules.check_next_action(task.status, task.next_action)
    if task.status == "blocked":
        rules.check_block(task.block_cause, task.block_plan, task.follow_up_at)
    if "operation_role" in diff and task.operation_role and task.status not in ROLE_STATUSES:
        raise RuleViolation(
            "role_not_applicable",
            "le rôle se prépare sur une tâche à venir ou en cours, pas sur une tâche "
            f"{task.status}",
        )
    if task.status == "in_progress" and ({"operation_role", "human_owner"} & diff.keys()):
        task.operation_role = rules.resolve_role(
            task.operation_role, _other_main_in_progress(session, task)
        )
        # L'historique dit ce qui est réellement enregistré, pas ce qui a été demandé.
        diff.pop("operation_role", None)
        if task.operation_role != role_before:
            diff["operation_role"] = [role_before, task.operation_role]
        if not diff:
            return task
    task.updated_at = now()
    _record(session, task, actor, "updated", diff)
    return task


def change_status(
    session: Session,
    task: Task,
    target: str,
    actor: str,
    *,
    reason: str | None = None,
    block_cause: str | None = None,
    block_plan: str | None = None,
    follow_up_at: datetime | None = None,
    evidence: list[str] | None = None,
    next_action: str | None = None,
    role: str | None = None,
) -> Task:
    permissions.check_status(actor, target)
    if evidence is not None:
        # Same checks as attach_evidence and publish(): a direct caller gets no silent drop.
        # Judged on the raw items, before masking (an item reduced to a secret is filtered later).
        _checked_evidence(evidence)
    redacted: dict[str, list[str]] = {}
    texts = secrets.redact_fields(
        {"reason": reason, "block_cause": block_cause, "block_plan": block_plan,
         "evidence": evidence, "next_action": next_action},
        redacted.__setitem__,
    )
    reason, block_cause, block_plan = texts["reason"], texts["block_cause"], texts["block_plan"]
    evidence, next_action = texts["evidence"], texts["next_action"]

    current = task.status
    rules.check_transition(current, target)
    rules.check_dependencies(target, _pending_dependencies(session, task))
    if current in rules.DEPENDENCY_RESOLVED and target not in rules.DEPENDENCY_RESOLVED:
        # Only dropped -> backlog gets here (done is final): taking back a prerequisite would
        # leave its advanced dependents without a resolved prerequisite.
        advanced = _advanced_dependents(session, task)
        if advanced:
            raise RuleViolation(
                "reopen_with_advanced_dependents",
                f"{task.ref} ne peut pas être rouverte : {', '.join(advanced)} en dépend "
                "et a déjà avancé",
            )
    watched = (
        "next_action", "block_cause", "block_plan", "follow_up_at", "drop_reason",
        "evidence", "operation_role",
    )
    before = {f: getattr(task, f) for f in watched}

    if next_action is not None:
        task.next_action = next_action

    if target == "blocked":
        follow_up = follow_up_at or task.follow_up_at
        rules.check_block(block_cause, block_plan, follow_up)
        task.block_cause, task.block_plan, task.follow_up_at = block_cause, block_plan, follow_up
    elif current == "blocked":
        task.block_cause = task.block_plan = None

    if target == "dropped":
        rules.check_drop(reason)
        task.drop_reason = reason
    elif current == "dropped":
        task.drop_reason = None

    final = target
    if target in ("done", "review"):
        # Une preuve vide ou réduite à un secret masqué ne prouve rien ; une preuve dont il
        # reste une référence lisible (« commit:abc token=[REDACTED] ») compte. Même règle
        # que les événements (secrets.is_blank_reference : il doit rester un identifiant).
        # Jointe à une mise en review, elle reste sur la tâche : Loïc peut ensuite la clore.
        refs = [e for e in (API_STRIP.validate_python(i) for i in evidence or [])
                if not secrets.is_blank_reference(e)]
        if refs:
            task.evidence = list(dict.fromkeys([*task.evidence, *refs]))
    if target == "done":
        final = rules.resolve_done(task.expected_evidence, task.evidence)
        if final == current:  # déjà en review, toujours sans preuve
            raise RuleViolation(
                "evidence_required", "cette tâche attend une preuve : fournis-la pour la clore"
            )

    if final == "in_progress":
        task.operation_role = rules.resolve_role(
            role or task.operation_role, _other_main_in_progress(session, task)
        )
    elif current == "in_progress":
        # Le rôle n'a de sens qu'en cours : à la reprise, il sera redemandé ou redéduit.
        task.operation_role = None

    rules.check_next_action(final, task.next_action)
    task.status = final
    task.updated_at = now()

    changes: dict[str, Any] = {"status": [current, final]}
    changes |= {f: [before[f], getattr(task, f)] for f in watched if before[f] != getattr(task, f)}
    if final != target:
        changes["note"] = "preuve attendue manquante : clôture passée en review"
    if reason and target != "dropped":
        changes["reason"] = reason
    _record(session, task, actor, "status", changes)
    _record_redactions(session, task, actor, redacted)
    return task


def add_comment(session: Session, task: Task, actor: str, body: str) -> TaskComment:
    if not body.strip():
        raise RuleViolation("empty_comment", "un commentaire ne peut pas être vide")
    body, kinds = secrets.redact(body)
    comment = TaskComment(task_id=task.id, author=actor, body=body, at=now())
    session.add(comment)
    session.flush()
    task.updated_at = comment.at
    _record(session, task, actor, "commented", {"comment_id": comment.id})
    _record_redactions(session, task, actor, {"comment": kinds} if kinds else {})
    return comment


def comments_of(session: Session, task: Task) -> list[TaskComment]:
    return list(session.scalars(
        select(TaskComment).where(TaskComment.task_id == task.id).order_by(TaskComment.id)
    ))


def history_of(session: Session, task: Task) -> list[TaskHistory]:
    return list(session.scalars(
        select(TaskHistory).where(TaskHistory.task_id == task.id).order_by(TaskHistory.id)
    ))


def dependencies_of(session: Session, task: Task) -> list[int]:
    return list(session.scalars(
        select(TaskDependency.depends_on_id)
        .where(TaskDependency.task_id == task.id)
        .order_by(TaskDependency.depends_on_id)
    ))


def add_dependency(session: Session, task: Task, other: Task, actor: str) -> None:
    if task.id == other.id:
        raise RuleViolation("self_dependency", "une tâche ne peut pas dépendre d'elle-même")
    if session.get(TaskDependency, (task.id, other.id)) is not None:
        return
    rules.check_not_done(task.status)
    if _depends_on(session, other.id, task.id):
        raise RuleViolation(
            "dependency_cycle", f"{other.ref} dépend déjà de {task.ref} : cycle refusé"
        )
    # Le contrôle des dépendances ne joue qu'aux transitions : une tâche déjà avancée ne
    # peut pas dépendre après coup d'une tâche non traitée.
    if task.status in rules.GATED_BY_DEPENDENCIES and other.status not in rules.DEPENDENCY_RESOLVED:
        raise RuleViolation(
            "dependency_on_advanced_task",
            f"{task.ref} est déjà {task.status} : elle ne peut pas dépendre de {other.ref}, "
            "qui n'est pas traitée",
        )
    session.add(TaskDependency(task_id=task.id, depends_on_id=other.id))
    task.updated_at = now()
    _record(session, task, actor, "linked", {"depends_on": [None, other.ref]})


def _checked_evidence(evidence: list[str]) -> list[str]:
    """Checks evidence from a direct caller as the API does and returns the stripped items.

    Texts only, encodable, stripped as Pydantic strips, none blank. The API refuses a blank
    item (422) and publish() answers invalid_evidence: a direct caller gets no silent drop.
    """
    if not isinstance(evidence, list | tuple) or not all(isinstance(e, str) for e in evidence):
        raise RuleViolation("invalid_evidence", "evidence : liste de textes attendue")
    if has_unencodable(list(evidence)):
        raise RuleViolation(
            "invalid_value", "valeur non encodable : demi-paire UTF-16, NaN ou Infinity"
        )
    stripped = [API_STRIP.validate_python(e) for e in evidence]
    if not all(stripped):
        raise RuleViolation("invalid_evidence", "evidence : éléments non vides requis")
    return stripped


def attach_evidence(session: Session, task: Task, evidence: list[str], actor: str) -> None:
    """Appends evidence to a task of any status, without changing its status (ADR-022).

    Safe for a direct caller: the same checks as the API (texts only, encodable, stripped as
    Pydantic strips, measured after stripping), then secrets are masked and traced.
    """
    stripped = _checked_evidence(evidence)
    if any(len(e) > EVIDENCE_REF_MAX for e in stripped):
        raise RuleViolation(
            "too_long_evidence",
            f"evidence : {EVIDENCE_REF_MAX} caractères au plus par élément",
        )
    redacted: dict[str, list[str]] = {}
    clean = secrets.redact_fields({"evidence": stripped}, redacted.__setitem__)["evidence"]
    # The alert fires as soon as a secret is seen, even if a refusal follows (as update_task
    # does). The `secret_redacted` history line is written only on success: a refusal rolls
    # the transaction back, so a line written before it would vanish anyway.
    _alert_redactions(task, redacted)
    refs = [e for e in clean if not secrets.is_blank_reference(e)]
    merged = list(dict.fromkeys([*task.evidence, *refs]))
    if not refs:
        raise RuleViolation("evidence_required", "evidence : aucune preuve lisible")
    if merged == task.evidence:
        raise RuleViolation("evidence_unchanged", "evidence : déjà jointe à la tâche")
    before, task.evidence = task.evidence, merged
    task.updated_at = now()
    _record(session, task, actor, "updated", {"evidence": [before, merged]})
    _record_redactions(session, task, actor, redacted, alert=False)


def remove_dependency(session: Session, task: Task, other: Task, actor: str) -> None:
    link = session.get(TaskDependency, (task.id, other.id))
    if link is None:
        raise TaskNotFound(f"dépendance {task.ref} → {other.ref}")
    rules.check_not_done(task.status)
    session.delete(link)
    task.updated_at = now()
    _record(session, task, actor, "unlinked", {"depends_on": [other.ref, None]})


def _advanced_dependents(session: Session, task: Task) -> list[str]:
    rows = session.execute(
        select(Task.id, Task.status)
        .join(TaskDependency, TaskDependency.task_id == Task.id)
        .where(TaskDependency.depends_on_id == task.id)
        .order_by(Task.id)
    )
    return [
        f"nx-task-{dep_id} ({status})"
        for dep_id, status in rows
        if status in rules.GATED_BY_DEPENDENCIES
    ]


def _pending_dependencies(session: Session, task: Task) -> list[str]:
    rows = session.execute(
        select(Task.id, Task.status)
        .join(TaskDependency, TaskDependency.depends_on_id == Task.id)
        .where(TaskDependency.task_id == task.id)
        .order_by(Task.id)
    )
    return [
        f"nx-task-{dep_id} ({status})"
        for dep_id, status in rows
        if status not in rules.DEPENDENCY_RESOLVED
    ]


def _depends_on(session: Session, start: int, target: int) -> bool:
    """`start` dépend-elle, directement ou non, de `target` ?"""
    seen, stack = set(), [start]
    while stack:
        current = stack.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(session.scalars(
            select(TaskDependency.depends_on_id).where(TaskDependency.task_id == current)
        ))
    return False


def _other_main_in_progress(session: Session, task: Task) -> bool:
    query = select(Task.id).where(
        Task.human_owner == task.human_owner,
        Task.status == "in_progress",
        Task.operation_role == "main",
        Task.id != task.id,
    )
    # Pas d'écriture anticipée des changements en cours : la règle doit répondre avant l'index.
    with session.no_autoflush:
        return session.scalar(query) is not None


def _record(session: Session, task: Task, actor: str, action: str, changes: dict) -> None:
    session.add(TaskHistory(
        task_id=task.id, actor=actor, at=now(), action=action, changes=_jsonable(changes)
    ))


def _alert_redactions(task: Task, redacted: dict[str, list[str]]) -> None:
    """Log (never the value) that a secret was masked."""
    if redacted:
        kinds = sorted({k for ks in redacted.values() for k in ks})
        log.warning(
            "secret masqué sur %s (champs %s, types %s)", task.ref, sorted(redacted), kinds
        )


def _record_redactions(
    session: Session, task: Task, actor: str, redacted: dict[str, list[str]], *, alert: bool = True
) -> None:
    """Trace (sans la valeur) qu'un secret a été masqué, et alerte dans les logs."""
    if not redacted:
        return
    if alert:
        _alert_redactions(task, redacted)
    kinds = sorted({k for ks in redacted.values() for k in ks})
    _record(session, task, actor, "secret_redacted", {"fields": sorted(redacted), "kinds": kinds})


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value
