"""Expiry and idempotence of approval answers and decisions (#26, PR 2)."""

from datetime import timedelta

import pytest
from approvals_support import (
    REF,
    TOKEN,
    answer,
    answer_events,
    approval_row,
    ask,
    code_of,
    decide,
    freeze,
    in_a_day,
    untouched,
)

from nexus.approvals import service as approvals
from nexus.clock import now
from nexus.models import Event
from nexus.tasks.rules import RuleViolation

# --- Expiry --------------------------------------------------------------------------------


def test_an_expired_approval_is_refused_exactly_at_the_deadline(client, monkeypatch):
    expires = in_a_day()
    ask(client, payload={"expires_at": expires.isoformat()})

    freeze(monkeypatch, expires)
    res = answer(client)

    assert code_of(res) == "approval_expired"
    assert res.json()["detail"]["message"] == "cette demande a expiré : l'agent ne l'attend plus"
    assert client.get(f"/api/approvals/{REF}").json()["status"] == "expired"
    untouched(client)


def test_one_microsecond_before_the_deadline_the_answer_is_accepted(client, monkeypatch):
    expires = in_a_day()
    ask(client, payload={"expires_at": expires.isoformat()})

    freeze(monkeypatch, expires - timedelta(microseconds=1))
    res = answer(client)

    assert res.status_code == 200 and res.json()["status"] == "answered"


def test_a_decision_on_an_expired_needs_human_is_refused_and_nothing_is_written(
    client, monkeypatch
):
    expires = in_a_day()
    ask(client, kind="needs_human", payload={"expires_at": expires.isoformat()})

    freeze(monkeypatch, expires + timedelta(days=3))

    assert code_of(decide(client, decision="rejected")) == "approval_expired"
    untouched(client)


def test_the_deadline_is_judged_at_the_write_not_when_the_view_was_read(client, monkeypatch):
    # A view read as pending, then the clock passes the deadline: the answer is judged on the
    # clock at the write. (The row itself is re-read after every rollback; this does not test
    # `session.refresh`, which no behaviour distinguishes.)
    expires = in_a_day()
    ask(client, payload={"expires_at": expires.isoformat()})
    clock = iter([expires - timedelta(seconds=1), expires + timedelta(seconds=1)])
    monkeypatch.setattr("nexus.approvals.service.now", lambda: next(clock, expires))

    with client.app.state.sessionmaker() as session:
        view_before = approvals.get_approval(session, REF)
        assert view_before.status == "pending"
        with pytest.raises(RuleViolation) as refused:
            approvals.answer(session, REF, "loic", "tard")
    assert refused.value.code == "approval_expired"


# --- Idempotence --------------------------------------------------------------------------------


def test_the_same_answer_resent_is_a_200_and_stores_one_event(client):
    ask(client)
    first = answer(client, text="Version 2")

    again = answer(client, text="  Version 2 ")

    assert (first.status_code, again.status_code) == (200, 200)
    assert again.json()["response"] == first.json()["response"]
    assert again.json()["decided_at"] == first.json()["decided_at"]
    assert len(answer_events(client)) == 1
    assert approval_row(client)[2] == 2  # one write only


def test_the_same_decision_resent_is_a_200_and_stores_one_event(client):
    ask(client, kind="needs_human")
    first = decide(client, decision="approved", choice=0, note="go")

    again = decide(client, decision="approved", choice=0, note="go")

    assert (first.status_code, again.status_code) == (200, 200)
    assert again.json()["response"] == first.json()["response"]
    assert len(answer_events(client)) == 1


def test_a_resend_whose_secret_is_masked_the_same_way_is_still_the_same(client):
    ask(client)
    first = answer(client, text=f"clé {TOKEN}")

    again = answer(client, text=f"clé {TOKEN}")

    assert (first.status_code, again.status_code) == (200, 200)
    assert len(answer_events(client)) == 1


def test_a_different_answer_is_refused_with_who_and_when(client):
    ask(client)
    first = answer(client, text="Version 2")

    res = answer(client, text="Version 3")

    assert code_of(res) == "approval_already_decided"
    message = res.json()["detail"]["message"]
    assert message.startswith("déjà répondue par loic le ")
    assert "Version" not in message
    assert len(answer_events(client)) == 1
    assert client.get(f"/api/approvals/{REF}").json()["response"] == first.json()["response"]


@pytest.mark.parametrize("second, verb", [
    ({"decision": "rejected"}, "validée"),  # first was approved
    ({"decision": "approved", "choice": 0, "note": "go"}, "validée"),  # only the choice differs
    ({"decision": "approved", "choice": 1, "note": "autre"}, "validée"),  # other note
])
def test_a_different_decision_is_refused(client, second, verb):
    ask(client, kind="needs_human")
    decide(client, decision="approved", choice=1, note="go")

    res = decide(client, **second)

    assert code_of(res) == "approval_already_decided"
    assert res.json()["detail"]["message"].startswith(f"déjà {verb} par loic le ")
    assert len(answer_events(client)) == 1
    assert client.get(f"/api/approvals/{REF}").json()["status"] == "approved"


def test_a_rejected_approval_says_refusee(client):
    ask(client, kind="needs_human")
    decide(client, decision="rejected")

    res = decide(client, decision="approved", choice=0)

    assert res.json()["detail"]["message"].startswith("déjà refusée par loic le ")


def test_a_decided_approval_stays_decided_after_its_deadline(client, monkeypatch):
    expires = in_a_day()
    ask(client, payload={"expires_at": expires.isoformat()})
    first = answer(client)
    freeze(monkeypatch, expires + timedelta(days=1))

    again = answer(client)

    assert again.status_code == 200 and again.json()["status"] == "answered"
    assert again.json()["response"] == first.json()["response"]


def test_the_answer_event_id_makes_a_second_content_impossible_at_the_database(client):
    ask(client)
    answer(client)

    with client.app.state.sessionmaker() as session:
        twin = Event(actor="loic", actor_event_id="answer-nx-appr-1", at=now(),
                     received_at=now(), kind="answer", subject="x", origin="api")
        session.add(twin)
        with pytest.raises(Exception, match="UNIQUE"):
            session.flush()
