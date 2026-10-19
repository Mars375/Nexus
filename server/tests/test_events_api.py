"""Tests for the events HTTP surface: reads, origins, 404 and refusals."""

import pytest
from events_support import AT, SECRET, publish, task


def test_coordination_event_without_task(client):
    res = publish(client, "question", "Quel scope pour les mails ?", needs=["loic"])
    assert res.status_code == 201
    assert res.json()["task"] is None
    # No task effect, but the ask for a human opens an approval (#26).
    assert res.json()["effects"] == [
        {"action": "approval", "applied": True, "approval": "nx-appr-1"}
    ]

def test_actor_header_must_match(client):
    res = client.post(
        "/api/events",
        json={"id": "e", "at": AT, "actor": "helios", "kind": "question", "subject": "?",
              "needs": ["loic"]},
        headers={"X-Nexus-Actor": "codex"},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "actor_mismatch"

def test_unknown_task_and_event_404(client):
    assert publish(client, "claimed", task="nx-task-999").status_code == 404
    assert client.get("/api/events/nx-evt-999").status_code == 404

def test_no_update_or_delete_route_exists(client):
    ref = task(client)
    event_id = publish(client, "claimed", task=ref).json()["id"]

    assert client.patch(f"/api/events/{event_id}", json={"subject": "x"}).status_code == 405
    assert client.delete(f"/api/events/{event_id}").status_code == 405

def test_invalid_references_are_never_echoed(client):
    res = publish(client, "claimed", task=SECRET)
    assert res.status_code == 409 and SECRET not in res.text

    for ref in (SECRET, "²", "9" * 5000):
        res = client.get(f"/api/events/{ref}")
        assert res.status_code == 404 and ref not in res.text

def test_event_carries_its_origin(client):
    ref = task(client)
    event = publish(client, "claimed", task=ref).json()

    assert event["origin"] == "api"
    assert event["source"] == "nexus.db"

def test_publish_refuses_a_session_with_pending_writes(client):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope
    from nexus.models import Task

    ref = task(client)
    with client.app.state.sessionmaker() as session:
        session.get(Task, int(ref.removeprefix("nx-task-"))).title = "modifiée, pas encore écrite"
        # Une course résolue par rollback annulerait cette écriture sans rien dire : refus net.
        with pytest.raises(RuntimeError, match="session dédiée"):
            service.publish(session, Envelope(actor="helios", kind="claimed", subject="s",
                                              task=ref), "evt_pending", datetime.fromisoformat(AT))

def test_adapter_origin_is_stored_and_returned(client):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope

    ref = task(client)
    with client.app.state.sessionmaker() as session:
        event, created = service.publish(
            session, Envelope(actor="helios", kind="claimed", subject="s", task=ref),
            "evt_hermes", datetime.fromisoformat(AT), origin="hermes",
        )
        session.commit()
        event_id = event.id
    assert created
    assert client.get(f"/api/events/nx-evt-{event_id}").json()["origin"] == "hermes"
