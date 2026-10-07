"""Approvals are opened by `events.service.publish` (#26, PR 1): one per ask addressed to a human.

Covers creation and the payload rules that feed it (`consequence`, `expires_at`), through HTTP and
through direct service calls (an adapter does not go through Pydantic).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from nexus.clock import TZ, now
from nexus.events import service
from nexus.events.limits import CONSEQUENCE_MAX
from nexus.events.rules import Envelope
from nexus.models import Approval, Event
from nexus.tasks.rules import RuleViolation

AT = "2026-09-28T09:05:00+02:00"
AT_DT = datetime.fromisoformat(AT)
FAKE_TOKEN = "ghp_" + "A" * 36  # built at runtime: never a literal secret in the repository


def ask(client, id, kind="question", **fields):
    body = {"id": id, "at": AT, "actor": "helios", "kind": kind, "subject": f"Sujet {id}",
            "needs": ["loic"]} | fields
    if kind == "needs_human":
        body["payload"] = {"options": ["oui", "non"], "consequence": "Publie l'épisode"} | (
            fields.get("payload") or {}
        )
    return client.post("/api/events", json=body)


def rows(client) -> list[Approval]:
    with client.app.state.sessionmaker() as session:
        return list(session.scalars(select(Approval).order_by(Approval.id)))


def code_of(res) -> str:
    assert res.status_code == 409, res.text
    return res.json()["detail"]["code"]


def in_days(days: float) -> str:
    return (now() + timedelta(days=days)).isoformat()


# --- Creation ---------------------------------------------------------------------------------


def test_a_question_for_a_human_opens_an_approval_recorded_in_the_effects(client):
    res = ask(client, "e1")

    assert res.status_code == 201, res.text
    assert res.json()["effects"] == [
        {"action": "approval", "applied": True, "approval": "nx-appr-1"}
    ]
    [approval] = rows(client)
    assert (approval.ref, approval.ask_kind, approval.status) == (
        "nx-appr-1", "question", "pending"
    )
    assert approval.request_event_id == 1
    assert approval.response_event_id is None
    assert approval.expires_at is None


def test_a_needs_human_opens_an_approval_with_its_kind(client):
    res = ask(client, "e1", "needs_human")

    assert res.status_code == 201, res.text
    [approval] = rows(client)
    assert approval.ask_kind == "needs_human"


def test_the_approval_effect_comes_after_the_task_effects_and_works_without_a_task(client):
    task = client.post("/api/tasks", json={"title": "Pont", "objective": "Lire"}).json()["id"]

    res = ask(client, "e1", task=task)

    assert res.json()["effects"] == [
        {"action": "approval", "applied": True, "approval": "nx-appr-1"}
    ]


def test_an_ask_that_needs_no_human_opens_nothing(client):
    res = ask(client, "e1", needs=["mnema"])

    assert res.status_code == 201
    assert res.json()["effects"] == []
    assert rows(client) == []


def test_other_kinds_open_nothing(client):
    task = client.post("/api/tasks", json={"title": "Pont", "objective": "Lire"}).json()["id"]
    res = client.post("/api/events", json={
        "id": "p1", "at": AT, "actor": "helios", "kind": "blocked", "subject": "SSH",
        "body": "timeout", "payload": {"plan": "rallumer"}, "needs": ["loic"], "task": task,
    })

    assert res.status_code == 201, res.text
    assert rows(client) == []


def test_a_duplicated_human_recipient_opens_one_approval(client):
    res = ask(client, "e1", needs=["loic", "loic"])

    assert res.status_code == 201
    assert len(rows(client)) == 1


def test_an_identical_resend_returns_the_same_approval_and_creates_nothing(client):
    first = ask(client, "e1")
    second = ask(client, "e1")

    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["effects"] == first.json()["effects"]
    assert len(rows(client)) == 1


def test_a_resend_with_another_id_is_noise_and_creates_nothing(client):
    ask(client, "e1", subject="Même fait")
    res = ask(client, "e2", subject="Même fait")

    assert code_of(res) == "noise"
    assert len(rows(client)) == 1


def test_a_refused_event_leaves_no_approval(client):
    res = ask(client, "e1", "needs_human", payload={"consequence": " "})

    assert code_of(res) == "consequence_required"
    assert rows(client) == []


def test_two_asks_get_two_numbered_approvals(client):
    ask(client, "e1")
    res = ask(client, "e2")

    assert res.json()["effects"][0]["approval"] == "nx-appr-2"


# --- consequence ------------------------------------------------------------------------------


def test_a_new_needs_human_must_state_its_consequence(client):
    res = client.post("/api/events", json={
        "id": "e1", "at": AT, "actor": "helios", "kind": "needs_human", "subject": "Publier ?",
        "needs": ["loic"], "payload": {"options": ["oui", "non"]},
    })

    assert code_of(res) == "consequence_required"
    assert "consequence" in res.json()["detail"]["message"]


@pytest.mark.parametrize("value", ["", "   ", "[REDACTED]", "token=[REDACTED]"])
def test_a_blank_or_fully_masked_consequence_counts_as_missing(client, value):
    res = ask(client, "e1", "needs_human", payload={"consequence": value})

    assert code_of(res) == "consequence_required"


def test_consequence_is_optional_for_a_question(client):
    assert ask(client, "e1").status_code == 201
    assert ask(client, "e2", payload={"consequence": "Rien de grave"}).status_code == 201


@pytest.mark.parametrize("value", [5, True, ["a"], {"a": 1}])
def test_a_consequence_that_is_not_text_is_refused(client, value):
    res = ask(client, "e1", payload={"consequence": value})

    assert code_of(res) == "invalid_consequence"


def test_a_consequence_over_the_limit_is_refused_without_echo(client):
    long = "x" * (CONSEQUENCE_MAX + 1)
    res = ask(client, "e1", payload={"consequence": long})

    assert code_of(res) == "too_long_consequence"
    assert long not in res.text


def test_a_consequence_at_the_limit_is_accepted(client):
    assert ask(client, "e1", payload={"consequence": "x" * CONSEQUENCE_MAX}).status_code == 201


def test_a_secret_in_the_consequence_is_masked(client):
    res = ask(client, "e1", payload={"consequence": f"Publie avec {FAKE_TOKEN}"})

    assert res.status_code == 201, res.text
    assert FAKE_TOKEN not in res.text
    assert "[REDACTED]" in res.json()["payload"]["consequence"]
    assert res.json()["redacted"]


def direct(client, envelope, id="d1"):
    with client.app.state.sessionmaker() as session:
        event, created = service.publish(session, envelope, id, AT_DT)
        session.commit()
        return event.id, created


def direct_ask(**fields):
    base = {"actor": "helios", "kind": "question", "subject": "Où est la clé ?",
            "needs": ["loic"], "payload": {}}
    return Envelope(**(base | fields))


def test_direct_call_refuses_a_too_long_consequence(client):
    long = "x" * (CONSEQUENCE_MAX + 1)
    with pytest.raises(RuleViolation) as exc:
        direct(client, direct_ask(payload={"consequence": long}))

    assert exc.value.code == "too_long_consequence"
    assert long not in exc.value.message


def test_direct_call_refuses_a_consequence_that_is_not_text(client):
    with pytest.raises(RuleViolation) as exc:
        direct(client, direct_ask(payload={"consequence": 12}))

    assert exc.value.code == "invalid_consequence"


def test_direct_call_needs_human_without_consequence_is_refused(client):
    envelope = direct_ask(kind="needs_human", payload={"options": ["a", "b"]})
    with pytest.raises(RuleViolation) as exc:
        direct(client, envelope)

    assert exc.value.code == "consequence_required"
    assert rows(client) == []


def test_a_direct_call_opens_the_approval_too(client):
    direct(client, direct_ask())

    assert len(rows(client)) == 1


def test_an_identical_resend_of_an_old_needs_human_without_consequence_is_still_a_read_back(client):
    """Old asks (before this rule) stay replayable: the rule applies to new events only (D3)."""
    envelope = direct_ask(kind="needs_human", payload={"options": ["a", "b"], "consequence": "x"})
    first = direct(client, envelope, "old")
    with client.app.state.sessionmaker() as session:
        event = session.get(Event, first[0])
        event.payload = {"options": ["a", "b"]}  # as stored before the rule existed
        session.commit()

    again = direct(client, direct_ask(kind="needs_human", payload={"options": ["a", "b"]}), "old")

    assert again == (first[0], False)


# --- expires_at -------------------------------------------------------------------------------


def test_expires_at_is_stored_as_the_utc_instant(client, monkeypatch):
    monkeypatch.setattr("nexus.events.service.now", lambda: datetime(2026, 10, 25, tzinfo=UTC))
    res = ask(client, "e1", payload={"expires_at": "2026-10-25T02:15:00+01:00"})

    assert res.status_code == 201, res.text
    [approval] = rows(client)
    # Compared as UTC instants: an aware `==` across zones trips over PEP 495 `fold`.
    assert approval.expires_at.astimezone(UTC) == datetime(2026, 10, 25, 1, 15, tzinfo=UTC)
    # The payload keeps what was declared (an event is immutable).
    assert res.json()["payload"]["expires_at"] == "2026-10-25T02:15:00+01:00"


@pytest.mark.parametrize(
    "value",
    ["2026-10-25T02:15:00", "2026-10-25", "demain", "", "2026-13-45T00:00:00+00:00"],
)
def test_expires_at_without_timezone_or_unreadable_is_refused(client, value):
    res = ask(client, "e1", payload={"expires_at": value})

    assert code_of(res) == "invalid_expires_at"
    if value:
        assert value not in res.text


@pytest.mark.parametrize("value", [1790000000, True, ["2026-10-25T00:00:00+00:00"], {"a": 1}])
def test_expires_at_that_is_not_a_string_is_refused(client, value):
    res = ask(client, "e1", payload={"expires_at": value})

    assert code_of(res) == "invalid_expires_at"


def test_expires_at_in_the_past_is_refused(client):
    res = ask(client, "e1", payload={"expires_at": in_days(-1)})

    assert code_of(res) == "expires_at_too_soon"
    assert rows(client) == []


def test_expires_at_under_one_minute_is_refused(client):
    res = ask(client, "e1", payload={"expires_at": (now() + timedelta(seconds=30)).isoformat()})

    assert code_of(res) == "expires_at_too_soon"


def test_expires_at_over_thirty_days_is_refused(client):
    res = ask(client, "e1", payload={"expires_at": in_days(31)})

    assert code_of(res) == "expires_at_too_far"


def test_expires_at_inside_the_window_is_accepted(client):
    assert ask(client, "e1", payload={"expires_at": in_days(2)}).status_code == 201


def test_an_identical_resend_after_the_deadline_is_a_read_back(client, monkeypatch):
    first = ask(client, "e1", payload={"expires_at": in_days(1)})
    assert first.status_code == 201
    monkeypatch.setattr("nexus.events.service.now", lambda: now() + timedelta(days=2))

    again = ask(client, "e1", payload={"expires_at": first.json()["payload"]["expires_at"]})

    assert again.status_code == 200, again.text
    assert again.json()["effects"] == first.json()["effects"]
    assert len(rows(client)) == 1


def test_a_new_ask_after_the_deadline_of_another_is_judged_on_its_own_date(client, monkeypatch):
    monkeypatch.setattr("nexus.events.service.now", lambda: now() + timedelta(days=2))

    res = ask(client, "e2", payload={"expires_at": in_days(1)})

    assert code_of(res) == "expires_at_too_soon"


def pinned(monkeypatch, received: datetime) -> None:
    monkeypatch.setattr("nexus.events.service.now", lambda: received)


def test_dst_fold_later_wall_time_can_be_an_earlier_instant(client, monkeypatch):
    # 2026-10-25 02:15+01:00 (winter) is 45 minutes AFTER 02:30+02:00 (summer): compare instants.
    pinned(monkeypatch, datetime.fromisoformat("2026-10-25T02:30:00+02:00"))
    ok = ask(client, "e1", payload={"expires_at": "2026-10-25T02:15:00+01:00"})
    assert ok.status_code == 201, ok.text

    # Reverse: 02:30+02:00 is BEFORE 02:15+01:00, although its wall time reads later.
    pinned(monkeypatch, datetime.fromisoformat("2026-10-25T02:15:00+01:00"))
    res = ask(client, "e2", payload={"expires_at": "2026-10-25T02:30:00+02:00"})
    assert code_of(res) == "expires_at_too_soon"


def test_dst_fold_with_the_paris_zone_itself(client, monkeypatch):
    summer = datetime(2026, 10, 25, 2, 30, tzinfo=TZ, fold=0)  # 02:30+02:00
    assert summer.utcoffset() == timedelta(hours=2)
    pinned(monkeypatch, summer)

    res = ask(client, "e1", payload={"expires_at": "2026-10-25T02:15:00+01:00"})

    assert res.status_code == 201, res.text


def test_the_thirty_day_bound_is_an_exact_duration_with_microseconds(client, monkeypatch):
    # The window spans the DST change of 2026-10-25: 30 days of wall time are 30 days + 1 h.
    received = datetime(2026, 10, 7, 10, 0, 0, 123456, tzinfo=TZ)
    pinned(monkeypatch, received)
    limit = received.astimezone(UTC) + timedelta(days=30)

    assert ask(client, "e1", payload={"expires_at": limit.isoformat()}).status_code == 201
    just_after = limit + timedelta(microseconds=1)
    res = ask(client, "e2", payload={"expires_at": just_after.isoformat()})
    assert code_of(res) == "expires_at_too_far"
    wall_clock_plus_30 = received + timedelta(days=30)  # 1 hour later in elapsed time
    res = ask(client, "e3", payload={"expires_at": wall_clock_plus_30.isoformat()})
    assert code_of(res) == "expires_at_too_far"


def test_the_one_minute_bound_is_exact_with_microseconds(client, monkeypatch):
    received = datetime(2026, 10, 7, 10, 0, 0, 999999, tzinfo=TZ)
    pinned(monkeypatch, received)
    low = received.astimezone(UTC) + timedelta(minutes=1)

    assert ask(client, "e1", payload={"expires_at": low.isoformat()}).status_code == 201
    below = low - timedelta(microseconds=1)
    assert code_of(ask(client, "e2", payload={"expires_at": below.isoformat()})) == (
        "expires_at_too_soon"
    )


def test_a_far_year_near_the_datetime_limit_is_refused_not_a_crash(client):
    res = ask(client, "e1", payload={"expires_at": "9999-12-31T23:59:59.999999-05:00"})

    assert res.status_code == 409, res.text
    assert res.json()["detail"]["code"] in {"invalid_expires_at", "expires_at_too_far"}


def test_direct_call_refuses_a_non_text_expires_at(client):
    with pytest.raises(RuleViolation) as exc:
        direct(client, direct_ask(payload={"expires_at": 12345}))

    assert exc.value.code == "invalid_expires_at"


def test_direct_call_refuses_an_expiry_in_the_past(client):
    past = (now() - timedelta(hours=1)).isoformat()
    with pytest.raises(RuleViolation) as exc:
        direct(client, direct_ask(payload={"expires_at": past}))

    assert exc.value.code == "expires_at_too_soon"
    assert past not in exc.value.message


def test_expires_at_is_checked_for_every_ask_even_one_not_for_a_human(client):
    res = ask(client, "e1", needs=["mnema"], payload={"expires_at": "demain"})

    assert code_of(res) == "invalid_expires_at"
    assert client.get("/api/events").json() == []


def test_identical_resend_racing_the_first_returns_the_same_approval(client, monkeypatch):
    """The loser of a race gets the winner's event: one approval, same reference."""
    make = client.app.state.sessionmaker
    original = service._refuse_noise

    def racing(session, envelope, task_row, actor_event_id):
        # Just before the insert, another request records the identical ask.
        monkeypatch.setattr(service, "_refuse_noise", original)
        with make() as other:
            service.publish(other, direct_ask(subject="Sujet race"), "evt_race", AT_DT)
            other.commit()
        original(session, envelope, task_row, actor_event_id)

    monkeypatch.setattr(service, "_refuse_noise", racing)
    res = ask(client, "evt_race", subject="Sujet race")

    assert res.status_code == 200, res.text
    assert res.json()["effects"] == [{"action": "approval", "applied": True,
                                      "approval": "nx-appr-1"}]
    assert len(rows(client)) == 1


# --- Old events stay replayable (#26 review P2-1) ---------------------------------------------

OLD_PAYLOADS = [
    ({"expires_at": "demain"}, "invalid_expires_at"),
    ({"expires_at": 1790000000}, "invalid_expires_at"),
    ({"expires_at": "2026-10-25T02:15:00"}, "invalid_expires_at"),
    ({"consequence": {"fr": "x"}}, "invalid_consequence"),
    ({"consequence": "x" * (CONSEQUENCE_MAX + 1)}, "too_long_consequence"),
]


def store_old_ask(client, payload):
    """An ask published before the rules existed: written straight into the database."""
    event_id, _ = direct(client, direct_ask(), "old")
    with client.app.state.sessionmaker() as session:
        event = session.scalar(select(Event).where(Event.actor_event_id == "old"))
        event.payload = payload
        session.commit()
    return event_id


@pytest.mark.parametrize(("payload", "code"), OLD_PAYLOADS)
def test_an_old_ask_with_a_payload_the_rules_now_refuse_is_still_a_read_back(
    client, payload, code
):
    event_id = store_old_ask(client, payload)

    http = client.post("/api/events", json={
        "id": "old", "at": AT, "actor": "helios", "kind": "question",
        "subject": "Où est la clé ?", "needs": ["loic"], "payload": payload,
    })
    assert http.status_code == 200, http.text
    again = direct(client, direct_ask(payload=payload), "old")
    assert http.json()["id"] == f"nx-evt-{event_id}"
    assert again == (event_id, False)


@pytest.mark.parametrize(("payload", "code"), OLD_PAYLOADS)
def test_a_new_ask_with_the_same_payload_is_still_refused(client, payload, code):
    res = ask(client, "fresh", payload=payload)
    assert code_of(res) == code
    with pytest.raises(RuleViolation) as exc:
        direct(client, direct_ask(payload=payload), "fresh2")
    assert exc.value.code == code


def test_a_consequence_is_measured_raw_not_after_stripping(client):
    res = ask(client, "e1", payload={"consequence": " " * CONSEQUENCE_MAX + "x"})

    assert code_of(res) == "too_long_consequence"


def test_the_one_minute_bound_is_an_instant_across_the_autumn_change(client, monkeypatch):
    # 02:59:30+02:00, 30 s before the clocks go back: one real minute later is 02:00:30+01:00,
    # whereas one minute of wall time (03:00:30) is an hour too far.
    received = datetime(2026, 10, 25, 2, 59, 30, tzinfo=TZ)
    assert received.utcoffset() == timedelta(hours=2)
    pinned(monkeypatch, received)
    low = received.astimezone(UTC) + timedelta(minutes=1)

    assert ask(client, "e1", payload={"expires_at": low.isoformat()}).status_code == 201
