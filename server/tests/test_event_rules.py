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


# --- #26: consequence and expires_at ----------------------------------------------------------


def test_validate_does_not_require_the_consequence_of_a_needs_human():
    # Required only for a NEW event (require_consequence, after the read-back): old asks replay.
    assert validate(env("needs_human", needs=["loic"], payload={"options": ["a", "b"]})) == (
        "needs_human"
    )


def test_require_consequence():
    from nexus.events.rules import require_consequence

    ok = env("needs_human", needs=["loic"], payload={"consequence": " Publie "})
    require_consequence(ok)
    require_consequence(env("question", needs=["loic"]))  # optional for a question
    for payload in ({}, {"consequence": "  "}, {"consequence": "token=[REDACTED]"}):
        with pytest.raises(RuleViolation) as exc:
            require_consequence(env("needs_human", needs=["loic"], payload=payload))
        assert exc.value.code == "consequence_required"


@pytest.mark.parametrize("kind", ["question", "needs_human"])
@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"consequence": 3}, "invalid_consequence"),
        ({"consequence": "x" * 1001}, "too_long_consequence"),
        ({"expires_at": 3}, "invalid_expires_at"),
        ({"expires_at": "2026-10-25T02:15:00"}, "invalid_expires_at"),
        ({"expires_at": "9999-12-31T23:59:59-05:00"}, "invalid_expires_at"),
    ],
)
def test_new_ask_payload_fields_are_checked(kind, payload, code):
    from datetime import UTC, datetime

    from nexus.events.rules import check_new_ask

    e = env(kind, needs=["loic"], payload={"options": ["a", "b"], "consequence": "c"} | payload)
    raw = e.payload.get("consequence")
    with pytest.raises(RuleViolation) as exc:
        check_new_ask(e, raw, datetime(2026, 10, 7, tzinfo=UTC))
    assert exc.value.code == code


def test_validate_leaves_the_new_only_payload_checks_to_check_new_ask():
    # Old asks must stay replayable: validate() runs before the read-back.
    for payload in ({"consequence": 3}, {"expires_at": "demain"}, {"consequence": "x" * 5000}):
        assert validate(env("question", needs=["loic"], payload=payload)) == "question"


def test_expiry_of_returns_a_utc_instant_or_none():
    from datetime import UTC, datetime

    from nexus.events.rules import expiry_of

    assert expiry_of({}) is None
    assert expiry_of({"expires_at": None}) is None
    got = expiry_of({"expires_at": "2026-10-25T02:15:00+01:00"})
    assert got == datetime(2026, 10, 25, 1, 15, tzinfo=UTC)
    assert got.utcoffset().total_seconds() == 0


def test_expiry_window_bounds_are_inclusive_and_exact():
    from datetime import UTC, datetime, timedelta

    from nexus.events.rules import check_expiry_window

    received = datetime(2026, 10, 7, 10, tzinfo=UTC)
    check_expiry_window(received + timedelta(minutes=1), received)
    check_expiry_window(received + timedelta(days=30), received)
    for delta, code in ((timedelta(minutes=1, microseconds=-1), "expires_at_too_soon"),
                        (timedelta(days=30, microseconds=1), "expires_at_too_far")):
        with pytest.raises(RuleViolation) as exc:
            check_expiry_window(received + delta, received)
        assert exc.value.code == code
