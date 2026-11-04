"""A done task is final for the example agent (ADR-022)."""

import demo_agent_support
import pytest
from demo_agent_support import run

from nexus import demo_agent

_no_developer_token = demo_agent_support._no_developer_token
http = demo_agent_support.http
task = demo_agent_support.task


# --- A done task is final (ADR-022) ---------------------------------------------------------


@pytest.fixture
def calls(monkeypatch):
    seen = []
    real = demo_agent.call

    def recording(base, method, path, body=None):
        seen.append((method, path))
        return real(base, method, path, body)

    monkeypatch.setattr(demo_agent, "call", recording)
    return seen


def test_a_rerun_on_a_done_task_stops_with_exit_4_and_publishes_nothing(
    http, task, calls, capsys
):
    # (This one keeps a next action; the empty case is the next test.)
    http.patch(f"/api/tasks/{task}", json={"next_action": "Garder celle-ci"})
    http.post(f"/api/tasks/{task}/status", json={"status": "in_progress"})
    http.post(f"/api/tasks/{task}/status", json={"status": "done", "evidence": ["commit:abc"]})
    before = http.get(f"/api/tasks/{task}").json() | {"measured_at": None}
    calls.clear()

    code = run(task, "--evidence", "commit:def")

    assert code == demo_agent.EXIT_EFFECT_REFUSED == 4
    out = capsys.readouterr().out
    assert "tâche terminée : elle ne se modifie plus" in out and "rien n'est publié" in out
    assert calls == [("GET", f"/api/tasks/{task}")]  # no PATCH, no event
    assert http.get("/api/events").json() == []
    assert http.get(f"/api/tasks/{task}").json() | {"measured_at": None} == before


@pytest.mark.parametrize(("closing", "stored"), [
    ("commit:a1b2c3d", ["commit:a1b2c3d"]),
    ("commit:other", ["commit:other", "commit:a1b2c3d"]),
])
def test_a_done_after_loic_closed_the_task_is_exit_0_whatever_the_evidence(
    http, task, monkeypatch, closing, stored
):
    """Two effects, never one: `status:done` « déjà en done », then `evidence` on its own."""
    real = demo_agent.publish

    def publish(base, actor, ref, kind, subject, **fields):
        if kind == "done":  # Loïc closes the task just before the agent's done
            http.post(f"/api/tasks/{ref}/status", json={"status": "done", "evidence": [closing]})
        return real(base, actor, ref, kind, subject, **fields)

    monkeypatch.setattr(demo_agent, "publish", publish)

    assert run(task, "--evidence", "commit:a1b2c3d") == 0

    done = http.get("/api/events", params={"kind": "done"}).json()[0]
    assert [e["action"] for e in done["effects"]] == ["status:done", "evidence"]
    assert done["effects"][0]["reason"] == "déjà en done"
    assert done["effects"][1]["applied"] is (closing != "commit:a1b2c3d")
    assert http.get(f"/api/tasks/{task}").json()["evidence"] == stored


def test_a_done_task_may_have_an_empty_next_action_and_the_agent_still_publishes_nothing(
    http, task, calls, capsys
):
    # Reachable: only an active status requires a next action, and `done` is not one, so
    # `POST …/status` can clear it while closing.
    http.post(f"/api/tasks/{task}/status", json={"status": "in_progress", "next_action": "x"})
    res = http.post(f"/api/tasks/{task}/status",
                    json={"status": "done", "evidence": ["commit:abc"], "next_action": ""})
    assert res.status_code == 200 and res.json()["next_action"] == "", res.text
    before = http.get(f"/api/tasks/{task}").json() | {"measured_at": None}
    calls.clear()

    code = run(task, "--evidence", "commit:def")

    assert code == demo_agent.EXIT_EFFECT_REFUSED == 4  # not 1: no PATCH next_action is sent
    assert "rien n'est publié" in capsys.readouterr().out
    assert calls == [("GET", f"/api/tasks/{task}")]
    assert http.get("/api/events").json() == []
    assert http.get(f"/api/tasks/{task}").json() | {"measured_at": None} == before
