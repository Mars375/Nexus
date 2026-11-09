"""Runs API (ADR-023, lot B): who may dispatch, idempotence, pre-conditions, reads."""

from pathlib import Path

import pytest
from runs_support import code_of, dispatch, make_task, register

from nexus.actors import AGENTS


def test_an_agent_is_forbidden_on_every_write_route(client):
    register(client)
    task = make_task(client)
    run = dispatch(client, task).json()["id"]
    for actor in sorted(AGENTS):
        res = dispatch(client, task, actor=actor, client_key=f"k-{actor}")
        assert (res.status_code, code_of(res)) == (403, "human_only"), actor
        res = client.post(f"/api/runs/{run}/cancel", headers={"X-Nexus-Actor": actor})
        assert (res.status_code, code_of(res)) == (403, "human_only"), actor
    assert len(client.get(f"/api/tasks/{task}/runs").json()) == 1


def test_a_human_dispatch_creates_a_run_with_provenance(client):
    register(client)
    task = make_task(client)

    res = dispatch(client, task, workdir="F:/Projet/Nexus")

    assert res.status_code == 201
    body = res.json()
    assert body["id"] == "nx-run-1" and body["task"] == task
    assert (body["executor"], body["agent"], body["dispatched_by"]) == ("codex", "codex", "loic")
    assert (body["status"], body["version"]) == ("dispatched", 1)
    assert body["source"] == "nexus.db" and body["measured_at"]
    assert client.get("/api/runs/nx-run-1").json()["brief"] == "Fais le travail"


def test_a_double_click_is_one_row(client):
    register(client)
    task = make_task(client)

    first = dispatch(client, task)
    second = dispatch(client, task)

    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json() == second.json() | {"measured_at": first.json()["measured_at"]}
    assert len(client.get(f"/api/tasks/{task}/runs").json()) == 1


def test_the_same_client_key_for_another_request_is_refused(client):
    register(client)
    task = make_task(client)
    dispatch(client, task)

    res = dispatch(client, task, brief="Autre chose")

    assert (res.status_code, code_of(res)) == (409, "client_key_reused")


def test_a_secret_in_the_brief_is_masked_in_the_database(client):
    from nexus.models import Run

    register(client)
    task = make_task(client)
    secret = "ghp_" + "A" * 36

    res = dispatch(client, task, brief=f"Utilise {secret} pour pousser")

    assert res.status_code == 201
    assert secret not in res.text
    with client.app.state.sessionmaker() as session:
        assert secret not in session.get(Run, 1).brief
    assert "[REDACTED]" in client.get("/api/runs/nx-run-1").json()["brief"]


def test_a_secret_in_the_client_key_is_refused_without_echo(client):
    register(client)
    task = make_task(client)
    secret = "ghp_" + "B" * 36

    res = dispatch(client, task, client_key=secret)

    assert (res.status_code, code_of(res)) == (409, "secret_in_client_key")
    assert secret not in res.text


def test_a_brief_reduced_to_a_secret_is_refused(client):
    register(client)
    task = make_task(client)

    res = dispatch(client, task, brief="ghp_" + "C" * 36)

    assert (res.status_code, code_of(res)) == (409, "brief_required")


def test_no_adapter_is_executor_unavailable(client):
    task = make_task(client)

    res = dispatch(client, task)

    assert (res.status_code, code_of(res)) == (409, "executor_unavailable")
    assert client.get(f"/api/tasks/{task}/runs").json() == []


def test_an_unknown_executor_or_agent_is_a_422(client):
    register(client)
    task = make_task(client)
    assert dispatch(client, task, executor="nobody").status_code == 422
    assert dispatch(client, task, agent="nobody").status_code == 422
    assert dispatch(client, task, extra="x").status_code == 422


def test_a_done_task_is_refused(client):
    register(client)
    task = make_task(client)
    client.post(f"/api/tasks/{task}/status", json={"status": "in_progress"})
    client.post(f"/api/tasks/{task}/status", json={"status": "done"})
    assert client.get(f"/api/tasks/{task}").json()["status"] == "done"

    res = dispatch(client, task)

    assert (res.status_code, code_of(res)) == (409, "task_done")


def test_a_task_without_next_action_is_refused(client):
    register(client)
    task = make_task(client, next_action=None)

    res = dispatch(client, task)

    assert (res.status_code, code_of(res)) == (409, "next_action_required")


def test_a_pending_dependency_is_refused(client):
    register(client)
    task, blocker = make_task(client), make_task(client, title="Avant")
    res = client.put(f"/api/tasks/{task}/dependencies/{blocker}")
    assert res.status_code in (200, 204), res.text

    res = dispatch(client, task)

    assert (res.status_code, code_of(res)) == (409, "dependencies_pending")


def test_another_main_task_in_progress_is_refused(client):
    register(client)
    other = make_task(client, title="Autre")
    client.post(f"/api/tasks/{other}/status", json={"status": "in_progress", "role": "main"})
    task = make_task(client, operation_role="main")

    res = dispatch(client, task)

    assert (res.status_code, code_of(res)) == (409, "main_operation_taken")


def test_a_second_active_run_for_the_same_agent_is_refused(client):
    register(client)
    task = make_task(client)
    dispatch(client, task)

    res = dispatch(client, task, client_key="k2")

    assert (res.status_code, code_of(res)) == (409, "run_already_active")
    register(client, "hermes")
    other_agent = dispatch(client, task, client_key="k3", executor="hermes", agent="helios")
    assert other_agent.status_code == 201  # one active run per (task, agent), not per task


def test_a_missing_run_or_task_is_a_404(client):
    register(client)
    assert client.get("/api/runs/nx-run-999").status_code == 404
    assert client.get("/api/runs/nope").status_code == 404
    assert dispatch(client, "nx-task-999").status_code == 404
    assert client.get("/api/tasks/nx-task-999/runs").status_code == 404


def test_the_list_is_per_task_and_newest_first(client):
    register(client)
    register(client, "hermes")
    register(client, "claude")
    one, two = make_task(client), make_task(client)
    dispatch(client, one, client_key="a")
    dispatch(client, one, client_key="b", executor="hermes", agent="helios")
    dispatch(client, two, client_key="c", executor="claude", agent="claude")

    listed = client.get(f"/api/tasks/{one}/runs").json()

    assert [r["id"] for r in listed] == ["nx-run-2", "nx-run-1"]


@pytest.mark.parametrize("status", ["done", "failed", "cancelled", "review", "blocked"])
def test_cancelling_a_settled_run_is_refused(client, status):
    from nexus.models import Run

    register(client)
    run = dispatch(client, make_task(client)).json()["id"]
    with client.app.state.sessionmaker() as session:
        session.get(Run, 1).status = status
        session.commit()

    res = client.post(f"/api/runs/{run}/cancel")

    assert (res.status_code, code_of(res)) == (409, "run_not_cancellable")


def test_a_cancel_request_is_recorded_and_idempotent(client):
    register(client)
    run = dispatch(client, make_task(client)).json()["id"]

    first = client.post(f"/api/runs/{run}/cancel")
    second = client.post(f"/api/runs/{run}/cancel")

    assert first.status_code == 200 and first.json()["cancel_requested_at"]
    assert second.json()["cancel_requested_at"] == first.json()["cancel_requested_at"]
    assert second.json()["version"] == first.json()["version"]


def test_executors_lists_only_the_registered_ones_with_their_agents_and_workdirs(client):
    assert client.get("/api/executors").json() == []
    adapter = register(client)
    adapter.workdirs = [Path("F:/Projet/Nexus-test")]

    [codex] = client.get("/api/executors").json()

    assert codex["executor"] == "codex" and codex["agents"] == ["codex"]
    assert codex["workdirs"] == [str(Path("F:/Projet/Nexus-test"))]
    assert codex["source"] == "nexus.db" and codex["measured_at"]
    register(client, "hermes")
    names = {e["executor"]: e["agents"] for e in client.get("/api/executors").json()}
    assert names["hermes"] == ["aether", "helios", "mnema"]
