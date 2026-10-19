"""Tests for event idempotence: replays, reused ids and repeated facts."""

import pytest
from events_support import AT, _first_noise_check, _handoff, _history, publish, task


def test_identical_handoffs_racing_under_different_ids_are_noise(client, monkeypatch):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope

    ref = task(client, lead_agent="mnema", next_action="x")

    def twin(other):
        service.publish(other, Envelope(
            actor="helios", kind="handoff", subject="À toi", task=ref, needs=["aether"],
            payload={"next_action": "poser la clé"}), "evt_twin", datetime.fromisoformat(AT))

    _first_noise_check(client, monkeypatch, twin)
    res = _handoff(client, ref)

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "noise"
    assert [h["action"] for h in _history(client, ref)].count("updated") == 1

def test_same_event_resent_is_a_read_back_not_a_duplicate(client):
    ref = task(client)
    first = publish(client, "claimed", task=ref, id="evt_0001")
    again = publish(client, "claimed", task=ref, id="evt_0001")

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]
    assert len(client.get("/api/events", params={"task": ref}).json()) == 1

def test_reusing_an_id_for_another_event_is_refused(client):
    ref = task(client)
    publish(client, "claimed", task=ref, id="evt_0002")
    res = publish(client, "progress", task=ref, id="evt_0002", body="autre chose")

    assert res.json()["detail"]["code"] == "event_id_reused"

def test_repeating_the_same_fact_is_noise(client):
    ref = task(client)
    publish(client, "progress", "40 %", task=ref, payload={"percent": 40})
    res = publish(client, "progress", "40 %", task=ref, payload={"percent": 40})

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "noise"
    assert publish(client, "progress", "60 %", task=ref, payload={"percent": 60}).status_code == 201

def test_repeating_a_question_without_task_is_noise_too(client):
    publish(client, "question", "Quel scope ?", needs=["loic"])
    res = publish(client, "question", "Quel scope ?", needs=["loic"])

    assert res.json()["detail"]["code"] == "noise"

def test_same_id_with_another_date_or_run_is_refused(client):
    ref = task(client)
    publish(client, "working", task=ref, id="evt_a", payload={"run_ref": "r1"})

    other_date = client.post("/api/events", json={
        "id": "evt_a", "at": "2026-09-28T10:00:00+02:00", "actor": "helios", "kind": "working",
        "subject": "s", "task": ref, "payload": {"run_ref": "r1"},
    })
    assert other_date.json()["detail"]["code"] == "event_id_reused"

def test_identical_resend_racing_the_first_is_a_read_back(client, monkeypatch):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope

    ref = task(client)
    make = client.app.state.sessionmaker
    original = service._refuse_noise

    def racing(session, envelope, task_row, actor_event_id):
        # Juste avant l'insertion, un renvoi identique est enregistré par une autre requête.
        monkeypatch.setattr(service, "_refuse_noise", original)
        with make() as other:
            service.publish(other, Envelope(actor="helios", kind="claimed", subject="s",
                                            task=ref), "evt_race", datetime.fromisoformat(AT))
            other.commit()
        original(session, envelope, task_row, actor_event_id)

    monkeypatch.setattr(service, "_refuse_noise", racing)
    res = publish(client, "claimed", task=ref, id="evt_race")

    assert res.status_code == 200
    assert len(client.get("/api/events", params={"task": ref}).json()) == 1

def test_nested_key_order_does_not_break_idempotency(client):
    ref = task(client)
    first = publish(client, "progress", task=ref, id="evt_n",
                    payload={"percent": 5, "meta": {"a": 1, "b": 2}})
    again = publish(client, "progress", task=ref, id="evt_n",
                    payload={"meta": {"b": 2, "a": 1}, "percent": 5})

    assert (first.status_code, again.status_code) == (201, 200)

def test_identical_working_retry_racing_is_a_read_back(client, monkeypatch):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope

    ref = task(client, next_action="x")
    make = client.app.state.sessionmaker
    original = service._refuse_second_active_run

    def racing(session, envelope, task_row):
        original(session, envelope, task_row)
        monkeypatch.setattr(service, "_refuse_second_active_run", original)
        with make() as other:  # le même working, renvoyé en parallèle, gagne la course
            service.publish(other, Envelope(actor="helios", kind="working", subject="s",
                                            task=ref, payload={"run_ref": "r1"}),
                            "evt_same", datetime.fromisoformat(AT))
            other.commit()

    monkeypatch.setattr(service, "_refuse_second_active_run", racing)
    res = publish(client, "working", task=ref, id="evt_same", payload={"run_ref": "r1"})

    assert res.status_code == 200
    assert len(client.get("/api/events", params={"task": ref}).json()) == 1

def test_identical_facts_racing_under_different_ids_are_noise(client, monkeypatch):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope

    ref = task(client)
    make = client.app.state.sessionmaker
    original = service._refuse_noise
    calls = []

    def racing(session, envelope, task_row, actor_event_id, **kwargs):
        original(session, envelope, task_row, actor_event_id, **kwargs)
        calls.append(actor_event_id)
        if len(calls) == 1:  # juste après le premier contrôle, le même fait arrive sous un autre id
            with make() as other:
                service.publish(other, Envelope(actor="helios", kind="progress", subject="40 %",
                                                task=ref, payload={"percent": 40}),
                                "evt_twin", datetime.fromisoformat(AT))
                other.commit()

    monkeypatch.setattr(service, "_refuse_noise", racing)
    res = publish(client, "progress", "40 %", task=ref, id="evt_mine", payload={"percent": 40})

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "noise"
    stored = client.get("/api/events", params={"task": ref}).json()
    assert [e["actor_event_id"] for e in stored] == ["evt_twin"]

def test_same_id_with_microseconds_apart_far_from_epoch_is_refused(client):
    ref = task(client)
    base = {"id": "evt_far", "actor": "helios", "kind": "claimed", "subject": "s", "task": ref}
    first = client.post("/api/events", json=base | {"at": "5000-06-01T00:00:00.000001+00:00"})
    assert first.status_code == 201, first.text

    other = client.post("/api/events", json=base | {"at": "5000-06-01T00:00:00.000002+00:00"})
    assert other.json()["detail"]["code"] == "event_id_reused"

def test_same_id_in_the_repeated_autumn_hour_compares_instants(client):
    ref = task(client)
    base = {"id": "evt_dst", "actor": "helios", "kind": "claimed", "subject": "s", "task": ref}
    # 02:30+02:00 (00:30 UTC) puis 02:15+01:00 (01:15 UTC) : même heure murale, instants différents.
    first = client.post("/api/events", json=base | {"at": "2026-10-25T02:30:00+02:00"})
    assert first.status_code == 201, first.text

    other = client.post("/api/events", json=base | {"at": "2026-10-25T02:15:00+01:00"})
    assert other.json()["detail"]["code"] == "event_id_reused"

    same_instant = client.post("/api/events", json=base | {"at": "2026-10-25T00:30:00+00:00"})
    assert same_instant.status_code == 200  # même instant écrit en UTC : relecture

def test_same_id_from_another_origin_is_not_a_replay(client):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope
    from nexus.tasks.rules import RuleViolation

    ref = task(client)
    first = publish(client, "claimed", task=ref, id="evt_origin")
    assert first.status_code == 201
    with client.app.state.sessionmaker() as session:
        with pytest.raises(RuleViolation) as refused:
            service.publish(session, Envelope(actor="helios", kind="claimed", subject="s",
                                              task=ref), "evt_origin",
                            datetime.fromisoformat(AT), origin="hermes")
    assert refused.value.code == "event_id_reused"

def test_reused_id_refusal_does_not_echo_the_identifier(client):
    ref = task(client)
    publish(client, "claimed", task=ref, id="evt_mon-identifiant-perso")
    res = publish(client, "claimed", "autre contenu", task=ref, id="evt_mon-identifiant-perso")
    assert res.json()["detail"]["code"] == "event_id_reused"
    assert "mon-identifiant-perso" not in res.text
