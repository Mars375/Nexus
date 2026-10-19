"""Shared helpers for the events API tests."""

AT = "2026-09-28T09:05:00+02:00"
SECRET = "ghp_" + "B" * 36


def task(client, **fields):
    body = {"title": "Pont lecture", "objective": "Lire les runs"} | fields
    return client.post("/api/tasks", json=body).json()["id"]


def publish(client, kind, subject="s", *, id=None, **fields):
    publish.n = getattr(publish, "n", 0) + 1
    body = {"id": id or f"evt_{publish.n}", "at": AT, "actor": "helios", "kind": kind,
            "subject": subject} | fields
    return client.post("/api/events", json=body)


def _history(client, ref):
    return client.get(f"/api/tasks/{ref}/history").json()


def _handoff(client, ref, next_action="poser la clé", lead="aether", **fields):
    return publish(client, "handoff", "À toi", task=ref, needs=[lead],
                   payload={"next_action": next_action}, **fields)


def _first_noise_check(client, monkeypatch, during):
    """Run `during(other_session)` in another session, just before the event is inserted."""
    from nexus.events import service

    make = client.app.state.sessionmaker
    original = service._refuse_noise
    calls = []

    def racing(session, envelope, task_row, actor_event_id, **kwargs):
        original(session, envelope, task_row, actor_event_id, **kwargs)
        calls.append(actor_event_id)
        if len(calls) == 1:
            with make() as other:
                during(other)
                other.commit()

    monkeypatch.setattr(service, "_refuse_noise", racing)
