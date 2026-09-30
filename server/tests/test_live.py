"""Temps réel (#5) : curseur, lecture des changements, contrôle d'origine."""

import pytest

from nexus import live
from nexus.live import Cursor, changes_since, current_cursor, origin_allowed, start_cursor

AT = "2026-09-30T09:00:00+02:00"
PRIVATE = "sujet confidentiel à ne jamais diffuser"


def new_task(client, title="Pont"):
    res = client.post("/api/tasks", json={"title": title, "objective": "Lire"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def db(client):
    return client.app.state.sessionmaker()


def test_an_empty_base_has_a_zero_cursor(client):
    with db(client) as s:
        assert current_cursor(s) == Cursor(0, 0)


def test_no_change_means_no_message(client):
    with db(client) as s:
        start = current_cursor(s)
        assert changes_since(s, start) == ([], start)


def test_several_changes_of_one_task_become_one_message(client):
    with db(client) as s:
        start = current_cursor(s)
    ref = new_task(client)
    assert client.patch(f"/api/tasks/{ref}", json={"next_action": "relire"}).status_code == 200
    assert client.post(f"/api/tasks/{ref}/comments", json={"body": "noté"}).status_code == 201
    with db(client) as s:
        messages, end = changes_since(s, start)
    assert [(m["type"], m["task"]) for m in messages] == [("task_changed", ref)]
    assert messages[-1]["cursor"] == end.as_dict()
    assert end.history > start.history


def test_events_carry_kind_and_references_but_no_free_text(client):
    ref = new_task(client)
    with db(client) as s:
        start = current_cursor(s)
    res = client.post("/api/events", json={
        "id": "evt_live", "at": AT, "actor": "helios", "kind": "progress",
        "subject": PRIVATE, "body": PRIVATE, "task": ref, "payload": {"percent": 10},
    })
    assert res.status_code == 201, res.text
    with db(client) as s:
        messages, end = changes_since(s, start)
    # Un événement peut aussi changer la tâche (task_changed) : on ne juge que le message
    # d'événement, dernier de la relecture, donc porteur du curseur de fin.
    assert messages[-1] == {
        "type": "event", "event": res.json()["id"], "task": ref, "kind": "progress",
        "cursor": end.as_dict(),
    }
    assert [m for m in messages if m["type"] == "event"] == messages[-1:]
    assert PRIVATE not in str(messages)


def test_only_the_last_message_of_a_batch_advances_the_cursor(client):
    with db(client) as s:
        start = current_cursor(s)
    a = new_task(client, "A")
    b = new_task(client, "B")
    with db(client) as s:
        messages, end = changes_since(s, start)
    assert [m["task"] for m in messages] == [a, b]
    assert messages[0]["cursor"] == start.as_dict()
    assert messages[1]["cursor"] == end.as_dict()


def test_too_many_changes_become_a_single_resync(client, monkeypatch):
    monkeypatch.setattr(live, "RESYNC_THRESHOLD", 2)
    with db(client) as s:
        start = current_cursor(s)
    for i in range(3):
        new_task(client, f"T{i}")
    with db(client) as s:
        messages, end = changes_since(s, start)
        latest = current_cursor(s)
    assert messages == [{"type": "resync", "cursor": latest.as_dict()}]
    assert end == latest


def test_no_cursor_starts_from_now():
    assert start_cursor(None, None, Cursor(5, 7)) == (Cursor(5, 7), False)


def test_a_valid_cursor_is_kept():
    assert start_cursor("3", "4", Cursor(5, 7)) == (Cursor(3, 4), False)


def test_a_cursor_ahead_of_the_base_is_reset():
    assert start_cursor("9", "0", Cursor(5, 7)) == (Cursor(5, 7), True)


@pytest.mark.parametrize(
    ("history", "events"), [("x", "1"), ("-1", "0"), ("1", None), ("9" * 13, "0"), ("²", "0")]
)
def test_invalid_cursor_parameters_are_refused(history, events):
    with pytest.raises(ValueError):
        start_cursor(history, events, Cursor(5, 5))


@pytest.mark.parametrize(
    "origin",
    [None, "http://localhost:5173", "http://127.0.0.1:8765", "http://[::1]:5199", "https://localhost"],
)
def test_loopback_origins_are_allowed(origin):
    assert origin_allowed(origin, frozenset())


@pytest.mark.parametrize(
    "origin",
    ["https://evil.example", "http://localhost.evil.example", "http://127.0.0.1@evil.example",
     "null", "file://", "http://localhost:99999", "ftp://localhost"],
)
def test_foreign_origins_are_refused(origin):
    assert not origin_allowed(origin, frozenset())


def test_a_configured_origin_is_allowed_exactly():
    extra = frozenset({"tauri://localhost"})
    assert origin_allowed("tauri://localhost", extra)
    assert not origin_allowed("tauri://localhost.evil", extra)
