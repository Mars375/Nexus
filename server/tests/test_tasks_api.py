import socket
from datetime import datetime

import pytest


def create(client, **fields):
    body = {"title": "Pont lecture", "objective": "Lire les runs Hermes"} | fields
    res = client.post("/api/tasks", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def move(client, ref, status, **fields):
    return client.post(f"/api/tasks/{ref}/status", json={"status": status} | fields)


def violation(res):
    assert res.status_code == 409, res.text
    return res.json()["detail"]["code"]


def test_create_returns_task_with_nexus_id_and_provenance(client):
    task = create(client, next_action="relever les tables", status="todo", lead_agent="helios")

    assert task["id"].startswith("nx-task-")
    assert task["status"] == "todo"
    assert task["human_owner"] == "loic"
    assert task["created_by"] == "loic"
    assert task["source"] == "nexus.db"
    assert datetime.fromisoformat(task["measured_at"]).tzinfo is not None


def test_create_refuses_active_task_without_next_action(client):
    res = client.post("/api/tasks", json={"title": "x", "objective": "y", "status": "todo"})
    assert violation(res) == "next_action_required"


def test_create_refuses_to_start_beyond_todo(client):
    res = client.post(
        "/api/tasks", json={"title": "x", "objective": "y", "status": "in_progress"}
    )
    assert res.status_code == 422


def test_unknown_actor_is_refused(client):
    res = client.post(
        "/api/tasks", json={"title": "x", "objective": "y"}, headers={"X-Nexus-Actor": "mallory"}
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "actor_mismatch"


def test_actor_header_is_recorded(client):
    task = create(client)
    res = client.post(
        f"/api/tasks/{task['id']}/comments", json={"body": "je regarde"},
        headers={"X-Nexus-Actor": "helios"},
    )
    assert res.json()["author"] == "helios"


def test_read_accepts_short_and_long_ids_and_404s(client):
    task = create(client)
    short = task["id"].removeprefix("nx-task-")

    assert client.get(f"/api/tasks/{short}").json()["id"] == task["id"]
    assert client.get("/api/tasks/nx-task-999").status_code == 404
    assert client.get("/api/tasks/nimporte").status_code == 404


def test_full_lifecycle_through_status_route(client):
    ref = create(client)["id"]

    assert move(client, ref, "todo", next_action="relever les tables").status_code == 200
    started = move(client, ref, "in_progress").json()
    assert started["status"] == "in_progress"
    assert started["operation_role"] == "main"

    blocked = move(client, ref, "blocked", block_cause="SSH timeout", block_plan="rallumer")
    assert blocked.json()["block_cause"] == "SSH timeout"
    resumed = move(client, ref, "in_progress").json()
    assert resumed["block_cause"] is None

    assert move(client, ref, "done").json()["status"] == "done"


def test_refused_transition_is_explained(client):
    ref = create(client)["id"]
    assert violation(move(client, ref, "review")) == "transition_refused"


def test_blocked_requires_cause_and_follow_up(client):
    ref = create(client, next_action="x")["id"]
    move(client, ref, "in_progress")

    assert violation(move(client, ref, "blocked")) == "block_cause_required"
    assert violation(move(client, ref, "blocked", block_cause="SSH")) == "block_follow_up_required"
    ok = move(client, ref, "blocked", block_cause="SSH", follow_up_at="2026-09-29T09:00:00+02:00")
    assert ok.status_code == 200


def test_dropped_requires_reason(client):
    ref = create(client)["id"]
    assert violation(move(client, ref, "dropped")) == "drop_reason_required"
    assert move(client, ref, "dropped", reason="doublon").json()["drop_reason"] == "doublon"


def test_done_without_expected_evidence_goes_to_review(client):
    ref = create(client, next_action="x", expected_evidence="commit + tests verts")["id"]
    move(client, ref, "in_progress")

    closed = move(client, ref, "done").json()
    assert closed["status"] == "review"

    assert violation(move(client, ref, "done")) == "evidence_required"
    done = move(client, ref, "done", evidence=["commit:a1b2c3d"]).json()
    assert done["status"] == "done"
    assert done["evidence"] == ["commit:a1b2c3d"]


def test_only_one_main_operation_in_progress(client):
    first = create(client, next_action="x")["id"]
    second = create(client, next_action="y")["id"]
    move(client, first, "in_progress")

    assert move(client, second, "in_progress").json()["operation_role"] == "auxiliary"
    move(client, second, "todo")
    assert violation(move(client, second, "in_progress", role="main")) == "main_operation_taken"


def test_promoting_auxiliary_to_main_is_checked(client):
    first = create(client, next_action="x")["id"]
    second = create(client, next_action="y")["id"]
    move(client, first, "in_progress")
    move(client, second, "in_progress")

    res = client.patch(f"/api/tasks/{second}", json={"operation_role": "main"})
    assert violation(res) == "main_operation_taken"


def test_patch_cannot_empty_next_action_of_active_task(client):
    ref = create(client, status="todo", next_action="x")["id"]
    res = client.patch(f"/api/tasks/{ref}", json={"next_action": ""})
    assert violation(res) == "next_action_required"


def test_patch_cannot_null_required_fields(client):
    ref = create(client)["id"]
    assert client.patch(f"/api/tasks/{ref}", json={"title": None}).status_code == 422


def test_assign_via_patch(client):
    ref = create(client)["id"]
    task = client.patch(
        f"/api/tasks/{ref}", json={"lead_agent": "codex", "collaborators": ["helios"]}
    ).json()
    assert task["lead_agent"] == "codex"
    assert task["collaborators"] == ["helios"]


def test_list_filters(client):
    a = create(client, lead_agent="helios", priority="high", due_at="2026-10-01T12:00:00+02:00")
    b = create(client, collaborators=["helios"], status="todo", next_action="x")
    create(client, lead_agent="codex")

    ids = lambda res: {t["id"] for t in res.json()}  # noqa: E731
    assert ids(client.get("/api/tasks", params={"agent": "helios"})) == {a["id"], b["id"]}
    assert ids(client.get("/api/tasks", params={"status": "todo"})) == {b["id"]}
    assert ids(client.get("/api/tasks", params={"priority": "high"})) == {a["id"]}
    due = client.get("/api/tasks", params={"due_before": "2026-10-02T00:00:00+02:00"})
    assert ids(due) == {a["id"]}


def test_dependencies_and_cycles(client):
    a, b, c = (create(client)["id"] for _ in range(3))

    assert client.put(f"/api/tasks/{a}/dependencies/{b}").status_code == 204
    assert client.put(f"/api/tasks/{b}/dependencies/{c}").status_code == 204
    assert client.get(f"/api/tasks/{a}").json()["depends_on"] == [b]

    assert violation(client.put(f"/api/tasks/{c}/dependencies/{a}")) == "dependency_cycle"
    assert violation(client.put(f"/api/tasks/{a}/dependencies/{a}")) == "self_dependency"

    assert client.delete(f"/api/tasks/{a}/dependencies/{b}").status_code == 204
    assert client.delete(f"/api/tasks/{a}/dependencies/{b}").status_code == 404


def test_every_mutation_is_in_history(client):
    ref = create(client, next_action="x")["id"]
    other = create(client)["id"]
    move(client, other, "dropped", reason="traitée")  # dépendance déjà traitée
    client.patch(f"/api/tasks/{ref}", json={"priority": "high"})
    move(client, ref, "in_progress")
    client.post(f"/api/tasks/{ref}/comments", json={"body": "note"})
    assert client.put(f"/api/tasks/{ref}/dependencies/{other}").status_code == 204

    history = client.get(f"/api/tasks/{ref}/history").json()

    assert [h["action"] for h in history] == ["created", "updated", "status", "commented", "linked"]
    assert history[1]["changes"]["priority"] == ["normal", "high"]
    assert history[2]["changes"]["status"] == ["backlog", "in_progress"]
    assert all(h["actor"] == "loic" for h in history)


def test_no_route_opens_a_network_connection(client, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("appel réseau sortant interdit")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)

    ref = create(client, next_action="x")["id"]
    other = create(client)["id"]
    client.patch(f"/api/tasks/{ref}", json={"lead_agent": "hermes"})
    move(client, ref, "in_progress")
    move(client, ref, "blocked", block_cause="c", block_plan="p")
    move(client, ref, "in_progress")
    client.post(f"/api/tasks/{ref}/comments", json={"body": "b"})
    client.put(f"/api/tasks/{ref}/dependencies/{other}")
    move(client, ref, "done")
    client.get("/api/tasks")


SECRET = "ghp_" + "A" * 36


def test_secrets_are_redacted_everywhere_and_traced(client):
    task = create(client, objective=f"utiliser {SECRET}", context=[f"token={SECRET}"])
    ref = task["id"]
    client.patch(f"/api/tasks/{ref}", json={"origin": f"collé : {SECRET}"})
    client.post(f"/api/tasks/{ref}/comments", json={"body": f"mot de passe : {SECRET}"})
    move(client, ref, "dropped", reason=f"clé {SECRET} révoquée")

    everything = client.get(f"/api/tasks/{ref}").text
    everything += client.get(f"/api/tasks/{ref}/comments").text
    history = client.get(f"/api/tasks/{ref}/history")
    everything += history.text

    assert SECRET not in everything
    assert "[REDACTED]" in everything
    traced = [h for h in history.json() if h["action"] == "secret_redacted"]
    assert len(traced) == 4
    assert traced[0]["changes"] == {"fields": ["context", "objective"], "kinds": ["github_token"]}


def test_validation_errors_never_echo_the_input(client):
    too_long = SECRET + "x" * 300
    res = client.post("/api/tasks", json={"title": too_long, "objective": "o"})

    assert res.status_code == 422
    assert SECRET not in res.text
    assert res.json()["detail"][0]["loc"] == ["body", "title"]


def test_secret_only_workflow_text_does_not_count(client):
    res = client.post(
        "/api/tasks", json={"title": "t", "objective": "o", "status": "todo", "next_action": SECRET}
    )
    assert violation(res) == "next_action_required"

    ref = create(client, next_action="x")["id"]
    move(client, ref, "in_progress")
    assert violation(move(client, ref, "blocked", block_cause=SECRET, block_plan="p")) == (
        "block_cause_required"
    )
    assert violation(move(client, ref, "dropped", reason=f"token={SECRET}")) == (
        "drop_reason_required"
    )


def test_secret_repasted_into_masked_field_is_still_traced(client):
    ref = create(client, origin=f"collé : {SECRET}")["id"]
    other = "ghp_" + "C" * 36
    client.patch(f"/api/tasks/{ref}", json={"origin": f"collé : {other}"})  # même valeur masquée

    history = client.get(f"/api/tasks/{ref}/history").json()
    assert other not in str(history)
    assert [h["action"] for h in history].count("secret_redacted") == 2
    assert [h["action"] for h in history].count("updated") == 0


def test_database_enforces_one_main_operation_under_concurrency(client):
    from sqlalchemy.exc import IntegrityError

    from nexus.tasks import service

    a = int(create(client, status="todo", next_action="x")["id"].removeprefix("nx-task-"))
    b = int(create(client, status="todo", next_action="y")["id"].removeprefix("nx-task-"))
    make = client.app.state.sessionmaker
    with make() as s1, make() as s2:
        # Les deux lisent « aucune autre principale en cours » avant que l'une n'écrive.
        service.change_status(s1, service.get_task(s1, a), "in_progress", "loic")
        service.change_status(s2, service.get_task(s2, b), "in_progress", "loic")
        s1.commit()
        with pytest.raises(IntegrityError):
            s2.commit()


@pytest.mark.parametrize("field", ["title", "objective"])
def test_whitespace_only_title_or_objective_is_refused(client, field):
    body = {"title": "Pont lecture", "objective": "Lire les runs"} | {field: "   "}
    assert client.post("/api/tasks", json=body).status_code == 422

    ref = create(client)["id"]
    assert client.patch(f"/api/tasks/{ref}", json={field: "   "}).status_code == 422


def test_title_is_stored_trimmed(client):
    assert create(client, title="  Pont lecture  ")["title"] == "Pont lecture"


def test_redacted_evidence_is_not_proof(client):
    ref = create(client, next_action="x", expected_evidence="commit")["id"]
    move(client, ref, "in_progress")

    closed = move(client, ref, "done", evidence=[SECRET]).json()

    assert closed["status"] == "review"
    assert closed["evidence"] == []


def test_blank_evidence_is_refused(client):
    ref = create(client, next_action="x", expected_evidence="commit")["id"]
    move(client, ref, "in_progress")

    assert move(client, ref, "done", evidence=["   "]).status_code == 422
    assert move(client, ref, "done", evidence=[""]).status_code == 422


def test_patch_cannot_break_a_block(client):
    ref = create(client, next_action="x")["id"]
    move(client, ref, "in_progress")
    move(client, ref, "blocked", block_cause="SSH", follow_up_at="2026-09-29T09:00:00+02:00")

    res = client.patch(f"/api/tasks/{ref}", json={"follow_up_at": None})
    assert violation(res) == "block_follow_up_required"


def test_prepared_role_is_honoured_at_start(client):
    aux = create(client, next_action="x", operation_role="auxiliary")["id"]
    assert move(client, aux, "in_progress").json()["operation_role"] == "auxiliary"

    main = create(client, next_action="y", operation_role="main")["id"]
    other = create(client, next_action="z", operation_role="main")["id"]
    assert move(client, main, "in_progress").json()["operation_role"] == "main"
    assert violation(move(client, other, "in_progress")) == "main_operation_taken"


def test_expected_evidence_cannot_be_added_to_a_task_done_without_proof(client):
    ref = create(client, next_action="x")["id"]
    move(client, ref, "in_progress")
    move(client, ref, "done")

    res = client.patch(f"/api/tasks/{ref}", json={"expected_evidence": "commit"})
    assert violation(res) == "task_done"
    assert client.get(f"/api/tasks/{ref}").json()["expected_evidence"] is None


def test_history_records_the_role_actually_stored(client):
    ref = create(client, next_action="x")["id"]
    move(client, ref, "in_progress")  # devient main

    client.patch(f"/api/tasks/{ref}", json={"operation_role": None})  # redéduit : reste main
    client.patch(f"/api/tasks/{ref}", json={"operation_role": "auxiliary"})

    history = client.get(f"/api/tasks/{ref}/history").json()
    updates = [h for h in history if h["action"] == "updated"]
    assert [u["changes"] for u in updates] == [{"operation_role": ["main", "auxiliary"]}]


def test_role_is_cleared_when_leaving_progress(client):
    ref = create(client, next_action="x")["id"]
    move(client, ref, "in_progress")
    assert move(client, ref, "todo").json()["operation_role"] is None


def test_dependencies_gate_progress_until_resolved(client):
    a = create(client, next_action="x")["id"]
    b = create(client, next_action="y")["id"]
    client.put(f"/api/tasks/{a}/dependencies/{b}")

    res = move(client, a, "in_progress")
    assert violation(res) == "dependencies_pending"
    assert b in res.json()["detail"]["message"]
    assert move(client, a, "todo").status_code == 200  # préparer reste permis

    move(client, b, "in_progress")
    move(client, b, "done")
    assert move(client, a, "in_progress").status_code == 200


def test_advanced_task_cannot_depend_on_unresolved_task(client):
    advanced = create(client, next_action="x")["id"]
    move(client, advanced, "in_progress")
    pending = create(client)["id"]
    finished = create(client, next_action="y")["id"]
    move(client, finished, "in_progress")
    move(client, finished, "done")

    res = client.put(f"/api/tasks/{advanced}/dependencies/{pending}")
    assert violation(res) == "dependency_on_advanced_task"
    assert client.put(f"/api/tasks/{advanced}/dependencies/{finished}").status_code == 204
    # A closed task takes no new link at all, resolved prerequisite or not.
    move(client, advanced, "done")
    res = client.put(f"/api/tasks/{advanced}/dependencies/{pending}")
    assert violation(res) == "task_done"


def test_prerequisite_cannot_be_reopened_under_an_advanced_dependent(client):
    # A done prerequisite is final; only a dropped one can be taken back (dropped -> backlog).
    prereq = create(client, next_action="x")["id"]
    dependent = create(client, next_action="y")["id"]
    client.put(f"/api/tasks/{dependent}/dependencies/{prereq}")
    move(client, prereq, "dropped", reason="abandonné")
    move(client, dependent, "in_progress")

    res = move(client, prereq, "backlog")
    assert violation(res) == "reopen_with_advanced_dependents"
    assert dependent in res.json()["detail"]["message"]

    move(client, dependent, "todo")  # la dépendante recule : reprise permise
    assert move(client, prereq, "backlog").status_code == 200


def test_dropped_dependency_counts_as_resolved(client):
    a = create(client, next_action="x")["id"]
    b = create(client)["id"]
    client.put(f"/api/tasks/{a}/dependencies/{b}")
    move(client, b, "dropped", reason="abandonné")

    assert move(client, a, "in_progress").status_code == 200


@pytest.mark.parametrize("path", ["/api/tasks/nx-task-1/history", "/api/tasks/nx-task-1/comments"])
def test_sub_resources_404_on_unknown_task(client, path):
    assert client.get(path).status_code == 404


def test_unknown_actor_value_is_never_echoed(client):
    res = client.post(
        "/api/tasks", json={"title": "x", "objective": "y"}, headers={"X-Nexus-Actor": SECRET}
    )
    assert res.status_code == 403
    assert SECRET not in res.text


@pytest.mark.parametrize("ref", [SECRET, "²", "9" * 5000, "nx-task-" + "1" * 40])
def test_invalid_task_reference_is_404_and_never_echoed(client, ref):
    res = client.get(f"/api/tasks/{ref}")
    assert res.status_code == 404
    assert ref not in res.text


def test_validation_errors_are_in_french(client):
    res = client.post("/api/tasks", json={"title": "x" * 300, "priority": "urgent"})

    messages = {e["loc"][-1]: e["msg"] for e in res.json()["detail"]}
    assert messages["title"] == "title : trop long (au plus 200 caractères)"
    assert messages["objective"] == "objective : champ obligatoire"
    assert messages["priority"].startswith("priority : valeur non autorisée")


@pytest.mark.parametrize("field", ["title", "objective"])
def test_secret_only_title_or_objective_is_refused(client, field):
    body = {"title": "Pont lecture", "objective": "Lire les runs"} | {field: SECRET}
    assert violation(client.post("/api/tasks", json=body)) == f"{field}_required"

    ref = create(client)["id"]
    assert violation(client.patch(f"/api/tasks/{ref}", json={field: SECRET})) == f"{field}_required"


def test_comment_and_history_carry_measured_at(client):
    ref = create(client)["id"]
    client.post(f"/api/tasks/{ref}/comments", json={"body": "note"})

    for path in ("comments", "history"):
        item = client.get(f"/api/tasks/{ref}/{path}").json()[0]
        assert item["source"] == "nexus.db"
        assert datetime.fromisoformat(item["measured_at"]).tzinfo is not None


def test_concurrent_transitions_on_the_same_task_cannot_both_win(client):
    from sqlalchemy.orm.exc import StaleDataError

    from nexus.tasks import service

    ref = create(client, next_action="x")["id"]
    move(client, ref, "in_progress")
    task_id = int(ref.removeprefix("nx-task-"))
    make = client.app.state.sessionmaker
    with make() as s1, make() as s2:
        # Les deux lisent in_progress, puis l'une clôt et l'autre bloque.
        service.change_status(s1, service.get_task(s1, task_id), "done", "loic")
        service.change_status(
            s2, service.get_task(s2, task_id), "blocked", "helios", block_cause="c", block_plan="p"
        )
        s1.commit()
        with pytest.raises(StaleDataError):
            s2.commit()

    assert client.get(f"/api/tasks/{ref}").json()["status"] == "done"
    statuses = [h["changes"]["status"] for h in client.get(f"/api/tasks/{ref}/history").json()
                if h["action"] == "status"]
    assert statuses == [["backlog", "in_progress"], ["in_progress", "done"]]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("patch", "", {"status": "done"}),
        ("post", "/status", {"status": "todo", "statut": "x"}),
        ("post", "/comments", {"body": "b", "auteur": "helios"}),
    ],
)
def test_unknown_fields_are_refused(client, method, path, body):
    ref = create(client, next_action="x")["id"]
    res = getattr(client, method)(f"/api/tasks/{ref}{path}", json=body)

    assert res.status_code == 422
    assert "champ inconnu" in res.text
    assert client.get(f"/api/tasks/{ref}").json()["status"] == "backlog"


def test_unknown_field_on_create_is_refused(client):
    res = client.post("/api/tasks", json={"title": "t", "objective": "o", "statut": "todo"})
    assert res.status_code == 422


# --- POST /status: fields that do not apply to the target ------------------------------------


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("backlog", "evidence", ["commit:a1b2c3d"]),
        ("todo", "role", "main"),
        ("in_progress", "block_cause", "c"),
        ("in_progress", "follow_up_at", "2026-11-01T09:00:00+01:00"),
        ("blocked", "reason", "motif"),
        ("blocked", "evidence", ["commit:a1b2c3d"]),
        ("review", "block_plan", "p"),
        ("done", "reason", "motif"),
        ("dropped", "block_plan", "p"),
    ],
)
def test_field_inapplicable_to_the_target_is_refused(client, target, field, value):
    ref = create(client, next_action="x")["id"]
    move(client, ref, "in_progress")

    res = move(client, ref, target, **{field: value})

    assert res.status_code == 422, res.text
    (error,) = res.json()["detail"]
    assert error["loc"] == ["body", field]
    assert error["msg"] == f"{field} : champ inapplicable au statut « {target} »"
    assert client.get(f"/api/tasks/{ref}").json()["status"] == "in_progress"


def test_every_inapplicable_field_is_named(client):
    ref = create(client, next_action="x")["id"]

    res = move(client, ref, "backlog", evidence=["commit:a1b2c3d"], block_cause="c", role="main")

    assert res.status_code == 422, res.text
    assert {error["loc"][-1] for error in res.json()["detail"]} == {
        "evidence",
        "block_cause",
        "role",
    }


def test_inapplicable_field_never_echoes_its_value(client):
    ref = create(client, next_action="x")["id"]

    res = move(client, ref, "todo", evidence=[f"token={SECRET}"])

    assert res.status_code == 422
    assert SECRET not in res.text


def test_a_provided_but_null_field_is_refused_too(client):
    ref = create(client, next_action="x")["id"]

    res = move(client, ref, "todo", evidence=None)

    assert res.status_code == 422, res.text
    assert res.json()["detail"][0]["loc"] == ["body", "evidence"]


def test_applicable_fields_are_accepted_per_target(client):
    ref = create(client, next_action="x")["id"]

    prepared = move(client, ref, "in_progress", role="main", next_action="suite")
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["operation_role"] == "main"
    blocked = move(
        client, ref, "blocked",
        block_cause="SSH", block_plan="clé", follow_up_at="2026-11-01T09:00:00+01:00",
    )
    assert blocked.status_code == 200, blocked.text
    assert move(client, ref, "in_progress").status_code == 200
    reviewed = move(client, ref, "review", evidence=["commit:a1b2c3d"])
    assert reviewed.json()["evidence"] == ["commit:a1b2c3d"]
    dropped = move(client, ref, "dropped", reason="doublon")
    assert dropped.json()["drop_reason"] == "doublon"


def test_secret_only_expected_evidence_is_cleared(client):
    task = create(client, next_action="x", expected_evidence=SECRET)
    assert task["expected_evidence"] is None

    move(client, task["id"], "in_progress")
    assert move(client, task["id"], "done").json()["status"] == "done"


@pytest.mark.parametrize("status", ["done", "dropped", "blocked", "review"])
def test_role_cannot_be_set_outside_preparation_or_progress(client, status):
    ref = create(client, next_action="x")["id"]
    move(client, ref, "in_progress")
    if status == "blocked":
        move(client, ref, "blocked", block_cause="c", block_plan="p")
    elif status == "dropped":
        move(client, ref, "dropped", reason="r")
    else:
        move(client, ref, status)

    res = client.patch(f"/api/tasks/{ref}", json={"operation_role": "main"})
    # A done task is final before the role is even judged.
    assert violation(res) == ("task_done" if status == "done" else "role_not_applicable")
    assert client.patch(f"/api/tasks/{ref}", json={"operation_role": None}).status_code == 200


def test_role_can_be_prepared_on_upcoming_task(client):
    ref = create(client, status="todo", next_action="x")["id"]
    res = client.patch(f"/api/tasks/{ref}", json={"operation_role": "auxiliary"})
    assert res.status_code == 200


def test_lone_surrogate_in_task_text_is_refused(client):
    raw = r'{"title": "x\ud800", "objective": "y"}'
    res = client.post("/api/tasks", content=raw, headers={"Content-Type": "application/json"})
    assert res.status_code == 422, res.text
    assert client.get("/api/tasks").status_code == 200


def test_evidence_reduced_to_a_label_is_not_proof(client):
    ref = create(client, status="todo", next_action="x", expected_evidence="le commit")["id"]
    move(client, ref, "in_progress")

    res = move(client, ref, "done", evidence=["commit: token=hunter2"])

    # Preuve ou review : sans identifiant, ce n'est pas une preuve, la tâche attend une relecture.
    assert res.status_code == 200, res.text
    assert "hunter2" not in res.text
    assert (res.json()["status"], res.json()["evidence"]) == ("review", [])
