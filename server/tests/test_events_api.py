from datetime import datetime

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

    done = publish(client, "done", "Livré", task=ref, evidence=["commit:a1b2c3d"])
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

    event = publish(client, "done", "Fini ?", task=ref).json()

    assert event["kind"] == "review"
    assert event["requested_kind"] == "done"
    assert client.get(f"/api/tasks/{ref}").json()["status"] == "review"


def test_blocked_moves_the_task_with_its_cause(client):
    ref = task(client, next_action="x")
    publish(client, "working", task=ref, payload={"run_ref": "r"})

    publish(client, "blocked", "SSH Artémis injoignable", task=ref, body="Timeout Tailscale",
            payload={"follow_up_at": "2026-09-29T09:00:00+02:00"}, needs=["loic"])

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


def test_refused_effect_is_reported_but_event_is_kept(client):
    ref = task(client)  # backlog : ne peut pas passer directement en done
    res = publish(client, "done", "Fini", task=ref, evidence=["commit:x"])

    assert res.status_code == 201
    effect = res.json()["effects"][0]
    assert effect["applied"] is False
    assert "non autorisé" in effect["reason"]
    assert client.get(f"/api/tasks/{ref}").json()["status"] == "backlog"


def test_invalid_event_is_refused_with_reason(client):
    ref = task(client)
    res = publish(client, "handoff", task=ref, needs=["aether"])

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "next_action_required"


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


def test_secrets_never_reach_the_database(client):
    ref = task(client)
    event = publish(client, "progress", f"clé {SECRET}", task=ref, body=f"token={SECRET}",
                    payload={"note": SECRET, "percent": 40}).json()

    stored = client.get(f"/api/events/{event['id']}").text
    assert SECRET not in stored
    assert event["redacted"] == ["github_token"]


def test_coordination_event_without_task(client):
    res = publish(client, "question", "Quel scope pour les mails ?", needs=["loic"])
    assert res.status_code == 201
    assert res.json()["task"] is None
    assert res.json()["effects"] == []


def test_actor_header_must_match(client):
    res = client.post(
        "/api/events",
        json={"id": "e", "at": AT, "actor": "helios", "kind": "question", "subject": "?",
              "needs": ["loic"]},
        headers={"X-Nexus-Actor": "codex"},
    )
    assert res.status_code == 422


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


def test_unknown_event_field_is_refused(client):
    ref = task(client)
    res = publish(client, "claimed", task=ref, statut="x")
    assert res.status_code == 422
    assert "champ inconnu" in res.text


def test_secret_only_cause_or_evidence_does_not_count(client):
    ref = task(client, next_action="x")
    publish(client, "working", task=ref, payload={"run_ref": "r"})

    blocked = publish(client, "blocked", task=ref, body=SECRET, payload={"plan": "p"})
    assert blocked.json()["detail"]["code"] == "block_cause_required"

    done = publish(client, "done", "Fini", task=ref, evidence=[SECRET]).json()
    assert done["kind"] == "review"


def test_secret_in_event_id_or_run_is_never_stored(client):
    ref = task(client, next_action="x")
    event = publish(client, "working", task=ref, id=SECRET, run=SECRET,
                    payload={"run_ref": "r1"}).json()

    stored = client.get(f"/api/events/{event['id']}").text
    assert SECRET not in stored
    assert "[REDACTED]" in event["actor_event_id"]


def test_non_string_run_ref_is_refused_not_500(client):
    ref = task(client)
    res = publish(client, "progress", task=ref, payload={"percent": 40, "run_ref": {}})
    assert res.json()["detail"]["code"] == "invalid_run_ref"


def test_same_id_with_another_date_or_run_is_refused(client):
    ref = task(client)
    publish(client, "working", task=ref, id="evt_a", payload={"run_ref": "r1"})

    other_date = client.post("/api/events", json={
        "id": "evt_a", "at": "2026-09-28T10:00:00+02:00", "actor": "helios", "kind": "working",
        "subject": "s", "task": ref, "payload": {"run_ref": "r1"},
    })
    assert other_date.json()["detail"]["code"] == "event_id_reused"


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

    publish(client, "blocked", task=ref, body="attente", payload={"plan": "p"})
    assert publish(client, "working", "Reprise", task=ref,
                   payload={"run_ref": "r2"}).status_code == 201


def test_secret_used_as_payload_key_is_redacted(client):
    ref = task(client)
    event = publish(client, "progress", task=ref, payload={"percent": 10, SECRET: "x"}).json()

    assert SECRET not in client.get(f"/api/events/{event['id']}").text
    assert event["redacted"] == ["github_token"]


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
