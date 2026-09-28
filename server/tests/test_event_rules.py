import pytest

from nexus.events.rules import Envelope, validate
from nexus.tasks.rules import RuleViolation


def env(kind, **kw):
    return Envelope(actor="helios", kind=kind, subject="s", task=kw.pop("task", "nx-task-1"), **kw)


def refused(envelope) -> str:
    with pytest.raises(RuleViolation) as exc:
        validate(envelope)
    return exc.value.code


VALID = [
    env("claimed"),
    env("working", payload={"run_ref": "session:abc"}),
    env("working", run="nx-run-3"),
    env("progress", payload={"percent": 40}),
    env("progress", body="parse OK"),
    env("question", needs=["mnema"], task=None),
    env("needs_human", needs=["loic"], payload={"options": ["publier", "attendre"]}),
    env("handoff", needs=["aether"], payload={"next_action": "poser la clé"}),
    env("blocked", body="SSH timeout", payload={"plan": "rallumer Artémis"}),
    env("blocked", payload={"cause": "SSH", "follow_up_at": "2026-09-29T09:00:00+02:00"}),
    env("review", evidence=["pr:12"]),
    env("done", evidence=["commit:a1b2c3d"]),
    env("failed", body="429 Go"),
    env("unknown", task=None, payload={"last_check_at": "2026-09-28T09:00:00+02:00"}),
]


@pytest.mark.parametrize("envelope", VALID, ids=lambda e: e.kind)
def test_valid_events_keep_their_kind(envelope):
    assert validate(envelope) == envelope.kind


def test_done_without_evidence_becomes_review():
    assert validate(env("done")) == "review"


@pytest.mark.parametrize(
    ("envelope", "code"),
    [
        (env("teleported"), "unknown_kind"),
        (env("claimed", task=None), "task_required"),
        (env("working"), "run_ref_required"),
        (env("progress"), "progress_empty"),
        (env("progress", payload={"percent": 140}), "invalid_percent"),
        (env("question", needs=[]), "recipient_required"),
        (env("question", needs=["mallory"]), "unknown_recipient"),
        (env("needs_human", needs=["mnema"], payload={"options": ["a"]}), "human_required"),
        (env("needs_human", needs=["loic"]), "options_required"),
        (env("handoff", needs=["aether"]), "next_action_required"),
        (env("handoff", needs=["helios"], payload={"next_action": "x"}), "handoff_to_self"),
        (env("blocked", payload={"plan": "p"}), "block_cause_required"),
        (env("blocked", body="SSH"), "block_follow_up_required"),
        (env("blocked", body="SSH", payload={"follow_up_at": "demain"}), "invalid_instant"),
        (env("review"), "evidence_required"),
        (env("failed"), "failure_cause_required"),
        (env("unknown", payload={}), "last_check_required"),
        (env("unknown", payload={"last_check_at": "2026-09-28T09:00:00"}), "invalid_instant"),
    ],
    ids=lambda v: v if isinstance(v, str) else v.kind,
)
def test_refused_events_say_why(envelope, code):
    assert refused(envelope) == code
