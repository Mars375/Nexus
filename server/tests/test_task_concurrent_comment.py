"""#154: an edit that overlaps a comment on the same task must not fail with a false conflict.

Found in the CI trace of the failing e2e run: the PATCH started 130 ms BEFORE the slow first
`POST .../comments` finished, read the task at version v, and its UPDATE then found v+1, because
adding a comment bumped `Task.version` (through `updated_at`). The comment changes none of the
fields an edit is based on: it must not take part in the optimistic lock.
"""

import logging

import pytest

from nexus.tasks import service


def new_task(client):
    res = client.post("/api/tasks", json={"title": "Pont", "objective": "Lire"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def overlap(monkeypatch, during):
    """Run `during()` (another request) after the PATCH has read the task, before it writes."""
    real = service.update_task
    state = {"done": False}

    def racing(*args, **kwargs):
        if not state["done"]:
            state["done"] = True
            during()
        return real(*args, **kwargs)

    monkeypatch.setattr(service, "update_task", racing)


def test_a_comment_posted_while_an_edit_is_in_flight_does_not_conflict(client, monkeypatch):
    ref = new_task(client)
    overlap(monkeypatch, lambda: client.post(f"/api/tasks/{ref}/comments", json={"body": "noté"}))

    res = client.patch(f"/api/tasks/{ref}", json={"lead_agent": "helios"})

    assert res.status_code == 200, res.text
    assert res.json()["lead_agent"] == "helios"
    assert [c["body"] for c in client.get(f"/api/tasks/{ref}/comments").json()] == ["noté"]


def test_a_comment_still_moves_the_task_up_the_board(client):
    ref = new_task(client)
    before = client.get(f"/api/tasks/{ref}").json()["updated_at"]

    client.post(f"/api/tasks/{ref}/comments", json={"body": "noté"})

    assert client.get(f"/api/tasks/{ref}").json()["updated_at"] > before


def test_two_real_edits_that_overlap_still_conflict(client, monkeypatch):
    ref = new_task(client)
    overlap(monkeypatch, lambda: client.patch(f"/api/tasks/{ref}", json={"title": "Autre"}))

    res = client.patch(f"/api/tasks/{ref}", json={"lead_agent": "helios"})

    assert (res.status_code, res.json()["detail"]["code"]) == (409, "concurrent_update")


def test_a_version_conflict_is_logged_without_any_received_value(client, monkeypatch, caplog):
    ref = new_task(client)
    overlap(monkeypatch, lambda: client.patch(f"/api/tasks/{ref}", json={"title": "Autre"}))
    caplog.set_level(logging.WARNING, logger="nexus")

    client.patch(f"/api/tasks/{ref}", json={"lead_agent": "helios"})

    [record] = [r for r in caplog.records if "conflit de version" in r.getMessage()]
    assert "PATCH /api/tasks/{task_ref}" in record.getMessage()  # the route template
    assert ref not in record.getMessage() and "Autre" not in record.getMessage()


@pytest.mark.parametrize("path", ["/api/tasks/{ref}/status"])
def test_a_status_move_overlapping_a_comment_does_not_conflict(client, monkeypatch, path):
    ref = new_task(client)
    real = service.change_status
    state = {"done": False}

    def racing(*args, **kwargs):
        if not state["done"]:
            state["done"] = True
            client.post(f"/api/tasks/{ref}/comments", json={"body": "noté"})
        return real(*args, **kwargs)

    monkeypatch.setattr(service, "change_status", racing)

    res = client.post(path.format(ref=ref), json={"status": "todo", "next_action": "x"})

    assert res.status_code == 200, res.text
