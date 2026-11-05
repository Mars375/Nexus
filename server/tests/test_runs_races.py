"""Races on runs: simultaneous dispatches and the version lock against a finish."""

import threading

import pytest
from runs_support import code_of, dispatch, make_task, register
from sqlalchemy.orm.exc import StaleDataError

from nexus.models import Run
from nexus.runs import service


def race(calls):
    """Run each call in its own thread, released together; returns the results in order."""
    barrier = threading.Barrier(len(calls))
    out = [None] * len(calls)

    def work(i):
        barrier.wait()
        out[i] = calls[i]()

    threads = [threading.Thread(target=work, args=(i,)) for i in range(len(calls))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return out


def test_two_simultaneous_dispatches_leave_one_active_run(client):
    register(client)
    task = make_task(client)
    client.token_for("loic")

    results = race([
        lambda: dispatch(client, task, client_key="a"),
        lambda: dispatch(client, task, client_key="b"),
    ])

    assert sorted(r.status_code for r in results) == [201, 409]
    loser = next(r for r in results if r.status_code == 409)
    assert code_of(loser) == "run_already_active"
    assert len(client.get(f"/api/tasks/{task}/runs").json()) == 1


def test_simultaneous_clicks_with_the_same_key_are_one_row(client):
    register(client)
    task = make_task(client)
    client.token_for("loic")

    results = race([lambda: dispatch(client, task) for _ in range(3)])

    assert sorted(r.status_code for r in results) == [200, 200, 201]
    assert len({r.json()["id"] for r in results}) == 1
    assert len(client.get(f"/api/tasks/{task}/runs").json()) == 1


def test_a_cancel_loaded_before_a_finish_loses(client):
    register(client)
    dispatch(client, make_task(client))
    make = client.app.state.sessionmaker
    with make() as canceller, make() as finisher:
        stale = canceller.get(Run, 1)
        done = finisher.get(Run, 1)
        service.update_run(finisher, done, status="done")
        finisher.commit()

        with pytest.raises(StaleDataError):
            service.request_cancel(canceller, stale, "loic")
    with make() as session:
        assert session.get(Run, 1).status == "done"
        assert session.get(Run, 1).cancel_requested_at is None


def test_a_finish_loaded_before_a_cancel_loses(client):
    register(client)
    dispatch(client, make_task(client))
    make = client.app.state.sessionmaker
    with make() as canceller, make() as finisher:
        done = finisher.get(Run, 1)
        stale = canceller.get(Run, 1)
        service.request_cancel(canceller, stale, "loic")
        canceller.commit()

        with pytest.raises(StaleDataError):
            service.update_run(finisher, done, status="done")
