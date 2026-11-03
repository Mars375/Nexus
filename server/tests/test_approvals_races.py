"""Races on the approval row: retries, one transaction, concurrent decisions (#26, PR 2)."""

import threading

import pytest
from approvals_support import REF, answer, answer_events, ask, code_of, decide, untouched

from nexus.approvals import service as approvals
from nexus.events import service as events
from nexus.models import Approval

# --- Races --------------------------------------------------------------------------------


def race_hook(monkeypatch, competitor):
    """Run `competitor()` between the approval's fresh read and the answer event's write."""
    real = events.publish

    def racing(*args, **kwargs):
        monkeypatch.setattr(events, "publish", real)  # only the first call races
        competitor()
        return real(*args, **kwargs)

    monkeypatch.setattr(events, "publish", racing)


def test_a_different_decision_that_wins_the_race_makes_this_one_a_409(client, monkeypatch):
    ask(client, kind="needs_human")
    race_hook(monkeypatch, lambda: decide(client, decision="rejected"))

    res = decide(client, decision="approved", choice=0)

    assert code_of(res) == "approval_already_decided"
    assert res.json()["detail"]["message"].startswith("déjà refusée par loic le ")
    [only] = answer_events(client)
    assert only["payload"]["decision"] == "rejected"
    assert client.get(f"/api/approvals/{REF}").json()["status"] == "rejected"


def test_an_identical_decision_that_wins_the_race_is_replayed_as_a_200(client, monkeypatch):
    ask(client, kind="needs_human")
    race_hook(monkeypatch, lambda: decide(client, decision="approved", choice=1))

    res = decide(client, decision="approved", choice=1)

    assert res.status_code == 200 and res.json()["status"] == "approved"
    assert len(answer_events(client)) == 1


def test_a_concurrent_write_on_the_approval_row_is_retried_not_lost(client, monkeypatch):
    # Another writer bumps the row version between our read and our write: StaleDataError.
    ask(client)
    from sqlalchemy import update

    def bump():
        with client.app.state.sessionmaker() as other:
            other.execute(update(Approval).values(version=Approval.version + 1))
            other.commit()

    race_hook(monkeypatch, bump)

    res = answer(client)

    assert res.status_code == 200 and res.json()["status"] == "answered"
    assert len(answer_events(client)) == 1
    assert "tâche" not in res.text  # not the generic « la tâche vient d'être modifiée »


def test_a_stale_row_that_never_settles_is_a_clean_409(client, monkeypatch):
    ask(client)
    from sqlalchemy import update

    def bump_always(*args, **kwargs):
        with client.app.state.sessionmaker() as other:
            other.execute(update(Approval).values(version=Approval.version + 1))
            other.commit()
        return real(*args, **kwargs)

    real = events.publish
    monkeypatch.setattr(events, "publish", bump_always)

    res = answer(client)

    assert code_of(res) == "approval_concurrent_update"
    assert "tâche" not in res.json()["detail"]["message"]
    assert answer_events(client) == []


def test_the_event_and_the_approval_are_written_in_one_transaction(client, monkeypatch):
    ask(client)

    def boom(*_args, **_kwargs):
        raise RuntimeError("panne pendant la mise à jour")

    monkeypatch.setattr(approvals, "_close", boom)
    with pytest.raises(RuntimeError):
        answer(client)

    monkeypatch.undo()
    untouched(client)


def two_threads(client, monkeypatch, first, second):
    """Both requests read the pending approval, then write at the same time."""
    barrier = threading.Barrier(2, timeout=10)
    real = events.publish
    seen = threading.local()

    def synchronised(*args, **kwargs):
        if not getattr(seen, "waited", False):
            seen.waited = True
            barrier.wait()
        return real(*args, **kwargs)

    monkeypatch.setattr(events, "publish", synchronised)
    results = {}

    def run(name, call):
        results[name] = call()

    threads = [threading.Thread(target=run, args=("a", first)),
               threading.Thread(target=run, args=("b", second))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()
    return results


def test_two_threads_with_different_decisions_have_exactly_one_winner(client, monkeypatch):
    ask(client, kind="needs_human")

    results = two_threads(
        client, monkeypatch,
        lambda: decide(client, decision="approved", choice=0),
        lambda: decide(client, decision="rejected"),
    )

    statuses = sorted(r.status_code for r in results.values())
    assert statuses == [200, 409], [r.text for r in results.values()]
    loser = next(r for r in results.values() if r.status_code == 409)
    assert loser.json()["detail"]["code"] == "approval_already_decided"
    assert len(answer_events(client)) == 1
    winner = next(r for r in results.values() if r.status_code == 200)
    assert client.get(f"/api/approvals/{REF}").json()["status"] == winner.json()["status"]


def test_two_threads_with_the_same_decision_both_get_a_200_and_one_event(client, monkeypatch):
    ask(client, kind="needs_human")

    results = two_threads(
        client, monkeypatch,
        lambda: decide(client, decision="approved", choice=1, note="go"),
        lambda: decide(client, decision="approved", choice=1, note="go"),
    )

    assert [r.status_code for r in results.values()] == [200, 200], [
        r.text for r in results.values()
    ]
    assert results["a"].json()["response"] == results["b"].json()["response"]
    assert len(answer_events(client)) == 1
