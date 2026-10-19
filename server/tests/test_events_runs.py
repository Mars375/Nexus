"""Tests for the run lifecycle of events: active runs, late closers and run references."""

import pytest
from events_support import AT, publish, task


def test_only_one_active_run_per_agent_and_task(client):
    ref = task(client, next_action="x")
    publish(client, "working", "Run 1", task=ref, payload={"run_ref": "r1"})

    second = publish(client, "working", "Run 2", task=ref, payload={"run_ref": "r2"})
    assert second.json()["detail"]["code"] == "run_already_active"

    # un autre agent peut travailler en parallèle
    other = client.post("/api/events", json={
        "id": "evt_codex", "at": AT, "actor": "codex", "kind": "working", "subject": "Run C",
        "task": ref, "payload": {"run_ref": "c1"},
    })
    assert other.status_code == 201

    publish(client, "blocked", task=ref, body="attente", payload={"plan": "p"}, run="r1")
    assert publish(client, "working", "Reprise", task=ref,
                   payload={"run_ref": "r2"}).status_code == 201

def test_late_closer_of_an_old_run_does_not_free_the_active_run(client):
    ref = task(client, next_action="x")
    publish(client, "working", "r1", task=ref, payload={"run_ref": "r1"})
    publish(client, "blocked", "pause r1", task=ref, body="attente",
            payload={"plan": "p", "run_ref": "r1"})
    publish(client, "working", "r2", task=ref, payload={"run_ref": "r2"})
    publish(client, "failed", "fin tardive de r1", task=ref, body="timeout",
            payload={"run_ref": "r1"})

    res = publish(client, "working", "r3", task=ref, payload={"run_ref": "r3"})
    assert res.json()["detail"]["code"] == "run_already_active"

def test_concurrent_working_runs_cannot_both_open(client, monkeypatch):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope

    ref = task(client, next_action="x")
    at = datetime.fromisoformat(AT)
    make = client.app.state.sessionmaker
    original = service._refuse_second_active_run

    def racing(session, envelope, task_row):
        original(session, envelope, task_row)  # r2 ne voit aucun run actif…
        monkeypatch.setattr(service, "_refuse_second_active_run", original)
        with make() as other:  # …mais r1 s'ouvre et s'enregistre juste avant son écriture
            service.publish(other, Envelope(actor="helios", kind="working", subject="r1",
                                            task=ref, payload={"run_ref": "r1"}), "evt_w1", at)
            other.commit()

    monkeypatch.setattr(service, "_refuse_second_active_run", racing)
    res = publish(client, "working", "r2", task=ref, id="evt_w2", payload={"run_ref": "r2"})

    # Après le conflit d'écriture, la règle est revérifiée : r1 est actif, r2 est refusé.
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "run_already_active"
    runs = [e["payload"]["run_ref"] for e in client.get("/api/events", params={"task": ref}).json()]
    assert runs == ["r1"]

def test_stale_run_completion_does_not_close_the_task(client):
    ref = task(client, next_action="x")
    publish(client, "working", "r1", task=ref, payload={"run_ref": "r1"})
    publish(client, "blocked", "pause r1", task=ref, body="attente",
            payload={"plan": "p", "run_ref": "r1"})
    publish(client, "working", "r2", task=ref, payload={"run_ref": "r2"})

    late = publish(client, "done", "fin de r1", task=ref, evidence=["commit:r1"],
                   payload={"run_ref": "r1"}).json()

    assert late["effects"][0]["applied"] is False
    assert "run actif" in late["effects"][0]["reason"]
    t = client.get(f"/api/tasks/{ref}").json()
    assert (t["status"], t["evidence"]) == ("in_progress", [])

def test_blank_top_level_run_falls_back_to_payload_run_ref(client):
    ref = task(client, next_action="x")
    publish(client, "working", "r1", task=ref, run="   ", payload={"run_ref": "r1"})

    done = publish(client, "done", "fini", task=ref, evidence=["commit:x"],
                   payload={"run_ref": "r1"}).json()
    assert done["effects"] == [{"action": "status:done", "applied": True}]

def test_other_agent_can_open_its_run_despite_a_concurrent_write(client, monkeypatch):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope

    ref = task(client, next_action="x")
    make = client.app.state.sessionmaker
    original = service._refuse_second_active_run

    def racing(session, envelope, task_row):
        original(session, envelope, task_row)
        monkeypatch.setattr(service, "_refuse_second_active_run", original)
        with make() as other:  # Codex ouvre son run pendant que Helios ouvre le sien
            service.publish(other, Envelope(actor="codex", kind="working", subject="c",
                                            task=ref, payload={"run_ref": "c1"}),
                            "evt_codex", datetime.fromisoformat(AT))
            other.commit()

    monkeypatch.setattr(service, "_refuse_second_active_run", racing)
    res = publish(client, "working", "h", task=ref, id="evt_helios", payload={"run_ref": "h1"})

    assert res.status_code == 201
    actors = {e["actor"] for e in client.get("/api/events", params={"task": ref}).json()}
    assert actors == {"helios", "codex"}

def test_stale_handoff_does_not_transfer_the_task(client):
    ref = task(client, next_action="x")
    publish(client, "working", "r1", task=ref, payload={"run_ref": "r1"})
    publish(client, "blocked", "pause", task=ref, body="attente",
            payload={"plan": "p", "run_ref": "r1"})
    publish(client, "working", "r2", task=ref, payload={"run_ref": "r2"})

    late = publish(client, "handoff", "relais r1", task=ref, needs=["aether"],
                   payload={"next_action": "reprendre", "run_ref": "r1"}).json()

    assert late["effects"][0]["applied"] is False
    assert client.get(f"/api/tasks/{ref}").json()["lead_agent"] != "aether"

def test_conflicting_run_references_are_refused(client):
    ref = task(client, next_action="x")
    res = publish(client, "working", task=ref, run="r1", payload={"run_ref": "r2"})
    assert res.json()["detail"]["code"] == "run_ref_conflict"

@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        ("done", {"evidence": ["commit:r1"]}),
        ("review", {"evidence": ["commit:r1"]}),
        ("blocked", {"body": "attente", "payload": {"plan": "p"}}),
        ("handoff", {"needs": ["aether"], "payload": {"next_action": "reprendre"}}),
    ],
)
def test_runless_closer_does_not_touch_a_task_with_an_active_run(client, kind, fields):
    ref = task(client, next_action="x")
    publish(client, "working", "r1", task=ref, payload={"run_ref": "r1"})
    publish(client, "blocked", "pause r1", task=ref, body="attente",
            payload={"plan": "p", "run_ref": "r1"})
    publish(client, "working", "r2", task=ref, payload={"run_ref": "r2"})
    before = client.get(f"/api/tasks/{ref}").json()

    late = publish(client, kind, "sans run", task=ref, **fields)

    assert late.status_code == 201, late.text  # le fait est enregistré…
    effect = late.json()["effects"][0]
    assert effect["applied"] is False  # … sans modifier la tâche
    assert "r2" in effect["reason"]
    after = client.get(f"/api/tasks/{ref}").json()
    assert (after["status"], after["lead_agent"], after["evidence"]) == (
        before["status"], before["lead_agent"], before["evidence"]
    )

def test_runless_closer_does_not_free_the_active_run(client):
    ref = task(client, next_action="x")
    publish(client, "working", "r1", task=ref, payload={"run_ref": "r1"})
    publish(client, "failed", "sans run", task=ref, body="timeout")

    res = publish(client, "working", "r2", task=ref, payload={"run_ref": "r2"})
    assert res.json()["detail"]["code"] == "run_already_active"

def test_closer_without_any_open_run_still_applies(client):
    ref = task(client, status="todo", next_action="x")
    client.post(f"/api/tasks/{ref}/status", json={"status": "in_progress"})  # par Loïc

    blocked = publish(client, "blocked", "bloqué d'emblée", task=ref, body="attente",
                      payload={"plan": "p"}).json()

    assert blocked["effects"] == [{"action": "status:blocked", "applied": True}]

def test_late_working_of_a_closed_run_does_not_reopen_the_task(client):
    ref = task(client, next_action="x")
    publish(client, "working", "r1", task=ref, id="evt_w1", payload={"run_ref": "r1"})
    publish(client, "done", "fini", task=ref, evidence=["commit:r1"], run="r1")

    # Un working tardif (ou rejoué) de r1 arrive après sa clôture.
    late = publish(client, "working", "r1 en retard", task=ref, payload={"run_ref": "r1"})

    assert late.status_code == 201, late.text  # le fait est enregistré…
    effect = late.json()["effects"][0]
    assert effect["applied"] is False  # … sans rouvrir la tâche
    assert "r1" in effect["reason"] and "clos" in effect["reason"]
    assert client.get(f"/api/tasks/{ref}").json()["status"] == "done"

def test_late_working_of_a_closed_run_does_not_count_as_active(client):
    ref = task(client, next_action="x")
    publish(client, "working", "r1", task=ref, payload={"run_ref": "r1"})
    publish(client, "blocked", "pause", task=ref, body="attente", payload={"plan": "p"}, run="r1")
    publish(client, "working", "r1 en retard", task=ref, payload={"run_ref": "r1"})

    res = publish(client, "working", "r2", task=ref, payload={"run_ref": "r2"})

    assert res.status_code == 201, res.text
    assert res.json()["effects"] == [{"action": "status:in_progress", "applied": True}]

def test_late_closer_of_an_already_closed_run_is_ignored(client):
    ref = task(client, next_action="x")
    publish(client, "working", "r1", task=ref, payload={"run_ref": "r1"})
    publish(client, "handoff", "relais", task=ref, needs=["aether"],
            payload={"next_action": "reprendre"}, run="r1")

    late = publish(client, "done", "fin tardive", task=ref, evidence=["commit:r1"], run="r1")

    assert late.status_code == 201, late.text
    effect = late.json()["effects"][0]
    assert effect["applied"] is False
    assert "r1" in effect["reason"] and "clos" in effect["reason"]
    t = client.get(f"/api/tasks/{ref}").json()
    assert (t["status"], t["lead_agent"]) == ("in_progress", "aether")

def test_runless_closers_without_any_run_keep_applying(client):
    ref = task(client, status="todo", next_action="x")
    client.post(f"/api/tasks/{ref}/status", json={"status": "in_progress"})
    publish(client, "review", "à relire", task=ref, evidence=["commit:a"])

    done = publish(client, "done", "validé", task=ref, evidence=["commit:a"]).json()

    assert done["effects"] == [{"action": "status:done", "applied": True}]
