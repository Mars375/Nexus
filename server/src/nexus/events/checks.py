"""Pure checks of an event envelope: task reference, text fields and lengths (no session)."""

from __future__ import annotations

import re
from typing import Any

from nexus.events.limits import EVENT_ID_MAX, EVIDENCE_REF_MAX, RUN_MAX, SUBJECT_MAX
from nexus.events.rules import Envelope
from nexus.tasks.rules import RuleViolation
from nexus.validation import API_STRIP


def parse_task_ref(ref: str) -> int:
    raw = ref.removeprefix("nx-task-")
    if not re.fullmatch(r"[0-9]{1,12}", raw):
        # La valeur reçue n'est jamais recopiée (elle pourrait être un secret).
        raise RuleViolation("unknown_task", "référence de tâche invalide")
    return int(raw)


def _text_list(value: Any, name: str) -> list[str]:
    # An adapter may pass a tuple: normalise to the list the database will re-read, otherwise the
    # fingerprint (read-back, anti-noise) compares a tuple to a list.
    if not isinstance(value, list | tuple) or not all(isinstance(v, str) for v in value):
        raise RuleViolation(f"invalid_{name}", f"{name} doit être une liste de textes")
    return list(value)


# (field, violation code, message): required text, then optional text. The received value is never
# echoed in the message (it could be a secret).
_REQUIRED_TEXT = (
    ("actor", "invalid_actor", "actor doit être un texte"),
    ("kind", "invalid_kind", "kind doit être un texte"),
    ("subject", "invalid_subject", "subject doit être un texte"),
)
_OPTIONAL_TEXT = (
    ("task", "invalid_task", "task doit être un texte ou absente"),
    ("run", "invalid_run", "run doit être un texte ou absent"),
    ("body", "invalid_body", "body doit être un texte ou absent"),
)


def _check_scalars(envelope: Envelope, actor_event_id: object) -> None:
    """Refuse a wrong scalar type from a direct call (the API's Pydantic models guarantee them).

    Only the type is checked: empty or unknown values keep the behaviour of `rules.validate`.
    """
    for name, code, message in _REQUIRED_TEXT:
        if not isinstance(getattr(envelope, name), str):
            raise RuleViolation(code, message)
    for name, code, message in _OPTIONAL_TEXT:
        value = getattr(envelope, name)
        if value is not None and not isinstance(value, str):
            raise RuleViolation(code, message)
    if not isinstance(actor_event_id, str):
        raise RuleViolation("invalid_event_id", "id doit être un texte")


def _check_lengths(envelope: Envelope, actor_event_id: str) -> None:
    """Refuse a value longer than the API accepts (same constants, same measure).

    Run after the type checks, before redaction: the API measures the raw received length (the
    evidence items after stripping, as `Ref` does). The value is never echoed.
    """
    if len(actor_event_id) > EVENT_ID_MAX:
        raise RuleViolation("too_long_id", f"id : {EVENT_ID_MAX} caractères au plus")
    if envelope.run is not None and len(envelope.run) > RUN_MAX:
        raise RuleViolation("too_long_run", f"run : {RUN_MAX} caractères au plus")
    if len(envelope.subject) > SUBJECT_MAX:
        raise RuleViolation("too_long_subject", f"subject : {SUBJECT_MAX} caractères au plus")
    if any(len(API_STRIP.validate_python(item)) > EVIDENCE_REF_MAX for item in envelope.evidence):
        raise RuleViolation(
            "too_long_evidence", f"evidence : {EVIDENCE_REF_MAX} caractères au plus par élément"
        )
