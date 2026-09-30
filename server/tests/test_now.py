"""Vue Maintenant (#6) : l'instantané GET /api/now."""

from datetime import timedelta

from nexus.clock import now

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
                            "subject": "Quelle version ?", "task": ref, "at": s["asks"][0]["at"]}


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


def test_blocks_and_their_start(client):
    ref = create(client, title="Sauvegarde distante", next_action="x", lead_agent="artemis")
    move(client, ref, "in_progress")
    move(client, ref, "blocked", block_cause="Artemis hors ligne", block_plan="rallumer")
    b = snapshot(client)["blocks"]
    assert len(b) == 1
    assert b[0]["task"] == ref and b[0]["cause"] == "Artemis hors ligne"
    assert b[0]["lead_agent"] == "artemis" and b[0]["since"]


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
