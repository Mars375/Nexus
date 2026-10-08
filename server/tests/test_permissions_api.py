"""Matrice des permissions appliquée par l'API (#16, ADR-020, spec §2), par acteur."""

import pytest

from nexus.actors import ACTORS, EXECUTORS, HUMANS
from nexus.models import Task

AT = "2026-09-28T09:05:00+02:00"
BODY = {"title": "Tâche", "objective": "Faire"}
SECRET = "ghp_" + "A" * 36


def as_(client, actor):
    return client.headers_for(actor)


def create(client, actor="loic", **fields):
    return client.post("/api/tasks", json=BODY | fields, headers=as_(client, actor))


def lead_of(client, ref):
    return client.get(f"/api/tasks/{ref}").json()["lead_agent"]


# --- POST /api/tasks ------------------------------------------------------------------------


@pytest.mark.parametrize("actor", sorted(ACTORS))
@pytest.mark.parametrize("target", sorted(ACTORS))
def test_create_with_a_lead_agent(client, actor, target):
    res = create(client, actor, lead_agent=target)
    if actor in EXECUTORS and target != actor:
        assert res.status_code == 403, res.text
        assert res.json()["detail"]["code"] == "assign_forbidden"
        assert "lead_agent" in res.json()["detail"]["message"]
        assert client.get("/api/tasks").json() == []
    else:
        assert res.status_code == 201, res.text
        assert res.json()["lead_agent"] == target and res.json()["created_by"] == actor


@pytest.mark.parametrize("actor", sorted(ACTORS))
def test_create_with_collaborators(client, actor):
    own = create(client, actor, collaborators=[actor])
    assert own.status_code == 201, own.text
    other = "helios" if actor != "helios" else "mnema"
    res = create(client, actor, collaborators=[actor, other])
    if actor in EXECUTORS:
        assert res.status_code == 403
        assert res.json()["detail"]["code"] == "assign_forbidden"
        assert "collaborators" in res.json()["detail"]["message"]
        assert other not in res.text
    else:
        assert res.status_code == 201


@pytest.mark.parametrize("actor", sorted(EXECUTORS))
def test_an_executor_creates_an_unassigned_task(client, actor):
    res = create(client, actor)
    assert res.status_code == 201 and res.json()["lead_agent"] is None


# --- PATCH /api/tasks/{ref} -----------------------------------------------------------------


@pytest.mark.parametrize("actor", sorted(ACTORS))
@pytest.mark.parametrize("target", ["helios", "claude", "codex", "loic", None])
def test_patch_lead_agent(client, actor, target):
    ref = create(client, "loic", lead_agent="mnema").json()["id"]
    res = client.patch(f"/api/tasks/{ref}", json={"lead_agent": target}, headers=as_(client, actor))
    forbidden = actor in EXECUTORS and target not in (actor, "loic", None)
    if forbidden:
        assert res.status_code == 403, res.text
        assert res.json()["detail"]["code"] == "assign_forbidden"
        assert "lead_agent" in res.json()["detail"]["message"]
        assert lead_of(client, ref) == "mnema"
    else:
        assert res.status_code == 200, res.text
        assert lead_of(client, ref) == target


@pytest.mark.parametrize("actor", sorted(EXECUTORS))
def test_an_executor_takes_a_task_for_itself(client, actor):
    ref = create(client).json()["id"]
    res = client.patch(f"/api/tasks/{ref}", json={"lead_agent": actor}, headers=as_(client, actor))
    assert res.status_code == 200 and lead_of(client, ref) == actor


@pytest.mark.parametrize("actor", sorted(ACTORS))
def test_patch_that_does_not_change_the_assignment_is_not_checked(client, actor):
    ref = create(client, "loic", lead_agent="helios", collaborators=["mnema"]).json()["id"]
    res = client.patch(
        f"/api/tasks/{ref}",
        json={"title": "Renommée", "lead_agent": "helios", "collaborators": ["mnema"]},
        headers=as_(client, actor),
    )
    assert res.status_code == 200, res.text
    assert res.json()["title"] == "Renommée" and res.json()["lead_agent"] == "helios"


@pytest.mark.parametrize("actor", sorted(ACTORS))
def test_patch_collaborators(client, actor):
    ref = create(client, "loic", collaborators=["mnema"]).json()["id"]
    url = f"/api/tasks/{ref}"
    assert client.patch(url, json={"collaborators": ["mnema", actor]},
                        headers=as_(client, actor)).status_code == 200
    res = client.patch(url, json={"collaborators": ["mnema", actor, "aether"]},
                       headers=as_(client, actor))
    if actor in EXECUTORS:
        assert res.status_code == 403 and res.json()["detail"]["code"] == "assign_forbidden"
        assert "collaborators" in res.json()["detail"]["message"]
        assert "aether" not in res.text
    else:
        assert res.status_code == 200


def test_a_refused_patch_changes_nothing_at_all(client):
    ref = create(client, "loic", lead_agent="mnema").json()["id"]
    res = client.patch(f"/api/tasks/{ref}", json={"title": "Autre", "lead_agent": "helios"},
                       headers=as_(client, "codex"))
    assert res.status_code == 403
    task = client.get(f"/api/tasks/{ref}").json()
    assert task["title"] == "Tâche" and task["lead_agent"] == "mnema"
    assert [h["action"] for h in client.get(f"/api/tasks/{ref}/history").json()] == ["created"]


def test_the_forbidden_answer_never_echoes_what_was_sent(client):
    res = create(client, "codex", lead_agent="helios", objective=SECRET)
    assert res.status_code == 403 and SECRET not in res.text and "helios" not in res.text


# --- POST /api/tasks/{ref}/status -----------------------------------------------------------


@pytest.mark.parametrize("actor", sorted(ACTORS))
def test_only_humans_drop_a_task(client, actor):
    ref = create(client, "loic", status="todo", next_action="x").json()["id"]
    res = client.post(f"/api/tasks/{ref}/status", json={"status": "dropped", "reason": "inutile"},
                      headers=as_(client, actor))
    if actor in HUMANS:
        assert res.status_code == 200 and res.json()["status"] == "dropped"
    else:
        assert res.status_code == 403, res.text
        assert res.json()["detail"]["code"] == "human_only"
        assert "needs_human" in res.json()["detail"]["message"]
        assert client.get(f"/api/tasks/{ref}").json()["status"] == "todo"


@pytest.mark.parametrize("actor", sorted(ACTORS))
def test_every_actor_moves_a_task_to_another_status_and_comments(client, actor):
    ref = create(client, "loic", status="todo", next_action="x").json()["id"]
    head = as_(client, actor)
    res = client.post(f"/api/tasks/{ref}/status", json={"status": "in_progress"}, headers=head)
    assert res.status_code == 200, res.text
    res = client.post(f"/api/tasks/{ref}/comments", json={"body": "ok"}, headers=head)
    assert res.status_code == 201 and res.json()["author"] == actor


@pytest.mark.parametrize("actor", sorted(ACTORS))
def test_every_actor_links_and_unlinks_dependencies_and_reads(client, actor):
    a, b = (create(client).json()["id"] for _ in range(2))
    head = as_(client, actor)
    assert client.put(f"/api/tasks/{a}/dependencies/{b}", headers=head).status_code == 204
    assert client.delete(f"/api/tasks/{a}/dependencies/{b}", headers=head).status_code == 204
    for path in ("/api/tasks", f"/api/tasks/{a}", "/api/now", "/api/events", "/api/approvals"):
        assert client.get(path, headers=head).status_code == 200, path


# --- POST /api/events -----------------------------------------------------------------------


def event(actor, kind, task, **fields):
    return {"id": f"{kind}-{actor}", "at": AT, "actor": actor, "kind": kind,
            "subject": f"{kind} par {actor}", "task": task} | fields


def handoff(actor, task, to):
    return event(actor, "handoff", task, needs=[to], payload={"next_action": "à toi"})


@pytest.mark.parametrize("actor", sorted(ACTORS))
def test_the_event_actor_is_the_token_actor(client, actor):
    ref = create(client).json()["id"]
    other = "helios" if actor != "helios" else "mnema"
    res = client.post("/api/events", json=event(other, "progress", ref, payload={"percent": 5}),
                      headers=as_(client, actor))
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "actor_mismatch"
    assert other not in res.text
    assert client.get("/api/events", headers=as_(client, actor)).json() == []


@pytest.mark.parametrize("actor", sorted(ACTORS - HUMANS))
def test_claimed_makes_the_agent_lead(client, actor):
    ref = create(client).json()["id"]
    res = client.post("/api/events", json=event(actor, "claimed", ref), headers=as_(client, actor))
    assert res.status_code == 201, res.text
    assert res.json()["effects"] == [{"action": "lead_agent", "applied": True}]
    assert lead_of(client, ref) == actor


@pytest.mark.parametrize("actor", sorted(EXECUTORS))
@pytest.mark.parametrize("target", ["helios", "mnema", "aether", "artemis", "claude", "codex"])
def test_an_executor_handoff_to_another_agent_is_recorded_but_not_applied(client, actor, target):
    if target == actor:
        return
    ref = create(client, "loic", lead_agent=actor).json()["id"]
    res = client.post("/api/events", json=handoff(actor, ref, target), headers=as_(client, actor))
    assert res.status_code == 201, res.text
    [effect] = res.json()["effects"]
    assert effect["action"] == "handoff" and effect["applied"] is False
    assert "lead_agent" in effect["reason"] and target not in effect["reason"]
    assert lead_of(client, ref) == actor
    assert client.get(f"/api/events/{res.json()['id']}").json()["kind"] == "handoff"


@pytest.mark.parametrize("actor", sorted(EXECUTORS))
def test_an_executor_handoff_to_a_human_is_applied(client, actor):
    ref = create(client, "loic", lead_agent=actor).json()["id"]
    res = client.post("/api/events", json=handoff(actor, ref, "loic"), headers=as_(client, actor))
    assert res.status_code == 201, res.text
    assert res.json()["effects"] == [{"action": "handoff", "applied": True}]
    assert lead_of(client, ref) == "loic"


def next_action_of(client, ref):
    return client.get(f"/api/tasks/{ref}").json()["next_action"]


@pytest.mark.parametrize("actor", sorted(EXECUTORS))
def test_an_executor_handoff_back_to_the_current_lead_changes_only_the_next_action(client, actor):
    lead = "codex" if actor != "codex" else "claude"
    ref = create(client, "loic", lead_agent=lead, collaborators=[actor]).json()["id"]
    res = client.post("/api/events", json=handoff(actor, ref, lead), headers=as_(client, actor))
    assert res.status_code == 201, res.text
    assert res.json()["effects"] == [{"action": "handoff", "applied": True}]
    assert lead_of(client, ref) == lead
    assert next_action_of(client, ref) == "à toi"


@pytest.mark.parametrize("actor", sorted(EXECUTORS))
def test_an_executor_handoff_to_the_current_lead_that_changes_nothing_is_not_applied(
    client, actor
):
    lead = "codex" if actor != "codex" else "claude"
    ref = create(client, "loic", lead_agent=lead, next_action="à toi").json()["id"]
    res = client.post("/api/events", json=handoff(actor, ref, lead), headers=as_(client, actor))
    assert res.status_code == 201, res.text
    [effect] = res.json()["effects"]
    assert effect["action"] == "handoff" and effect["applied"] is False and effect["reason"]
    assert lead_of(client, ref) == lead and next_action_of(client, ref) == "à toi"


@pytest.mark.parametrize("actor", sorted(EXECUTORS))
def test_an_executor_already_lead_changes_its_next_action_by_patch_not_handoff(client, actor):
    ref = create(client, "loic", lead_agent=actor).json()["id"]
    res = client.post("/api/events", json=handoff(actor, ref, actor), headers=as_(client, actor))
    assert res.status_code == 409 and res.json()["detail"]["code"] == "handoff_to_self"
    assert client.get("/api/events", headers=as_(client, actor)).json() == []
    res = client.patch(f"/api/tasks/{ref}", json={"next_action": "relire"},
                       headers=as_(client, actor))
    assert res.status_code == 200, res.text
    assert lead_of(client, ref) == actor and next_action_of(client, ref) == "relire"


@pytest.mark.parametrize("actor", sorted(ACTORS - EXECUTORS - HUMANS))
@pytest.mark.parametrize("target", ["claude", "codex", "aether", "loic"])
def test_a_node_agent_handoff_is_applied(client, actor, target):
    if target == actor:
        return
    ref = create(client, "loic", lead_agent=actor).json()["id"]
    res = client.post("/api/events", json=handoff(actor, ref, target), headers=as_(client, actor))
    assert res.json()["effects"] == [{"action": "handoff", "applied": True}]
    assert lead_of(client, ref) == target


# --- Approbations : inchangé (ADR-019) ---------------------------------------------------------


@pytest.mark.parametrize("actor", sorted(ACTORS - HUMANS))
def test_an_agent_answering_or_deciding_an_approval_still_gets_409(client, actor):
    asked = client.post("/api/events", json={
        "id": "q1", "at": AT, "actor": "mnema", "kind": "question", "subject": "Version ?",
        "needs": ["loic"],
    })
    needs = client.post("/api/events", json={
        "id": "n1", "at": AT, "actor": "mnema", "kind": "needs_human", "subject": "Publier ?",
        "needs": ["loic"], "payload": {"options": ["oui", "non"], "consequence": "Publie"},
    })
    head = as_(client, actor)
    # Contract of ADR-019, unchanged: the author of the request is told so, others are not the
    # addressee.
    expected = "self_decision" if actor == "mnema" else "not_addressee"
    res = client.post(f"/api/approvals/{asked.json()['effects'][0]['approval']}/answer",
                      json={"text": "oui"}, headers=head)
    assert res.status_code == 409 and res.json()["detail"]["code"] == expected, res.text
    res = client.post(f"/api/approvals/{needs.json()['effects'][0]['approval']}/decision",
                      json={"decision": "approved"}, headers=head)
    assert res.status_code == 409 and res.json()["detail"]["code"] == expected, res.text


def test_nothing_in_the_database_changes_on_a_403(client):
    create(client, "codex", lead_agent="helios")
    with client.app.state.sessionmaker() as s:
        assert s.query(Task).count() == 0
