"""Vue Maintenant (#6) : l'instantané GET /api/now."""

from datetime import datetime, timedelta

from nexus import now as now_module
from nexus.clock import TZ, now

AT = "2026-09-30T09:00:00+02:00"


def create(client, **fields):
    body = {"title": "Pont lecture", "objective": "Lire les runs"} | fields
    res = client.post("/api/tasks", json=body)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def move(client, ref, status, **fields):
    res = client.post(f"/api/tasks/{ref}/status", json={"status": status} | fields)
    assert res.status_code == 200, res.text
    return res.json()


def publish(client, kind, actor="helios", **fields):
    publish.n = getattr(publish, "n", 0) + 1
    body = {
        "id": f"evt_now_{publish.n}", "at": AT, "actor": actor, "kind": kind, "subject": "s",
    } | fields
    res = client.post("/api/events", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def snapshot(client):
    res = client.get("/api/now")
    assert res.status_code == 200, res.text
    return res.json()


def test_an_empty_base_is_an_honest_snapshot(client):
    s = snapshot(client)
    assert s["source"] == "nexus.db" and s["measured_at"]
    assert s["operation"] is None and s["auxiliaries"] == []
    assert [a["agent"] for a in s["agents"]] == [
        "helios", "mnema", "aether", "artemis", "claude", "codex", "orca", "hermes"]
    assert all(a["state"] == "idle" and a["task"] is None for a in s["agents"])
    assert s["asks"] == [] and s["blocks"] == [] and s["done"] == []


def test_the_main_operation_and_its_auxiliaries(client):
    main = create(client, title="Refonte du pont", next_action="relire les tables")
    move(client, main, "in_progress")
    aux = create(client, title="Doc d'installation", operation_role="auxiliary", next_action="x")
    s = snapshot(client)
    assert s["operation"]["task"] == main
    assert s["operation"]["title"] == "Refonte du pont"
    assert s["operation"]["next_action"] == "relire les tables"
    assert s["operation"]["since"]
    assert s["auxiliaries"] == [{"task": aux, "title": "Doc d'installation"}]


def test_an_open_run_makes_the_agent_run_and_a_closer_makes_it_idle(client):
    ref = create(client, title="Refonte du pont", status="todo", next_action="x")
    publish(client, "claimed", task=ref)
    publish(client, "working", task=ref, payload={"run_ref": "session:abc"})
    helios = snapshot(client)["agents"][0]
    assert helios == {"agent": "helios", "state": "run", "task": ref, "title": "Refonte du pont",
                      "run": "session:abc", "since": helios["since"]}
    assert helios["since"]
    publish(client, "blocked", task=ref, run="session:abc", body="SSH",
            payload={"plan": "rallumer"})
    assert snapshot(client)["agents"][0]["state"] == "idle"


def test_a_late_working_of_a_closed_run_does_not_reopen_it(client):
    ref = create(client, title="Refonte du pont", status="todo", next_action="x")
    publish(client, "claimed", task=ref)
    publish(client, "working", task=ref, payload={"run_ref": "session:abc"})
    publish(client, "blocked", task=ref, run="session:abc", body="SSH",
            payload={"plan": "rallumer"})
    publish(client, "working", task=ref, subject="retard", payload={"run_ref": "session:abc"})
    assert snapshot(client)["agents"][0]["state"] == "idle"


def test_asks_are_questions_and_needs_human_for_loic_within_seven_days(client):
    ref = create(client)
    q = publish(client, "question", actor="mnema", subject="Quelle version ?", task=ref,
                needs=["loic"])
    publish(client, "question", actor="mnema", subject="Pour Helios", needs=["helios"])
    publish(client, "progress", actor="mnema", task=ref, payload={"percent": 5})
    s = snapshot(client)
    assert [a["event"] for a in s["asks"]] == [q["id"]]
    assert s["asks"][0] == {"event": q["id"], "agent": "mnema", "kind": "question",
                            "subject": "Quelle version ?", "task": ref, "at": s["asks"][0]["at"],
                            "received_at": s["asks"][0]["received_at"]}


def test_the_seven_day_window_is_on_reception_not_on_the_claimed_date(client):
    old = (now() - timedelta(days=8)).isoformat()
    publish(client, "needs_human", actor="helios", at=old, needs=["loic"], subject="Antidaté",
            payload={"options": ["oui", "non"]})
    # un événement antidaté mais reçu aujourd'hui est bien une demande récente
    assert [a["subject"] for a in snapshot(client)["asks"]] == ["Antidaté"]


def test_asks_received_more_than_seven_days_ago_are_left_out(client, monkeypatch):
    publish(client, "needs_human", actor="helios", needs=["loic"], subject="Ancienne",
            payload={"options": ["oui", "non"]})
    later = now() + timedelta(days=7, minutes=1)
    monkeypatch.setattr("nexus.now.now", lambda: later)
    assert snapshot(client)["asks"] == []


def test_the_seven_day_window_is_a_real_duration_across_the_dst_change(client, monkeypatch):
    # 2026-10-25 : passage à l'heure d'hiver. Reçue 7 j 0 h 30 avant la mesure (durée réelle),
    # la demande est hors fenêtre ; une soustraction en heure murale de Paris la garderait.
    received = datetime.fromisoformat("2026-10-21T12:30:00+02:00")
    measured = datetime(2026, 10, 28, 12, tzinfo=TZ)  # comme nexus.clock.now(), fuseau nommé
    monkeypatch.setattr("nexus.events.service.now", lambda: received)
    publish(client, "needs_human", actor="helios", needs=["loic"], subject="Avant le changement",
            at=received.isoformat(), payload={"options": ["oui", "non"]})
    monkeypatch.setattr("nexus.now.now", lambda: measured)
    assert snapshot(client)["asks"] == []


def test_blocks_and_their_start(client):
    ref = create(client, title="Sauvegarde distante", next_action="x", lead_agent="artemis")
    move(client, ref, "in_progress")
    move(client, ref, "blocked", block_cause="Artemis hors ligne", block_plan="rallumer")
    b = snapshot(client)["blocks"]
    assert len(b) == 1
    assert b[0]["task"] == ref and b[0]["cause"] == "Artemis hors ligne"
    assert b[0]["lead_agent"] == "artemis" and b[0]["since"]


def test_done_tasks_older_than_seven_days_are_left_out(client, monkeypatch):
    ref = create(client, title="Livrée", next_action="x")
    move(client, ref, "in_progress")
    move(client, ref, "done", evidence=["PR #1"])
    assert [d["task"] for d in snapshot(client)["done"]] == [ref]
    later = now() + timedelta(days=7, minutes=1)
    monkeypatch.setattr("nexus.now.now", lambda: later)
    assert snapshot(client)["done"] == []


def test_a_done_task_edited_later_still_leaves_the_window_on_its_done_instant(client, monkeypatch):
    ref = create(client, title="Livrée", next_action="x")
    move(client, ref, "in_progress")
    move(client, ref, "done", evidence=["PR #1"])
    later = now() + timedelta(days=7, minutes=1)
    # `updated_at` est récent (retouche), mais le passage à done date de plus de sept jours
    monkeypatch.setattr("nexus.tasks.service.now", lambda: later)
    res = client.patch(f"/api/tasks/{ref}", json={"title": "Livrée (retitrée)"})
    assert res.status_code == 200, res.text
    monkeypatch.setattr("nexus.now.now", lambda: later)
    assert snapshot(client)["done"] == []


def test_recent_done_with_evidence_at_most_five(client):
    refs = []
    for i in range(6):
        ref = create(client, title=f"T{i}", next_action="x")
        move(client, ref, "in_progress")
        move(client, ref, "done", evidence=[f"PR #{i}"])
        refs.append(ref)
    done = snapshot(client)["done"]
    assert [d["task"] for d in done] == list(reversed(refs))[:5]
    assert done[0]["evidence"] == ["PR #5"] and done[0]["at"]


def test_a_closer_on_another_task_or_by_another_actor_does_not_close_the_run(client):
    mine = create(client, title="Pont", status="todo", next_action="x")
    other = create(client, title="Autre", status="todo", next_action="x")
    publish(client, "claimed", task=mine)
    publish(client, "working", task=mine, payload={"run_ref": "session:abc"})
    # même run_ref, mais une autre tâche : ne ferme pas le run de `mine`
    publish(client, "claimed", actor="mnema", task=other)
    publish(client, "blocked", actor="mnema", task=other, run="session:abc", body="SSH",
            payload={"plan": "rallumer"})
    # même tâche et même run_ref, mais un autre acteur : ne le ferme pas non plus
    publish(client, "blocked", actor="codex", task=mine, run="session:abc", body="SSH",
            payload={"plan": "rallumer"})
    assert snapshot(client)["agents"][0]["state"] == "run"


def test_two_agents_runs_are_independent(client):
    a = create(client, title="Pont", status="todo", next_action="x")
    b = create(client, title="Sauvegarde", status="todo", next_action="x")
    publish(client, "claimed", actor="helios", task=a)
    publish(client, "working", actor="helios", task=a, payload={"run_ref": "session:a"})
    publish(client, "claimed", actor="mnema", task=b)
    publish(client, "working", actor="mnema", task=b, payload={"run_ref": "session:b"})
    publish(client, "blocked", actor="mnema", task=b, run="session:b", body="SSH",
            payload={"plan": "rallumer"})
    states = {x["agent"]: x for x in snapshot(client)["agents"]}
    assert states["helios"]["state"] == "run" and states["helios"]["task"] == a
    assert states["mnema"]["state"] == "idle"


def test_the_snapshot_reads_one_state_even_if_someone_commits_midway(client, monkeypatch):
    real = now_module._open_runs

    def commit_an_ask_midway(session):
        publish(client, "question", actor="mnema", subject="Arrivée en cours de lecture",
                needs=["loic"])
        return real(session)

    monkeypatch.setattr(now_module, "_open_runs", commit_an_ask_midway)
    with client.app.state.sessionmaker() as session:
        assert now_module.snapshot(session)["asks"] == []
    monkeypatch.undo()
    assert len(snapshot(client)["asks"]) == 1


def test_asks_carry_their_reception_instant(client):
    publish(client, "question", actor="mnema", subject="Q", needs=["loic"])
    ask = snapshot(client)["asks"][0]
    assert ask["received_at"]
