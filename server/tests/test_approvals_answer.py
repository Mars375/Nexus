"""Answers and decisions on approvals (#26, PR 2): answer, decision, who decides, references."""

from datetime import datetime

import pytest
from approvals_support import AT, REF, TOKEN, answer, answer_events, ask, code_of, decide, untouched

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
