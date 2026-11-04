"""Pure checks of task input: blank expectations, `follows` references and evidence refs."""

from __future__ import annotations

import re
from typing import Any

from nexus import secrets
from nexus.tasks.rules import RuleViolation
from nexus.validation import API_STRIP, has_unencodable


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


def _checked_evidence(evidence: object) -> list[str]:
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
