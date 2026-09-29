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


@pytest.mark.parametrize("subject", ["   ", "[REDACTED]", "token=[REDACTED]"])
def test_unreadable_subject_is_refused(subject):
    e = Envelope(actor="helios", kind="claimed", subject=subject, task="nx-task-1")
    assert refused(e) == "subject_required"


@pytest.mark.parametrize("percent", [True, False])
def test_boolean_percent_is_refused(percent):
    assert refused(env("progress", payload={"percent": percent})) == "invalid_percent"


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "ghp_" + "S" * 36},
        {"kind": "question", "needs": ["loic", "ghp_" + "S" * 36]},
    ],
)
def test_refusals_never_echo_a_secret_received_by_an_adapter(fields):
    # Un adaptateur peut appeler publish() sans passer par le modèle Pydantic de l'API.
    envelope = Envelope(
        actor="helios", subject="s", task="nx-task-1", **({"kind": "claimed"} | fields)
    )
    with pytest.raises(RuleViolation) as refused:
        validate(envelope)
    assert "S" * 36 not in refused.value.message


def test_unknown_actor_from_an_adapter_is_refused():
    envelope = Envelope(actor="codx", kind="claimed", subject="s", task="nx-task-1")
    with pytest.raises(RuleViolation) as refused:
        validate(envelope)
    assert refused.value.code == "unknown_actor"


@pytest.mark.parametrize(
    "fields", [{"actor": "haxor"}, {"kind": "teleported"}, {"kind": "question", "needs": ["haxor"]}]
)
def test_refusals_name_the_field_without_echoing_the_value(fields):
    envelope = Envelope(
        **({"actor": "helios", "kind": "claimed", "subject": "s", "task": "nx-task-1"} | fields)
    )
    with pytest.raises(RuleViolation) as refused:
        validate(envelope)
    message = refused.value.message
    assert "haxor" not in message and "teleported" not in message
