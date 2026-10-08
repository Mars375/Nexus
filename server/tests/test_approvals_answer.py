"""Answers and decisions on approvals (#26, PR 2): POST answer / decision, kind `answer`.

A decision is an immutable `answer` event (the journal) plus the approval row (the state), written
in ONE transaction. Covers HTTP and direct service calls, idempotence and races.
"""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from nexus.approvals import service as approvals
from nexus.clock import now
from nexus.events import service as events
from nexus.models import Approval, Event
from nexus.tasks.rules import RuleViolation

AT = "2026-09-28T09:05:00+02:00"
TOKEN = "ghp_" + "A" * 36  # built at runtime: never a literal secret in the repository
REF = "nx-appr-1"


def ask(client, id="e1", kind="question", actor="mnema", **fields):
    body = {"id": id, "at": AT, "actor": actor, "kind": kind, "subject": f"Sujet {id}",
            "needs": ["loic"]} | fields
    if kind == "needs_human":
        body["payload"] = {"options": ["oui", "non"], "consequence": "Publie l'épisode"} | (
            fields.get("payload") or {}
        )
    res = client.post("/api/events", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def headers(actor):
    return {"X-Nexus-Actor": actor} if actor else {}


def answer(client, ref=REF, actor=None, **body):
    return client.post(f"/api/approvals/{ref}/answer", json=body or {"text": "Version 2"},
                       headers=headers(actor))


def decide(client, ref=REF, actor=None, **body):
    return client.post(f"/api/approvals/{ref}/decision", json=body, headers=headers(actor))


def code_of(res, status=409):
    assert res.status_code == status, res.text
    return res.json()["detail"]["code"] if status == 409 else res.json()


def answer_events(client):
    return client.get("/api/events", params={"kind": "answer"}).json()


def approval_row(client, number=1):
    with client.app.state.sessionmaker() as session:
        row = session.get(Approval, number)
        return row.status, row.response_event_id, row.version


def untouched(client, number=1):
    """Nothing stored: no answer event, approval still pending, version never bumped."""
    assert answer_events(client) == []
    assert approval_row(client, number) == ("pending", None, 1)


def freeze(monkeypatch, instant):
    monkeypatch.setattr("nexus.approvals.service.now", lambda: instant)


def in_a_day():
    return (now() + timedelta(days=1)).astimezone(UTC)


# --- Answer to a question ------------------------------------------------------------------------


def test_answering_a_question_stores_an_answer_event_and_closes_the_approval(client):
    task = client.post("/api/tasks", json={"title": "Pont", "objective": "Lire"}).json()["id"]
    request = ask(client, task=task)

    res = answer(client, text="  Version 2  ")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "answered"
    assert body["decided_by"] == "loic"
    assert datetime.fromisoformat(body["decided_at"]).tzinfo is not None
    assert body["id"] == REF and body["requested_by"] == "mnema" and body["task"] == task
    event_ref = body["response"]["event"]
    assert body["response"] == {"event": event_ref, "text": "Version 2", "choice": None,
                                "redacted": []}
    event = client.get(f"/api/events/{event_ref}").json()
    assert (event["kind"], event["actor"], event["origin"]) == ("answer", "loic", "api")
    assert event["actor_event_id"] == "answer-nx-appr-1"
    assert event["task"] == task and event["needs"] == ["mnema"]
    assert event["subject"] == "réponse : nx-appr-1" and event["body"] == "Version 2"
    assert event["payload"] == {"approval": REF, "in_reply_to": request["id"],
                                "decision": "answered", "choice": None}
    assert event["effects"] == []  # no effect on the task
    assert body["decided_at"] == event["received_at"]
    # The same state is read back by the agent.
    read = client.get(f"/api/approvals/{REF}").json()
    assert read == body | {"measured_at": read["measured_at"]}


def test_an_answer_does_not_touch_the_task_nor_close_runs(client):
    task = client.post("/api/tasks", json={"title": "Pont", "objective": "Lire",
                                           "status": "todo", "next_action": "x"}).json()["id"]
    client.post("/api/events", json={"id": "w1", "at": AT, "actor": "mnema", "kind": "working",
                                     "subject": "go", "task": task, "payload": {"run_ref": "r1"}})
    before = client.get(f"/api/tasks/{task}").json()
    history_before = [h["id"] for h in client.get(f"/api/tasks/{task}/history").json()]
    ask(client, task=task)

    assert answer(client).status_code == 200

    after = client.get(f"/api/tasks/{task}").json()
    assert (after["status"], after["updated_at"]) == (before["status"], before["updated_at"])
    assert [h["id"] for h in client.get(f"/api/tasks/{task}/history").json()] == history_before
    assert client.get("/api/now").json()["agents"][1]["state"] == "run"  # mnema keeps its run


@pytest.mark.parametrize("text", [TOKEN, f"la clé est {TOKEN}", f"token={TOKEN}"])
def test_a_secret_in_the_answer_is_masked_and_listed(client, text):
    ask(client)

    res = answer(client, text=f"{text} voilà")

    assert res.status_code == 200, res.text
    assert TOKEN not in res.text
    assert "[REDACTED]" in res.json()["response"]["text"]
    assert res.json()["response"]["redacted"]
    event_ref = res.json()["response"]["event"]
    assert TOKEN not in client.get(f"/api/events/{event_ref}").text
    assert TOKEN not in client.get(f"/api/approvals/{REF}").text
    assert client.get(f"/api/events/{event_ref}").json()["redacted"] == (
        res.json()["response"]["redacted"]
    )


@pytest.mark.parametrize("text", ["", "   ", "\n\t", "[REDACTED]", "token=[REDACTED]",
                                  "  password: [REDACTED] "])
def test_a_blank_or_fully_masked_answer_is_refused(client, text):
    ask(client)

    res = answer(client, text=text)

    assert code_of(res) == "answer_required"
    untouched(client)


def test_an_answer_that_only_holds_a_secret_is_refused_without_echo(client):
    ask(client)

    res = answer(client, text=TOKEN)

    assert code_of(res) == "answer_required"
    assert TOKEN not in res.text
    untouched(client)


def test_the_answer_text_is_capped_at_2000_characters(client):
    ask(client)

    too_long = answer(client, text="x" * 2001)

    assert too_long.status_code == 422
    assert "x" * 50 not in too_long.text and "2000" in too_long.text
    untouched(client)
    assert answer(client, text="x" * 2000).status_code == 200


@pytest.mark.parametrize("body", [
    {}, {"text": "ok", "choice": 0}, {"text": "ok", "extra": 1}, {"text": 3}, {"text": None},
    {"text": ["a"]},
])
def test_an_invalid_answer_body_is_a_422(client, body):
    ask(client)

    res = client.post(f"/api/approvals/{REF}/answer", json=body)

    assert res.status_code == 422
    untouched(client)


@pytest.mark.parametrize("route, fragment", [
    ("answer", r'"text": "a\ud800b"'),
    ("decision", r'"decision": "rejected", "note": "\udfff"'),
])
def test_a_lone_surrogate_is_refused_before_storage(client, route, fragment):
    ask(client, kind="needs_human")

    res = client.post(f"/api/approvals/{REF}/{route}", content="{" + fragment + "}",
                      headers={"Content-Type": "application/json"})

    assert res.status_code == 422, res.text
    untouched(client)


def test_an_unknown_field_name_that_is_a_secret_is_not_echoed(client):
    ask(client)

    res = answer(client, text="ok", **{f"token={TOKEN}": 1})

    assert res.status_code == 422
    assert TOKEN not in res.text


def test_a_question_is_not_decided_and_a_validation_is_not_answered(client):
    ask(client)  # nx-appr-1: question
    ask(client, "e2", "needs_human")  # nx-appr-2: needs_human

    wrong_decision = decide(client, REF, decision="approved")
    wrong_answer = answer(client, "nx-appr-2", text="oui")

    assert code_of(wrong_decision) == "wrong_kind"
    assert wrong_decision.json()["detail"]["message"] == (
        "une question se traite par une réponse, pas par une validation"
    )
    assert code_of(wrong_answer) == "wrong_kind"
    assert wrong_answer.json()["detail"]["message"] == (
        "une demande de validation se traite par une décision, pas par une réponse"
    )
    assert answer_events(client) == []


# --- Decision on a needs_human -------------------------------------------------------------------


def test_approving_stores_the_chosen_option_index_and_the_note(client):
    ask(client, kind="needs_human")

    res = decide(client, decision="approved", choice=1, note=" Go, sans la vidéo ")

    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["status"], body["decided_by"]) == ("approved", "loic")
    assert body["response"]["choice"] == 1 and body["response"]["text"] == "Go, sans la vidéo"
    event = client.get(f"/api/events/{body['response']['event']}").json()
    assert event["subject"] == "validé : nx-appr-1" and event["body"] == "Go, sans la vidéo"
    assert event["payload"]["decision"] == "approved" and event["payload"]["choice"] == 1
    assert event["needs"] == ["mnema"] and event["kind"] == "answer"
    # The chosen text is never copied: only its index.
    assert "non" not in str(event["payload"]) and "non" not in event["subject"]


def test_rejecting_needs_no_choice_and_the_note_is_optional(client):
    ask(client, kind="needs_human")

    res = decide(client, decision="rejected")

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "rejected"
    assert res.json()["response"]["text"] is None and res.json()["response"]["choice"] is None
    event = client.get(f"/api/events/{res.json()['response']['event']}").json()
    assert event["subject"] == "refusé : nx-appr-1" and event["body"] is None


def test_a_single_option_can_be_approved_without_a_choice(client):
    ask(client, kind="needs_human", payload={"options": ["ok"]})

    res = decide(client, decision="approved")

    assert res.status_code == 200 and res.json()["response"]["choice"] is None


def test_a_secret_in_the_note_is_masked_and_listed(client):
    ask(client, kind="needs_human")

    res = decide(client, decision="rejected", note=f"voici {TOKEN}")

    assert res.status_code == 200
    assert TOKEN not in res.text and res.json()["response"]["redacted"] == ["github_token"]
    assert TOKEN not in client.get(f"/api/events/{res.json()['response']['event']}").text


def test_the_note_is_capped_at_2000_characters(client):
    ask(client, kind="needs_human")

    res = decide(client, decision="rejected", note="n" * 2001)

    assert res.status_code == 422 and "n" * 50 not in res.text
    untouched(client)


@pytest.mark.parametrize("body", [
    {}, {"decision": "maybe"}, {"decision": "answered"}, {"decision": "approved", "text": "x"},
    {"decision": "rejected", "note": 3},
    {"decision": "approved", "choice": True}, {"decision": "approved", "choice": False},
    {"decision": "approved", "choice": "1"}, {"decision": "approved", "choice": 1.0},
    {"decision": "approved", "choice": [0]},
])
def test_an_invalid_decision_body_is_a_422_without_echo(client, body):
    ask(client, kind="needs_human")

    res = client.post(f"/api/approvals/{REF}/decision", json=body)

    assert res.status_code == 422
    assert "maybe" not in res.text
    untouched(client)


@pytest.mark.parametrize("choice", [2, 3, -1, 10**30])
def test_a_choice_out_of_range_is_refused(client, choice):
    ask(client, kind="needs_human")

    res = decide(client, decision="approved", choice=choice)

    assert code_of(res) == "choice_unknown"
    untouched(client)


def test_a_choice_on_a_blank_option_position_is_refused(client):
    ask(client, kind="needs_human", payload={"options": ["", "oui", 3, "non"]})

    assert code_of(decide(client, decision="approved", choice=0)) == "choice_unknown"
    assert code_of(decide(client, decision="approved", choice=2)) == "choice_unknown"
    assert decide(client, decision="approved", choice=3).json()["response"]["choice"] == 3


def test_approving_with_two_options_requires_a_choice(client):
    ask(client, kind="needs_human")

    res = decide(client, decision="approved")

    assert code_of(res) == "choice_required"
    untouched(client)


# --- Who may decide ------------------------------------------------------------------------------


def test_only_the_human_addressee_decides(client):
    ask(client)

    res = answer(client, actor="helios")

    assert code_of(res) == "not_addressee"
    untouched(client)


def test_a_human_asking_only_himself_opens_no_approval(client):
    res = ask(client, actor="loic")  # needs: [loic]

    assert res["effects"] == []
    assert client.get("/api/approvals").json() == []


def test_a_human_asking_an_agent_and_himself_opens_no_approval(client):
    res = ask(client, actor="loic", needs=["loic", "helios"])  # helios is not a human

    assert res["effects"] == []
    assert client.get("/api/approvals").json() == []


def test_an_agent_asking_a_human_opens_one(client):
    res = ask(client, actor="mnema", needs=["loic"])

    assert res["effects"] == [{"action": "approval", "applied": True, "approval": REF}]


def test_an_agent_requester_deciding_its_own_request_is_a_self_decision(client):
    ask(client, kind="needs_human", actor="helios")

    res = decide(client, actor="helios", decision="approved", choice=0)

    assert code_of(res) == "self_decision"
    untouched(client)


def test_an_unknown_actor_header_is_a_403_without_echo(client):
    ask(client)

    res = answer(client, actor=f"token={TOKEN}")

    assert res.status_code == 403 and TOKEN not in res.text
    assert res.json()["detail"]["code"] == "actor_mismatch"
    untouched(client)


def test_an_absent_actor_header_is_the_token_actor(client):
    ask(client)

    assert answer(client).json()["decided_by"] == "loic"


# --- References --------------------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["nx-appr-²", "nx-appr-" + "9" * 5000, "nx-appr-", "1",
                                 "nx-appr-1x", "NX-APPR-1", "nx-appr-" + "1" * 13])
@pytest.mark.parametrize("route", ["answer", "decision"])
def test_a_malformed_reference_is_a_generic_404(client, ref, route):
    ask(client)
    body = {"text": "ok"} if route == "answer" else {"decision": "rejected"}

    res = client.post(f"/api/approvals/{ref}/{route}", json=body)

    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "not_found"
    assert "²" not in res.text and "9999" not in res.text
    untouched(client)


def test_an_unknown_approval_is_a_404(client):
    res = answer(client, "nx-appr-42")

    assert res.status_code == 404
    assert res.json()["detail"]["message"] == "approbation introuvable : nx-appr-42"


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


# --- Races --------------------------------------------------------------------------------


def race_hook(monkeypatch, competitor):
    """Run `competitor()` between the approval's fresh read and the answer event's write."""
    real = events.publish

    def racing(*args, **kwargs):
        monkeypatch.setattr(events, "publish", real)  # only the first call races
        competitor()
        return real(*args, **kwargs)

    monkeypatch.setattr(events, "publish", racing)


def test_a_different_decision_that_wins_the_race_makes_this_one_a_409(client, monkeypatch):
    ask(client, kind="needs_human")
    race_hook(monkeypatch, lambda: decide(client, decision="rejected"))

    res = decide(client, decision="approved", choice=0)

    assert code_of(res) == "approval_already_decided"
    assert res.json()["detail"]["message"].startswith("déjà refusée par loic le ")
    [only] = answer_events(client)
    assert only["payload"]["decision"] == "rejected"
    assert client.get(f"/api/approvals/{REF}").json()["status"] == "rejected"


def test_an_identical_decision_that_wins_the_race_is_replayed_as_a_200(client, monkeypatch):
    ask(client, kind="needs_human")
    race_hook(monkeypatch, lambda: decide(client, decision="approved", choice=1))

    res = decide(client, decision="approved", choice=1)

    assert res.status_code == 200 and res.json()["status"] == "approved"
    assert len(answer_events(client)) == 1


def test_a_concurrent_write_on_the_approval_row_is_retried_not_lost(client, monkeypatch):
    # Another writer bumps the row version between our read and our write: StaleDataError.
    ask(client)
    from sqlalchemy import update

    def bump():
        with client.app.state.sessionmaker() as other:
            other.execute(update(Approval).values(version=Approval.version + 1))
            other.commit()

    race_hook(monkeypatch, bump)

    res = answer(client)

    assert res.status_code == 200 and res.json()["status"] == "answered"
    assert len(answer_events(client)) == 1
    assert "tâche" not in res.text  # not the generic « la tâche vient d'être modifiée »


def test_a_stale_row_that_never_settles_is_a_clean_409(client, monkeypatch):
    ask(client)
    from sqlalchemy import update

    def bump_always(*args, **kwargs):
        with client.app.state.sessionmaker() as other:
            other.execute(update(Approval).values(version=Approval.version + 1))
            other.commit()
        return real(*args, **kwargs)

    real = events.publish
    monkeypatch.setattr(events, "publish", bump_always)

    res = answer(client)

    assert code_of(res) == "approval_concurrent_update"
    assert "tâche" not in res.json()["detail"]["message"]
    assert answer_events(client) == []


def test_the_event_and_the_approval_are_written_in_one_transaction(client, monkeypatch):
    ask(client)

    def boom(*_args, **_kwargs):
        raise RuntimeError("panne pendant la mise à jour")

    monkeypatch.setattr(approvals, "_close", boom)
    with pytest.raises(RuntimeError):
        answer(client)

    monkeypatch.undo()
    untouched(client)


def two_threads(client, monkeypatch, first, second):
    """Both requests read the pending approval, then write at the same time."""
    barrier = threading.Barrier(2, timeout=10)
    real = events.publish
    seen = threading.local()

    def synchronised(*args, **kwargs):
        if not getattr(seen, "waited", False):
            seen.waited = True
            barrier.wait()
        return real(*args, **kwargs)

    monkeypatch.setattr(events, "publish", synchronised)
    results = {}

    def run(name, call):
        results[name] = call()

    threads = [threading.Thread(target=run, args=("a", first)),
               threading.Thread(target=run, args=("b", second))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()
    return results


def test_two_threads_with_different_decisions_have_exactly_one_winner(client, monkeypatch):
    ask(client, kind="needs_human")

    results = two_threads(
        client, monkeypatch,
        lambda: decide(client, decision="approved", choice=0),
        lambda: decide(client, decision="rejected"),
    )

    statuses = sorted(r.status_code for r in results.values())
    assert statuses == [200, 409], [r.text for r in results.values()]
    loser = next(r for r in results.values() if r.status_code == 409)
    assert loser.json()["detail"]["code"] == "approval_already_decided"
    assert len(answer_events(client)) == 1
    winner = next(r for r in results.values() if r.status_code == 200)
    assert client.get(f"/api/approvals/{REF}").json()["status"] == winner.json()["status"]


def test_two_threads_with_the_same_decision_both_get_a_200_and_one_event(client, monkeypatch):
    ask(client, kind="needs_human")

    results = two_threads(
        client, monkeypatch,
        lambda: decide(client, decision="approved", choice=1, note="go"),
        lambda: decide(client, decision="approved", choice=1, note="go"),
    )

    assert [r.status_code for r in results.values()] == [200, 200], [
        r.text for r in results.values()
    ]
    assert results["a"].json()["response"] == results["b"].json()["response"]
    assert len(answer_events(client)) == 1


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
