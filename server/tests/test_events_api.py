from datetime import datetime

import pytest

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


def _history(client, ref):
    return client.get(f"/api/tasks/{ref}/history").json()


def _handoff(client, ref, next_action="poser la clé", lead="aether", **fields):
    return publish(client, "handoff", "À toi", task=ref, needs=[lead],
                   payload={"next_action": next_action}, **fields)


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


def test_secret_in_event_id_is_refused(client):
    ref = task(client, next_action="x")
    refused = publish(client, "claimed", task=ref, id=f"evt {SECRET}")
    assert refused.json()["detail"]["code"] == "secret_in_event_id"
    assert SECRET not in refused.text


@pytest.mark.parametrize(
    "fields",
    [
        {"run": SECRET},
        {"payload": {"run_ref": SECRET}},
        # Masquées, ces deux références deviendraient la même : "run token=[REDACTED]".
        {"run": "run token=alpha"},
        {"payload": {"run_ref": "run token=beta"}},
    ],
)
def test_run_reference_containing_a_secret_is_refused(client, fields):
    ref = task(client, next_action="x")
    res = publish(client, "working", task=ref, **fields)

    assert res.json()["detail"]["code"] == "secret_in_run_ref"
    assert SECRET not in res.text and "alpha" not in res.text and "beta" not in res.text
    assert client.get("/api/events", params={"task": ref}).json() == []


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

    publish(client, "blocked", task=ref, body="attente", payload={"plan": "p"}, run="r1")
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


def test_nested_key_order_does_not_break_idempotency(client):
    ref = task(client)
    first = publish(client, "progress", task=ref, id="evt_n",
                    payload={"percent": 5, "meta": {"a": 1, "b": 2}})
    again = publish(client, "progress", task=ref, id="evt_n",
                    payload={"meta": {"b": 2, "a": 1}, "percent": 5})

    assert (first.status_code, again.status_code) == (201, 200)


def test_event_carries_its_origin(client):
    ref = task(client)
    event = publish(client, "claimed", task=ref).json()

    assert event["origin"] == "api"
    assert event["source"] == "nexus.db"


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


def test_handoff_needs_exactly_one_recipient(client):
    ref = task(client)
    res = publish(client, "handoff", task=ref, needs=["aether", "mnema"],
                  payload={"next_action": "poser la clé"})
    assert res.json()["detail"]["code"] == "single_recipient_required"


def test_values_under_credential_keys_are_redacted(client):
    ref = task(client)
    event = publish(client, "progress", task=ref,
                    payload={"percent": 5, "password": "hunter2", "db": {"api_key": "abc"}}).json()

    stored = client.get(f"/api/events/{event['id']}").text
    assert "hunter2" not in stored and '"abc"' not in stored
    assert event["redacted"] == ["credential"]


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_are_refused_not_stored(client, literal):
    ref = task(client)
    # Corps écrit à la main : json.dumps refuserait de produire NaN/Infinity en JSON strict.
    body = (
        f'{{"id": "evt_nan", "at": "{AT}", "actor": "helios", "kind": "progress", '
        f'"subject": "s", "task": "{ref}", "payload": {{"percent": 5, "x": {literal}}}}}'
    )
    res = client.post("/api/events", content=body, headers={"Content-Type": "application/json"})

    assert res.status_code == 422
    assert client.get("/api/events", params={"task": ref}).json() == []


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
    ("kind", "payload", "code"),
    [
        ("blocked", {"follow_up_at": "2026-09-29T09:00:00+02:00", "plan": {}}, "invalid_plan"),
        ("blocked", {"plan": "p", "cause": ["c"]}, "invalid_cause"),
        ("handoff", {"next_action": {"x": 1}}, "invalid_next_action"),
    ],
)
def test_non_text_workflow_fields_are_refused_not_500(client, kind, payload, code):
    ref = task(client, next_action="x")
    publish(client, "working", task=ref, payload={"run_ref": "r1"})

    res = publish(client, kind, task=ref, body="cause écrite", needs=["aether"], payload=payload)

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == code


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


def test_partially_redacted_evidence_is_kept_as_proof_on_the_task(client):
    ref = task(client, next_action="x", expected_evidence="commit")
    publish(client, "working", task=ref, payload={"run_ref": "r1"})

    done = publish(client, "done", "fini", task=ref, evidence=[f"commit:abc token={SECRET}"],
                   run="r1").json()

    assert done["effects"] == [{"action": "status:done", "applied": True}]
    t = client.get(f"/api/tasks/{ref}").json()
    assert t["status"] == "done"
    assert t["evidence"] == ["commit:abc token=[REDACTED]"]


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


def test_same_id_with_microseconds_apart_far_from_epoch_is_refused(client):
    ref = task(client)
    base = {"id": "evt_far", "actor": "helios", "kind": "claimed", "subject": "s", "task": ref}
    first = client.post("/api/events", json=base | {"at": "5000-06-01T00:00:00.000001+00:00"})
    assert first.status_code == 201, first.text

    other = client.post("/api/events", json=base | {"at": "5000-06-01T00:00:00.000002+00:00"})
    assert other.json()["detail"]["code"] == "event_id_reused"


def test_refused_working_does_not_make_the_task_look_recently_modified(client):
    prereq = task(client, title="Prérequis", status="todo", next_action="x")
    ref = task(client, status="todo", next_action="x")
    assert client.put(f"/api/tasks/{ref}/dependencies/{prereq}").status_code == 204
    before = client.get(f"/api/tasks/{ref}").json()["updated_at"]

    working = publish(client, "working", task=ref, payload={"run_ref": "r1"}).json()

    assert working["effects"][0]["applied"] is False  # prérequis non traité
    assert client.get(f"/api/tasks/{ref}").json()["updated_at"] == before


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


def test_working_whose_run_reads_as_redacted_is_refused(client):
    ref = task(client, next_action="x")
    res = publish(client, "working", task=ref, payload={"run_ref": "[REDACTED]"})
    assert res.json()["detail"]["code"] == "run_ref_required"


def test_unknown_field_named_like_a_secret_is_not_echoed(client):
    ref = task(client)
    res = client.post("/api/events", json={
        "id": "evt_x", "at": AT, "actor": "helios", "kind": "claimed", "subject": "s",
        "task": ref, SECRET: "x",
    })
    assert res.status_code == 422
    assert SECRET not in res.text
    assert "champ inconnu" in res.text


@pytest.mark.parametrize(
    "fragment",
    [
        r'"payload": {"percent": 5, "x": "\ud800"}',
        r'"payload": {"percent": 5, "\udfff": 1}',
        r'"body": "a\ud800b"',
    ],
)
def test_lone_surrogates_are_refused_before_storage(client, fragment):
    ref = task(client)
    raw = (
        f'{{"id": "evt_s", "at": "{AT}", "actor": "helios", "kind": "progress", '
        f'"subject": "s", "task": "{ref}", {fragment}}}'
    )
    res = client.post("/api/events", content=raw, headers={"Content-Type": "application/json"})

    assert res.status_code == 422, res.text
    assert client.get("/api/events", params={"task": ref}).status_code == 200
    assert client.get("/api/events", params={"task": ref}).json() == []


def test_valid_surrogate_pair_is_an_ordinary_character(client):
    ref = task(client)
    raw = (
        f'{{"id": "evt_e", "at": "{AT}", "actor": "helios", "kind": "progress", '
        rf'"subject": "fusée \ud83d\ude80", "task": "{ref}", "payload": {{"percent": 5}}}}'
    )
    res = client.post("/api/events", content=raw, headers={"Content-Type": "application/json"})
    assert res.status_code == 201, res.text
    assert res.json()["subject"] == "fusée 🚀"


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


@pytest.mark.parametrize(
    "fields", [{"actor": "codx"}, {"kind": "termine"}, {"needs": ["loic", "codx"]}]
)
def test_http_api_refuses_unknown_actor_kind_or_recipient_with_422(client, fields):
    ref = task(client)
    body = {"id": "evt_bad", "at": AT, "actor": "helios", "kind": "question",
            "subject": "s", "task": ref, "needs": ["loic"]} | fields
    res = client.post("/api/events", json=body)
    assert res.status_code == 422, res.text
    assert client.get("/api/events", params={"task": ref}).json() == []


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


@pytest.mark.parametrize(
    "origin",
    ["token=ghp_" + "S" * 36, "Hermes Adapter!", "", "sk-proj-" + "a1b2c3d4e5f6g7h8i9j0k1l2"],
)
def test_adapter_origin_must_be_a_plain_adapter_name(client, origin):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope
    from nexus.tasks.rules import RuleViolation

    ref = task(client)
    with client.app.state.sessionmaker() as session:
        with pytest.raises(RuleViolation) as refused:
            service.publish(session, Envelope(actor="helios", kind="claimed", subject="s",
                                              task=ref), "evt_o", datetime.fromisoformat(AT),
                            origin=origin)
    assert refused.value.code == "invalid_origin"
    assert "S" * 36 not in refused.value.message


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


@pytest.mark.parametrize(
    "fields",
    [
        {"payload": {"x": "\ud800"}},
        {"payload": {"x": float("nan")}},
        {"body": "a\udfffb"},
        {"payload": {"\ud800": 1}},
        {"payload": {"x": ("\ud800",)}},
    ],
)
def test_adapter_payload_is_checked_like_the_api(client, fields):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope
    from nexus.tasks.rules import RuleViolation

    ref = task(client)
    envelope = Envelope(actor="helios", kind="progress", subject="s", task=ref,
                        **({"body": "avance"} | fields))
    with client.app.state.sessionmaker() as session:
        with pytest.raises(RuleViolation):
            service.publish(session, envelope, "evt_adapter", datetime.fromisoformat(AT),
                            origin="hermes")
    assert client.get("/api/events", params={"task": ref}).status_code == 200


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


@pytest.mark.parametrize("event_id", ["   ", "[REDACTED]"])
def test_blank_or_redacted_event_id_is_refused(client, event_id):
    ref = task(client)
    res = publish(client, "claimed", task=ref, id=event_id)
    assert res.status_code in (409, 422), res.text
    assert client.get("/api/events", params={"task": ref}).json() == []


def test_naive_timestamp_from_an_adapter_is_refused(client):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope
    from nexus.tasks.rules import RuleViolation

    ref = task(client)
    with client.app.state.sessionmaker() as session:
        with pytest.raises(RuleViolation) as refused:
            service.publish(session, Envelope(actor="helios", kind="claimed", subject="s",
                                              task=ref), "evt_naive", datetime(2026, 9, 29, 9, 0),
                            origin="hermes")
    assert refused.value.code == "invalid_instant"


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


def test_unreadable_evidence_on_a_task_already_in_review_is_refused(client):
    ref = task(client, status="todo", next_action="x", expected_evidence="le commit")
    client.post(f"/api/tasks/{ref}/status", json={"status": "in_progress"})
    client.post(f"/api/tasks/{ref}/status", json={"status": "review"})

    res = publish(client, "review", "preuve", task=ref, evidence=["commit: token=hunter2"])

    # Une preuve illisible est refusée dès la validation de l'événement, avant tout effet.
    assert res.json()["detail"]["code"] == "evidence_required"
    assert "hunter2" not in res.text
    assert client.get(f"/api/tasks/{ref}").json()["evidence"] == []


def test_attach_evidence_refuses_references_without_identifier(client):
    from nexus.models import Task
    from nexus.tasks import service as tasks
    from nexus.tasks.rules import RuleViolation

    ref = task(client)
    with client.app.state.sessionmaker() as session:
        row = session.get(Task, int(ref.removeprefix("nx-task-")))
        with pytest.raises(RuleViolation) as refused:
            tasks.attach_evidence(session, row, ["commit: [REDACTED]"], "helios")
    assert refused.value.code == "evidence_required"


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


def test_reused_id_refusal_does_not_echo_the_identifier(client):
    ref = task(client)
    publish(client, "claimed", task=ref, id="evt_mon-identifiant-perso")
    res = publish(client, "claimed", "autre contenu", task=ref, id="evt_mon-identifiant-perso")
    assert res.json()["detail"]["code"] == "event_id_reused"
    assert "mon-identifiant-perso" not in res.text


@pytest.mark.parametrize(
    "payload", [{"tags": {"a", "b"}}, {"blob": b"\x00"}, {"quand": datetime(2026, 9, 29)}]
)
def test_adapter_payload_must_be_plain_json(client, payload):
    from nexus.events import service
    from nexus.events.rules import Envelope
    from nexus.tasks.rules import RuleViolation

    ref = task(client)
    with client.app.state.sessionmaker() as session:
        with pytest.raises(RuleViolation) as refused:
            service.publish(session, Envelope(actor="helios", kind="progress", subject="s",
                                              task=ref, body="b", payload=payload),
                            "evt_json", datetime.fromisoformat(AT), origin="hermes")
    assert refused.value.code == "invalid_value"


def test_evidence_already_attached_is_reported_as_no_change(client):
    ref = task(client, status="todo", next_action="x", expected_evidence="le commit")
    client.post(f"/api/tasks/{ref}/status", json={"status": "in_progress"})
    client.post(f"/api/tasks/{ref}/status", json={"status": "review"})
    publish(client, "review", "preuve", task=ref, evidence=["commit:a1b2c3d"])

    again = publish(client, "review", "même preuve", task=ref, evidence=["commit:a1b2c3d"]).json()

    assert again["effects"][0]["applied"] is False
