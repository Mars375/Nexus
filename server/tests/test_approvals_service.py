"""The `answer` kind reserved to Nexus, real time, direct service calls, review fixes (#26)."""

import pytest
from approvals_support import (
    AT,
    REF,
    TOKEN,
    answer,
    answer_events,
    approval_row,
    ask,
    code_of,
    decide,
    untouched,
)
from sqlalchemy import select

from nexus.approvals import service as approvals
from nexus.clock import now
from nexus.events import service as events
from nexus.models import Approval, Event
from nexus.tasks.rules import RuleViolation

# --- Kind `answer` is reserved to Nexus (D8) -----------------------------------------------------


def test_an_agent_cannot_publish_an_answer_event(client):
    ask(client)

    res = client.post("/api/events", json={
        "id": "answer-nx-appr-1", "at": AT, "actor": "loic", "kind": "answer",
        "subject": "réponse : nx-appr-1", "body": "fausse réponse de Loïc"})

    assert res.status_code == 422
    assert "réservé à Nexus" in res.text
    assert answer_events(client) == []
    untouched(client)


def test_a_direct_service_call_cannot_publish_an_answer_either(client):
    from nexus.events.rules import Envelope

    with client.app.state.sessionmaker() as session, pytest.raises(RuleViolation) as refused:
        events.publish(session, Envelope(actor="loic", kind="answer", subject="x"), "a1",
                       now())

    assert refused.value.code == "reserved_kind"


def test_the_events_list_filters_on_the_answer_kind(client):
    ask(client)
    answer(client)

    res = client.get("/api/events", params={"kind": "answer"})

    assert [e["kind"] for e in res.json()] == ["answer"]
    assert [e["kind"] for e in client.get("/api/events", params={"kind": "question"}).json()] == [
        "question"
    ]
    assert client.get("/api/events", params={"kind": "nope"}).status_code == 422


# --- Real time --------------------------------------------------------------------------------


def test_an_answer_is_announced_live_with_references_only(client):
    from nexus.live import changes_since, current_cursor

    ask(client)
    with client.app.state.sessionmaker() as session:
        start = current_cursor(session)

    res = answer(client, text="texte privé de la réponse")

    with client.app.state.sessionmaker() as session:
        messages, _end = changes_since(session, start)
    announced = [m for m in messages if m["type"] == "event"]
    assert [(m["kind"], m["event"]) for m in announced] == [
        ("answer", res.json()["response"]["event"])
    ]
    assert "texte privé" not in str(messages)


# --- Direct service calls (an adapter does not go through Pydantic) ------------------------------


def service_call(client, fn, *args, **kwargs):
    with client.app.state.sessionmaker() as session:
        try:
            view = fn(session, *args, **kwargs)
            session.commit()
            return view
        except RuleViolation as refused:
            session.rollback()
            return refused


def test_the_service_answers_like_the_api(client):
    ask(client)

    view = service_call(client, approvals.answer, REF, "loic", "Version 2")

    assert view.status == "answered" and view.response.body == "Version 2"
    assert view.response.actor == "loic"


@pytest.mark.parametrize("args, code", [
    (("helios", "x"), "not_addressee"),
    (("nobody", "x"), "unknown_actor"),
    ((3, "x"), "invalid_actor"),
    (("loic", None), "invalid_text"),
    (("loic", b"x"), "invalid_text"),
    (("loic", "x" * 2001), "too_long_text"),
    (("loic", "  "), "answer_required"),
    (("loic", "[REDACTED]"), "answer_required"),
    (("loic", "\ud800"), "invalid_value"),
])
def test_the_service_rechecks_what_the_http_models_guarantee_on_an_answer(client, args, code):
    ask(client)

    refused = service_call(client, approvals.answer, REF, *args)

    assert isinstance(refused, RuleViolation) and refused.code == code
    assert TOKEN not in str(refused)
    untouched(client)


@pytest.mark.parametrize("kwargs, code", [
    ({"decision": "maybe"}, "invalid_decision"),
    ({"decision": 3}, "invalid_decision"),
    ({"decision": "approved", "choice": True}, "invalid_choice"),
    ({"decision": "approved", "choice": "1"}, "invalid_choice"),
    ({"decision": "approved", "choice": 1.0}, "invalid_choice"),
    ({"decision": "approved", "choice": -1}, "choice_unknown"),
    ({"decision": "approved", "choice": 5}, "choice_unknown"),
    ({"decision": "approved"}, "choice_required"),
    ({"decision": "rejected", "note": 3}, "invalid_note"),
    ({"decision": "rejected", "note": "n" * 2001}, "too_long_note"),
    ({"decision": "rejected", "note": "\ud800"}, "invalid_value"),
])
def test_the_service_rechecks_what_the_http_models_guarantee_on_a_decision(client, kwargs, code):
    ask(client, kind="needs_human")

    refused = service_call(client, approvals.decide, REF, "loic", **kwargs)

    assert isinstance(refused, RuleViolation) and refused.code == code
    untouched(client)


def test_the_service_refuses_a_non_text_reference_as_a_404(client):
    with client.app.state.sessionmaker() as session, pytest.raises(approvals.ApprovalNotFound):
        approvals.answer(session, 1, "loic", "x")


def test_the_service_needs_a_clean_session(client):
    ask(client)
    with client.app.state.sessionmaker() as session:
        session.add(Event(actor="loic", actor_event_id="x", at=now(), received_at=now(),
                          kind="progress", subject="s", origin="api"))
        with pytest.raises(RuntimeError):
            approvals.answer(session, REF, "loic", "x")
        session.rollback()


def test_every_stored_answer_event_points_back_to_its_approval(client):
    ask(client)
    ask(client, "e2", "needs_human")
    answer(client)
    decide(client, "nx-appr-2", decision="rejected")

    with client.app.state.sessionmaker() as session:
        rows = session.execute(
            select(Approval, Event).join(Event, Event.id == Approval.response_event_id)
            .order_by(Approval.id)
        ).all()
    assert [(a.ref, e.payload["approval"], e.actor_event_id) for a, e in rows] == [
        ("nx-appr-1", "nx-appr-1", "answer-nx-appr-1"),
        ("nx-appr-2", "nx-appr-2", "answer-nx-appr-2"),
    ]


# --- Review fixes (reviewer on 7cee449) -------------------------------------------------------


def test_a_non_human_in_needs_is_not_an_addressee(client):
    ask(client, needs=["loic", "helios"])

    res = answer(client, actor="helios")

    assert code_of(res) == "not_addressee"
    untouched(client)


def squat(id="answer-nx-appr-1", **fields):
    return {"id": id, "at": AT, "actor": "loic", "kind": "question", "subject": "squat",
            "needs": ["helios"]} | fields


@pytest.mark.parametrize("id", ["answer-nx-appr-1", "answer-", "answer-whatever",
                                "  answer-nx-appr-1"])
def test_an_event_cannot_take_an_id_reserved_to_answers(client, id):
    # Before the approval exists, then after: the id is never squatted.
    before = client.post("/api/events", json=squat(id))
    ask(client)
    after = client.post("/api/events", json=squat(id, subject="squat 2"))

    for res in (before, after):
        assert res.status_code == 409, res.text
        assert res.json()["detail"]["code"] == "reserved_id"
        assert "answer-" in res.json()["detail"]["message"]
    assert answer(client).status_code == 200  # the approval can still be decided


def test_a_direct_service_call_cannot_take_a_reserved_id(client):
    from nexus.events.rules import Envelope

    with client.app.state.sessionmaker() as session, pytest.raises(RuleViolation) as refused:
        events.publish(session, Envelope(actor="loic", kind="progress", subject="x"),
                       "answer-nx-appr-9", now())

    assert refused.value.code == "reserved_id"
    assert "nx-appr-9" not in str(refused.value)


def test_a_squatted_id_in_the_database_gives_a_dedicated_refusal(client):
    ask(client)
    with client.app.state.sessionmaker() as session:  # an old squat, inserted directly
        session.add(Event(actor="loic", actor_event_id="answer-nx-appr-1", at=now(),
                          received_at=now(), kind="question", subject="squat", origin="api"))
        session.commit()

    res = answer(client)

    assert code_of(res) == "approval_id_taken"
    assert "réessaie" not in res.json()["detail"]["message"]
    assert approval_row(client) == ("pending", None, 1)


def test_a_real_race_still_says_to_retry(client, monkeypatch):
    ask(client)
    real = events.publish

    def always_bump(*args, **kwargs):
        from sqlalchemy import update

        with client.app.state.sessionmaker() as other:
            other.execute(update(Approval).values(version=Approval.version + 1))
            other.commit()
        return real(*args, **kwargs)

    monkeypatch.setattr(events, "publish", always_bump)

    res = answer(client)

    assert code_of(res) == "approval_concurrent_update"
    assert "réessaie" in res.json()["detail"]["message"]


def test_a_rejection_validates_a_given_choice(client):
    ask(client, kind="needs_human")

    refused = decide(client, decision="rejected", choice=99)

    assert code_of(refused) == "choice_unknown"
    untouched(client)
    kept = decide(client, decision="rejected", choice=1)
    assert kept.status_code == 200 and kept.json()["response"]["choice"] == 1


def test_a_blank_note_is_stored_as_no_note(client):
    ask(client, kind="needs_human")

    res = decide(client, decision="rejected", note="   ")

    assert res.status_code == 200 and res.json()["response"]["text"] is None
    event = client.get(f"/api/events/{res.json()['response']['event']}").json()
    assert event["body"] is None


def test_two_notes_that_differ_only_by_a_masked_secret_are_the_same_decision(client):
    # The comparison is made on what is stored: after masking. Documented, not an accident.
    other = "gh" + "p" + "_" + "B" * 36
    ask(client, kind="needs_human")
    first = decide(client, decision="rejected", note=f"clé {TOKEN}")

    again = decide(client, decision="rejected", note=f"clé {other}")

    assert (first.status_code, again.status_code) == (200, 200)
    assert again.json()["response"] == first.json()["response"]
    assert len(answer_events(client)) == 1
