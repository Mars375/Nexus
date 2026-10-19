"""Tests for the task effects of events: claims, handoffs, statuses and evidence."""

from datetime import datetime

from events_support import AT, SECRET, _first_noise_check, _handoff, _history, publish, task


def test_claimed_progress_done_with_read_back(client):
    ref = task(client, status="todo", next_action="relever les tables")

    claimed = publish(client, "claimed", "Je prends le pont", task=ref)
    assert claimed.status_code == 201, claimed.text
    assert client.get(f"/api/tasks/{ref}").json()["lead_agent"] == "helios"

    working = publish(client, "working", "Session ouverte", task=ref,
                      payload={"run_ref": "session:abc"})
    assert working.json()["effects"] == [{"action": "status:in_progress", "applied": True}]

    progress = publish(client, "progress", "40 %", task=ref, payload={"percent": 40})
    assert progress.status_code == 201

    done = publish(client, "done", "Livré", task=ref, evidence=["commit:a1b2c3d"],
                   run="session:abc")
    event = done.json()
    assert event["kind"] == "done"
    assert event["effects"] == [{"action": "status:done", "applied": True}]
    assert client.get(f"/api/tasks/{ref}").json()["evidence"] == ["commit:a1b2c3d"]

    read_back = client.get(f"/api/events/{event['id']}").json()
    assert read_back["id"] == event["id"]
    assert read_back["source"] == "nexus.db"
    assert datetime.fromisoformat(read_back["measured_at"]).tzinfo is not None

    kinds = [e["kind"] for e in client.get("/api/events", params={"task": ref}).json()]
    assert kinds == ["done", "progress", "working", "claimed"]

def test_done_without_evidence_is_stored_as_review(client):
    ref = task(client, next_action="x")
    publish(client, "working", task=ref, payload={"run_ref": "r"})

    event = publish(client, "done", "Fini ?", task=ref, run="r").json()

    assert event["kind"] == "review"
    assert event["requested_kind"] == "done"
    assert client.get(f"/api/tasks/{ref}").json()["status"] == "review"

def test_blocked_moves_the_task_with_its_cause(client):
    ref = task(client, next_action="x")
    publish(client, "working", task=ref, payload={"run_ref": "r"})

    publish(client, "blocked", "SSH Artémis injoignable", task=ref, body="Timeout Tailscale",
            payload={"follow_up_at": "2026-09-29T09:00:00+02:00"}, needs=["loic"], run="r")

    t = client.get(f"/api/tasks/{ref}").json()
    assert t["status"] == "blocked"
    assert t["block_cause"] == "Timeout Tailscale"
    assert t["follow_up_at"].startswith("2026-09-29T09:00:00")

def test_handoff_changes_lead_and_next_action(client):
    ref = task(client)
    publish(client, "handoff", "À toi", task=ref, needs=["aether"],
            payload={"next_action": "poser la clé"})

    t = client.get(f"/api/tasks/{ref}").json()
    assert (t["lead_agent"], t["next_action"]) == ("aether", "poser la clé")

def test_handoff_that_changes_nothing_is_not_applied(client):
    ref = task(client, lead_agent="aether", next_action="poser la clé")
    before = client.get(f"/api/tasks/{ref}").json()
    history = len(_history(client, ref))

    effects = _handoff(client, ref).json()["effects"]

    assert [(e["action"], e["applied"]) for e in effects] == [("handoff", False)]
    assert "aether" in effects[0]["reason"] and "déjà" in effects[0]["reason"]
    after = client.get(f"/api/tasks/{ref}").json()
    assert after["updated_at"] == before["updated_at"]
    assert len(_history(client, ref)) == history

def test_handoff_same_next_action_up_to_spaces_is_not_applied(client):
    ref = task(client, lead_agent="aether", next_action="poser la clé")

    effects = _handoff(client, ref, next_action="  poser la clé  ").json()["effects"]

    assert effects[0]["applied"] is False
    assert client.get(f"/api/tasks/{ref}").json()["next_action"] == "poser la clé"

def test_handoff_to_current_lead_records_only_the_new_next_action(client):
    ref = task(client, lead_agent="aether", next_action="poser la clé")
    before = client.get(f"/api/tasks/{ref}").json()

    effects = _handoff(client, ref, next_action="tester la clé").json()["effects"]

    assert effects[0]["applied"] is True
    assert _history(client, ref)[-1]["changes"] == {
        "next_action": ["poser la clé", "tester la clé"]
    }
    assert client.get(f"/api/tasks/{ref}").json()["updated_at"] != before["updated_at"]

def test_handoff_with_same_next_action_records_only_the_new_lead(client):
    ref = task(client, lead_agent="mnema", next_action="poser la clé")

    effects = _handoff(client, ref).json()["effects"]

    assert effects[0]["applied"] is True
    assert _history(client, ref)[-1]["changes"] == {"lead_agent": ["mnema", "aether"]}

def test_handoff_is_judged_on_the_current_task_not_the_copy_read_before_the_event(
    client, monkeypatch
):
    from nexus.events import service
    from nexus.models import Task

    ref = task(client, lead_agent="aether", next_action="poser la clé")
    task_id = service.parse_task_ref(ref)

    def other_agent_takes_over(other):
        service.tasks.update_task(other, other.get(Task, task_id), {"lead_agent": "mnema"}, "loic")

    _first_noise_check(client, monkeypatch, other_agent_takes_over)
    effects = _handoff(client, ref).json()["effects"]

    assert effects[0]["applied"] is True
    assert client.get(f"/api/tasks/{ref}").json()["lead_agent"] == "aether"

def test_concurrent_handoffs_with_different_subjects_apply_once(client, monkeypatch):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope

    ref = task(client, lead_agent="mnema", next_action="x")

    def twin(other):
        service.publish(other, Envelope(
            actor="helios", kind="handoff", subject="Autre sujet", task=ref, needs=["aether"],
            payload={"next_action": "poser la clé"}), "evt_twin", datetime.fromisoformat(AT))

    _first_noise_check(client, monkeypatch, twin)
    res = _handoff(client, ref)

    assert res.status_code == 201
    assert res.json()["effects"][0]["applied"] is False
    assert [h["action"] for h in _history(client, ref)].count("updated") == 1

def test_claim_whose_update_stores_nothing_is_not_applied(client, monkeypatch):
    from nexus.events import service

    ref = task(client, lead_agent="mnema")
    monkeypatch.setattr(service.tasks, "update_task", lambda session, task, changes, actor: task)

    effects = publish(client, "claimed", task=ref).json()["effects"]

    assert [(e["action"], e["applied"]) for e in effects] == [("lead_agent", False)]

def test_refused_effect_is_reported_but_event_is_kept(client):
    ref = task(client)  # backlog : ne peut pas passer directement en done
    res = publish(client, "done", "Fini", task=ref, evidence=["commit:x"])

    assert res.status_code == 201
    effect = res.json()["effects"][0]
    assert effect["applied"] is False
    assert "non autorisé" in effect["reason"]
    assert client.get(f"/api/tasks/{ref}").json()["status"] == "backlog"

def test_partially_redacted_evidence_is_kept_as_proof_on_the_task(client):
    ref = task(client, next_action="x", expected_evidence="commit")
    publish(client, "working", task=ref, payload={"run_ref": "r1"})

    done = publish(client, "done", "fini", task=ref, evidence=[f"commit:abc token={SECRET}"],
                   run="r1").json()

    assert done["effects"] == [{"action": "status:done", "applied": True}]
    t = client.get(f"/api/tasks/{ref}").json()
    assert t["status"] == "done"
    assert t["evidence"] == ["commit:abc token=[REDACTED]"]

def test_refused_working_does_not_make_the_task_look_recently_modified(client):
    prereq = task(client, title="Prérequis", status="todo", next_action="x")
    ref = task(client, status="todo", next_action="x")
    assert client.put(f"/api/tasks/{ref}/dependencies/{prereq}").status_code == 204
    before = client.get(f"/api/tasks/{ref}").json()["updated_at"]

    working = publish(client, "working", task=ref, payload={"run_ref": "r1"}).json()

    assert working["effects"][0]["applied"] is False  # prérequis non traité
    assert client.get(f"/api/tasks/{ref}").json()["updated_at"] == before

def test_done_whose_evidence_is_only_a_redacted_label_goes_to_review(client):
    ref = task(client, next_action="x")
    publish(client, "working", task=ref, payload={"run_ref": "r1"})

    event = publish(client, "done", "fini", task=ref, run="r1",
                    evidence=["commit: token=hunter2"]).json()

    assert event["kind"] == "review"
    assert client.get(f"/api/tasks/{ref}").json()["status"] == "review"

def test_review_evidence_is_attached_so_loic_can_close_the_task(client):
    ref = task(client, next_action="x", expected_evidence="le commit")
    publish(client, "working", task=ref, payload={"run_ref": "r1"})

    review = publish(client, "review", "à relire", task=ref, run="r1",
                     evidence=["commit:a1b2c3d"]).json()

    assert review["effects"] == [{"action": "status:review", "applied": True}]
    assert client.get(f"/api/tasks/{ref}").json()["evidence"] == ["commit:a1b2c3d"]
    # Loïc valide : la preuve de l'agent suffit, la tâche se clôt.
    closed = client.post(f"/api/tasks/{ref}/status", json={"status": "done"}).json()
    assert closed["status"] == "done"

def test_effect_is_retried_after_a_concurrent_task_update(client, monkeypatch):
    from nexus.events import service
    from nexus.models import Task

    ref = task(client, next_action="x")
    publish(client, "working", task=ref, payload={"run_ref": "r1"})
    make = client.app.state.sessionmaker
    original = service._refuse_noise

    def racing(session, envelope, task_row, actor_event_id, exclude_id=None):
        if exclude_id is None:  # avant l'insertion : Loïc modifie la tâche entre-temps
            monkeypatch.setattr(service, "_refuse_noise", original)
            with make() as other:
                other.get(Task, int(ref.removeprefix("nx-task-"))).next_action = "relire"
                other.commit()
        original(session, envelope, task_row, actor_event_id, exclude_id=exclude_id)

    monkeypatch.setattr(service, "_refuse_noise", racing)
    done = publish(client, "done", "fini", task=ref, run="r1", evidence=["commit:abc"]).json()

    assert done["effects"] == [{"action": "status:done", "applied": True}]
    t = client.get(f"/api/tasks/{ref}").json()
    assert (t["status"], t["next_action"]) == ("done", "relire")

def test_effect_gives_up_after_repeated_version_conflicts(client, monkeypatch):
    from sqlalchemy.orm.exc import StaleDataError

    from nexus.events import service

    ref = task(client, next_action="x")
    publish(client, "working", task=ref, payload={"run_ref": "r1"})

    def always_stale(*_args, **_kwargs):
        raise StaleDataError("conflit simulé")

    monkeypatch.setattr(service.tasks, "change_status", always_stale)
    done = publish(client, "done", "fini", task=ref, run="r1", evidence=["commit:abc"])

    assert done.status_code == 201, done.text
    assert done.json()["effects"] == [{"action": "status:done", "applied": False,
                                       "reason": "conflit en base : trop d'écritures concurrentes"}]

def test_review_evidence_is_attached_even_when_the_task_is_already_in_review(client):
    ref = task(client, status="todo", next_action="x", expected_evidence="le commit")
    client.post(f"/api/tasks/{ref}/status", json={"status": "in_progress"})
    client.post(f"/api/tasks/{ref}/status", json={"status": "review"})  # par Loïc, sans preuve

    event = publish(client, "review", "preuve", task=ref, evidence=["commit:a1b2c3d"]).json()

    assert client.get(f"/api/tasks/{ref}").json()["evidence"] == ["commit:a1b2c3d"]
    assert event["effects"][0]["applied"] is True

def test_already_in_target_status_is_judged_on_the_current_state(client, monkeypatch):
    from nexus.events import service
    from nexus.models import Task

    ref = task(client, next_action="x")
    publish(client, "working", task=ref, payload={"run_ref": "r1"})
    publish(client, "blocked", "pause", task=ref, body="attente", payload={"plan": "p"}, run="r1")
    make = client.app.state.sessionmaker
    original = service._refuse_noise

    def racing(session, envelope, task_row, actor_event_id, exclude_id=None):
        if exclude_id is None:  # la tâche était bloquée à la lecture ; Loïc la débloque entre-temps
            monkeypatch.setattr(service, "_refuse_noise", original)
            with make() as other:
                other.get(Task, int(ref.removeprefix("nx-task-"))).status = "todo"
                other.commit()
        original(session, envelope, task_row, actor_event_id, exclude_id=exclude_id)

    monkeypatch.setattr(service, "_refuse_noise", racing)
    codex = client.post("/api/events", json={
        "id": "evt_cx", "at": AT, "actor": "codex", "kind": "blocked", "subject": "bloqué",
        "task": ref, "body": "dépendance", "payload": {"plan": "attendre"},
    }).json()

    assert codex["effects"][0]["reason"] != "déjà en blocked"

def test_claim_is_judged_on_the_current_lead_agent(client, monkeypatch):
    from nexus.events import service
    from nexus.models import Task

    ref = task(client)
    publish(client, "claimed", task=ref)  # helios est agent principal
    make = client.app.state.sessionmaker
    original = service._refuse_noise

    def racing(session, envelope, task_row, actor_event_id, exclude_id=None):
        if exclude_id is None:  # Codex prend la tâche entre la lecture et l'insertion
            monkeypatch.setattr(service, "_refuse_noise", original)
            with make() as other:
                other.get(Task, int(ref.removeprefix("nx-task-"))).lead_agent = "codex"
                other.commit()
        original(session, envelope, task_row, actor_event_id, exclude_id=exclude_id)

    monkeypatch.setattr(service, "_refuse_noise", racing)
    again = publish(client, "claimed", "je reprends", task=ref).json()

    assert again["effects"] == [{"action": "lead_agent", "applied": True}]
    assert client.get(f"/api/tasks/{ref}").json()["lead_agent"] == "helios"

def test_evidence_already_attached_is_reported_as_no_change(client):
    ref = task(client, status="todo", next_action="x", expected_evidence="le commit")
    client.post(f"/api/tasks/{ref}/status", json={"status": "in_progress"})
    client.post(f"/api/tasks/{ref}/status", json={"status": "review"})
    publish(client, "review", "preuve", task=ref, evidence=["commit:a1b2c3d"])

    again = publish(client, "review", "même preuve", task=ref, evidence=["commit:a1b2c3d"]).json()

    assert again["effects"][0]["applied"] is False
