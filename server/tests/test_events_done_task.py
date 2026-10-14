"""Agent events on a done task (ADR-022, #65): recorded, their effects refused or joined."""

import itertools

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from nexus.events import service as events
from nexus.models import Task

AT = "2026-10-14T09:00:00+02:00"
DONE_IS_FINAL = (
    "tâche terminée : elle ne se modifie plus ; commente-la, joins-lui une preuve ou ouvre "
    "une tâche de suite"
)
ALREADY_JOINED = "evidence : déjà jointe à la tâche"
_ids = itertools.count(1)


def publish(client, kind, *, actor="helios", subject=None, **fields):
    n = next(_ids)
    body = {"id": f"evt_{n}", "at": AT, "actor": actor, "kind": kind,
            "subject": subject or f"{kind} {n}"} | fields
    res = client.post("/api/events", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def made(client, **fields):
    body = {"title": "Pont", "objective": "Lire", "status": "todo", "next_action": "relever",
            "lead_agent": "helios"} | fields
    res = client.post("/api/tasks", json=body)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def move(client, ref, status, **fields):
    res = client.post(f"/api/tasks/{ref}/status", json={"status": status} | fields)
    assert res.status_code == 200, res.text


def closed(client, evidence=("commit:abc",), **fields):
    ref = made(client, **fields)
    move(client, ref, "in_progress")
    move(client, ref, "done", evidence=list(evidence))
    return ref


def task(client, ref):
    return client.get(f"/api/tasks/{ref}").json()


def refused(action, reason=DONE_IS_FINAL):
    return [{"action": action, "applied": False, "reason": reason}]


@pytest.fixture
def ref(client):
    return closed(client)


def unchanged(client, ref, before):
    after = task(client, ref)
    assert (after["status"], after["updated_at"], after["evidence"], after["lead_agent"],
            after["next_action"]) == (before["status"], before["updated_at"], before["evidence"],
                                      before["lead_agent"], before["next_action"])


def test_claimed_by_another_agent_does_not_take_a_done_task(client, ref):
    before = task(client, ref)
    event = publish(client, "claimed", actor="aether", task=ref)
    assert event["effects"] == refused("lead_agent")
    unchanged(client, ref, before)


def test_claimed_by_the_lead_agent_has_no_effect(client, ref):
    assert publish(client, "claimed", actor="helios", task=ref)["effects"] == []


def test_working_does_not_reopen_a_done_task_but_the_run_is_open(client, ref):
    before = task(client, ref)
    event = publish(client, "working", task=ref, payload={"run_ref": "r1"})
    assert event["effects"] == refused("status:in_progress")
    unchanged(client, ref, before)
    res = client.post("/api/events", json={
        "id": "evt_other_run", "at": AT, "actor": "helios", "kind": "working", "subject": "s",
        "task": ref, "payload": {"run_ref": "r2"}})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "run_already_active"


def test_working_on_a_closed_run_keeps_its_own_reason(client, ref):
    publish(client, "working", task=ref, payload={"run_ref": "r1"})
    publish(client, "failed", task=ref, run="r1", body="refusé")
    event = publish(client, "working", task=ref, payload={"run_ref": "r1"})
    [effect] = event["effects"]
    assert effect["action"] == "status:in_progress" and effect["applied"] is False
    assert "est déjà clos" in effect["reason"]


def test_blocked_is_refused_with_the_done_reason(client, ref):
    before = task(client, ref)
    event = publish(client, "blocked", task=ref, body="Timeout", payload={"plan": "rallumer"})
    assert event["effects"] == refused("status:blocked")
    unchanged(client, ref, before)


def test_review_is_refused_and_its_evidence_is_not_joined(client, ref):
    before = task(client, ref)
    event = publish(client, "review", task=ref, evidence=["commit:new"])
    assert event["effects"] == refused("status:review")
    unchanged(client, ref, before)


def test_a_done_without_evidence_is_recorded_as_review_and_refused(client, ref):
    before = task(client, ref)
    event = publish(client, "done", task=ref)
    assert event["kind"] == "review"
    assert event["effects"] == refused("status:review")
    unchanged(client, ref, before)


def test_a_done_with_new_evidence_is_already_done_and_joins_it(client, ref):
    event = publish(client, "done", task=ref, evidence=["commit:new"])
    assert event["effects"] == [
        {"action": "status:done", "applied": False, "reason": "déjà en done"},
        {"action": "evidence", "applied": True},
    ]
    assert task(client, ref)["evidence"] == ["commit:abc", "commit:new"]
    assert task(client, ref)["status"] == "done"


def test_a_done_with_the_same_evidence_gives_two_effects_never_one(client, ref):
    before = task(client, ref)
    event = publish(client, "done", task=ref, evidence=["commit:abc"])
    assert event["effects"] == [
        {"action": "status:done", "applied": False, "reason": "déjà en done"},
        {"action": "evidence", "applied": False, "reason": ALREADY_JOINED},
    ]
    unchanged(client, ref, before)


def test_a_done_with_only_a_masked_label_counts_as_no_evidence(client, ref):
    event = publish(client, "done", task=ref, evidence=["commit: [REDACTED]"])
    assert event["kind"] == "review"
    assert event["effects"] == refused("status:review")


def test_review_on_review_with_the_same_evidence_has_the_evidence_effect_only(client):
    ref = made(client)
    move(client, ref, "in_progress")
    move(client, ref, "review", evidence=["commit:abc"])
    event = publish(client, "review", task=ref, evidence=["commit:abc"])
    assert event["effects"] == [{"action": "evidence", "applied": False, "reason": ALREADY_JOINED}]
    event = publish(client, "review", task=ref, evidence=["commit:new"])
    assert event["effects"] == [{"action": "evidence", "applied": True}]


def test_without_evidence_the_only_effect_is_already_in_the_target(client, ref):
    assert publish(client, "done", task=ref, evidence=[], actor="helios")["effects"] == refused(
        "status:review"
    )  # recorded as review, as always
    review = made(client)
    move(client, review, "in_progress")
    move(client, review, "review")
    # `review` itself must point at evidence; a `done` without any is recorded as `review`.
    assert publish(client, "done", task=review)["effects"] == refused(
        "status:review", "déjà en review"
    )


def test_handoff_rights_come_before_the_state(client, ref):
    before = task(client, ref)
    event = publish(client, "handoff", actor="codex", task=ref, needs=["aether"],
                    payload={"next_action": "poser la clé"})
    assert event["effects"] == refused(
        "handoff", "lead_agent : un exécutant ne peut désigner que lui-même, un humain ou "
                   "personne")
    unchanged(client, ref, before)


def test_an_identical_handoff_keeps_its_own_reason(client, ref):
    action = task(client, ref)["next_action"]
    event = publish(client, "handoff", actor="mnema", task=ref, needs=["helios"],
                    payload={"next_action": action})
    assert event["effects"] == refused(
        "handoff", "helios a déjà la main, avec la même prochaine action"
    )


@pytest.mark.parametrize(("needs", "next_action"), [("loic", "relever"), ("helios", "autre")])
def test_any_other_handoff_is_refused_with_the_done_reason(client, ref, needs, next_action):
    before = task(client, ref)
    event = publish(client, "handoff", actor="mnema", task=ref, needs=[needs],
                    payload={"next_action": next_action})
    assert event["effects"] == refused("handoff")
    unchanged(client, ref, before)


@pytest.mark.parametrize("kind", ["progress", "question"])
def test_other_kinds_change_nothing(client, ref, kind):
    before = task(client, ref)
    fields = {"needs": ["loic"]} if kind == "question" else {}
    event = publish(client, kind, task=ref, body="x", **fields)
    assert [e for e in event["effects"] if e["action"] != "approval"] == []
    unchanged(client, ref, before)


# --- The state is judged on every attempt (defence: injected, not reachable) -----------------


def inject_stale_once(monkeypatch, ref, *, status, evidence=()):
    """The first status change loses a version race against a write that lands `status`.

    The competing write goes through the same connection right after the savepoint rollback: a
    second connection would wait on the write lock the event's own transaction already holds.
    """
    real_change = events.tasks.change_status
    real_refresh = Session.refresh
    pending = []

    def raising(*args, **kwargs):
        monkeypatch.setattr(events.tasks, "change_status", real_change)
        pending.append(True)
        raise StaleDataError("conflit simulé")

    def refresh(self, instance, *args, **kwargs):
        if pending:
            pending.clear()
            monkeypatch.setattr(Session, "refresh", real_refresh)
            self.execute(update(Task).where(Task.id == int(ref[8:])).values(
                status=status, evidence=list(evidence), version=Task.version + 1))
        return real_refresh(self, instance, *args, **kwargs)

    monkeypatch.setattr(events.tasks, "change_status", raising)
    monkeypatch.setattr(Session, "refresh", refresh)


def test_a_working_that_loses_the_race_against_the_closing_is_recorded_as_done(
    client, monkeypatch
):
    ref = made(client)  # todo
    move(client, ref, "in_progress")
    move(client, ref, "blocked", block_cause="c", block_plan="p")
    inject_stale_once(monkeypatch, ref, status="done", evidence=["commit:abc"])
    event = publish(client, "working", task=ref, payload={"run_ref": "r1"})
    assert event["effects"] == refused("status:in_progress")
    assert task(client, ref)["status"] == "done"


def test_a_done_that_loses_the_race_against_the_closing_has_the_same_effects(
    client, monkeypatch
):
    ref = made(client)
    move(client, ref, "in_progress")
    inject_stale_once(monkeypatch, ref, status="done", evidence=["commit:abc"])
    event = publish(client, "done", task=ref, evidence=["commit:new"])
    assert event["effects"] == [
        {"action": "status:done", "applied": False, "reason": "déjà en done"},
        {"action": "evidence", "applied": True},
    ]
    assert task(client, ref)["evidence"] == ["commit:abc", "commit:new"]


def test_a_review_that_loses_the_race_against_a_review_only_joins_its_evidence(
    client, monkeypatch
):
    ref = made(client)
    move(client, ref, "in_progress")
    inject_stale_once(monkeypatch, ref, status="review")
    event = publish(client, "review", task=ref, evidence=["commit:new"])
    assert event["effects"] == [{"action": "evidence", "applied": True}]
    assert task(client, ref)["evidence"] == ["commit:new"]
    with client.app.state.sessionmaker() as session:
        assert session.scalar(select(Task.status).where(Task.id == int(ref[8:]))) == "review"


@pytest.mark.parametrize("kind", ["failed", "needs_human", "unknown"])
def test_failed_needs_human_and_unknown_are_recorded_without_touching_a_done_task(
    client, ref, kind
):
    before = task(client, ref)
    fields = {
        "needs_human": {"needs": ["loic"],
                        "payload": {"options": ["oui", "non"], "consequence": "x"}},
        "unknown": {"payload": {"last_check_at": AT}},
    }.get(kind, {})
    event = publish(client, kind, task=ref, body="x", **fields)
    assert event["kind"] == kind and event["task"] == ref
    effects = event["effects"]
    if kind == "needs_human":  # addressed to a human: it still opens its approval, nothing else
        assert [e["action"] for e in effects] == ["approval"] and effects[0]["applied"] is True
    else:
        assert effects == []
    unchanged(client, ref, before)
    assert client.get("/api/events").json()[0]["id"] == event["id"]
