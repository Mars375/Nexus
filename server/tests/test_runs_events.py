"""The `nx-run-` prefix is reserved: such a reference must be a run of the same task and signer."""

import pytest
from events_support import AT, publish, task
from runs_support import dispatch, make_task, register


def as_actor(client, actor, kind, ref, **fields):
    body = {"id": f"e-{actor}-{kind}-{fields.get('run', '')}", "at": AT, "actor": actor,
            "kind": kind, "subject": "s", "task": ref} | fields
    return client.post("/api/events", json=body)


def run_for(client, executor="codex", agent="codex"):
    register(client, executor)
    ref = make_task(client)
    res = dispatch(client, ref, executor=executor, agent=agent)
    assert res.status_code == 201, res.text
    return ref, res.json()["id"]


def test_the_signer_of_the_run_may_name_it(client):
    ref, run = run_for(client)

    res = as_actor(client, "codex", "working", ref, run=run)

    assert res.status_code == 201, res.text


def test_run_ref_in_the_payload_is_checked_too(client):
    ref, run = run_for(client)

    ok = as_actor(client, "codex", "working", ref, payload={"run_ref": run})
    other = make_task(client, title="Autre")
    bad = as_actor(client, "codex", "working", other, payload={"run_ref": run}, id="x2")

    assert ok.status_code == 201
    assert (bad.status_code, bad.json()["detail"]["code"]) == (409, "run_unknown")


@pytest.mark.parametrize("name", ["nx-run-999", "nx-run-abc", "nx-run-", "NX-RUN-1", " nx-run-1x"])
def test_an_unknown_run_is_refused(client, name):
    ref, _ = run_for(client)

    res = as_actor(client, "codex", "working", ref, run=name)

    assert (res.status_code, res.json()["detail"]["code"]) == (409, "run_unknown")
    assert name.strip().casefold() == "nx-run-" or name.strip() not in res.text


def test_another_task_is_refused(client):
    _, run = run_for(client)
    other = make_task(client, title="Autre")

    res = as_actor(client, "codex", "working", other, run=run)

    assert (res.status_code, res.json()["detail"]["code"]) == (409, "run_unknown")


def test_another_signer_is_refused(client):
    ref, run = run_for(client)

    res = as_actor(client, "helios", "working", ref, run=run)

    assert (res.status_code, res.json()["detail"]["code"]) == (409, "run_unknown")


def test_an_event_without_task_cannot_name_a_run(client):
    _, run = run_for(client)

    res = client.post("/api/events", json={
        "id": "e1", "at": AT, "actor": "codex", "kind": "question", "subject": "s",
        "needs": ["loic"], "run": run,
    })

    assert (res.status_code, res.json()["detail"]["code"]) == (409, "run_unknown")


def test_other_run_names_are_untouched(client):
    ref = task(client, next_action="x")

    assert publish(client, "working", "r", task=ref, run="r1").status_code == 201
    assert publish(client, "progress", "p", task=ref, run="nx-runner-1",
                   body="x").status_code == 201
