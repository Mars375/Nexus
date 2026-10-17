"""Temps réel (#5) : curseur, lecture des changements, contrôle d'origine."""

import re

import pytest
from conftest import ws_connect
from starlette.websockets import WebSocketDisconnect

from nexus import live
from nexus.config import Settings
from nexus.live import (
    Cursor,
    changes_since,
    current_cursor,
    origin_allowed,
    origin_allowed_in_scope,
    start_cursor,
)

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


def test_an_event_without_task_carries_a_null_task(client):
    with db(client) as s:
        start = current_cursor(s)
    res = client.post("/api/events", json={
        "id": "evt_notask", "at": AT, "actor": "helios", "kind": "question",
        "subject": "sans tâche", "body": "Une question générale ?", "needs": ["helios"],
    })
    assert res.status_code == 201, res.text
    with db(client) as s:
        messages, end = changes_since(s, start)
    assert messages == [{
        "type": "event", "event": res.json()["id"], "task": None, "kind": "question",
        "cursor": end.as_dict(),
    }]


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


INSTANCE = "0123456789abcdef"
OTHER = "fedcba9876543210"


def test_no_cursor_starts_from_now():
    assert start_cursor(None, None, None, Cursor(5, 7), INSTANCE) == (Cursor(5, 7), False)


def test_a_valid_cursor_is_kept():
    assert start_cursor("3", "4", None, Cursor(5, 7), INSTANCE) == (Cursor(3, 4), False)


def test_a_cursor_ahead_of_the_base_is_reset():
    assert start_cursor("9", "0", INSTANCE, Cursor(5, 7), INSTANCE) == (Cursor(5, 7), True)


def test_only_the_events_component_ahead_resets_to_now():
    assert start_cursor("0", "9", INSTANCE, Cursor(5, 7), INSTANCE) == (Cursor(5, 7), True)


def test_same_instance_and_cursor_not_ahead_is_kept():
    assert start_cursor("3", "4", INSTANCE, Cursor(5, 7), INSTANCE) == (Cursor(3, 4), False)


def test_a_different_instance_resets_even_if_the_cursor_is_not_ahead():
    # Central regression: a restored base can have rewritten ids past the old cursor.
    assert start_cursor("3", "4", OTHER, Cursor(5, 7), INSTANCE) == (Cursor(5, 7), True)


def test_a_cursor_without_instance_is_compared_to_nothing():
    # Old client: same behaviour as before the instance existed.
    assert start_cursor("3", "4", None, Cursor(5, 7), INSTANCE) == (Cursor(3, 4), False)


BAD_INSTANCES = ["", "ABCDEF0123456789", "0123456789abcde", "0123456789abcdef0", "٣" * 16,
                 "g" * 16, "0" * 10_000, "0123456789abcde\n"]


@pytest.mark.parametrize("instance", BAD_INSTANCES, ids=range(len(BAD_INSTANCES)))
def test_a_malformed_instance_is_refused(instance):
    with pytest.raises(ValueError) as error:
        start_cursor("1", "1", instance, Cursor(5, 5), INSTANCE)
    assert instance not in str(error.value) or instance == ""


def test_an_instance_without_cursor_is_refused():
    with pytest.raises(ValueError):
        start_cursor(None, None, INSTANCE, Cursor(5, 5), INSTANCE)
    with pytest.raises(ValueError):
        start_cursor("1", None, INSTANCE, Cursor(5, 5), INSTANCE)


@pytest.mark.parametrize(
    ("history", "events"), [("x", "1"), ("-1", "0"), ("1", None), ("9" * 13, "0"), ("²", "0")]
)
def test_invalid_cursor_parameters_are_refused(history, events):
    with pytest.raises(ValueError):
        start_cursor(history, events, None, Cursor(5, 5), INSTANCE)


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


def test_hello_without_cursor_starts_from_now(client):
    new_task(client)
    with db(client) as s:
        now = current_cursor(s)
    with ws_connect(client, "/api/ws") as ws:
        hello = ws.receive_json()
    assert re.fullmatch(r"[0-9a-f]{16}", hello.pop("instance"))
    assert hello == {"type": "hello", "cursor": now.as_dict(), "reset": False}


def test_a_reconnection_replays_what_was_missed(client):
    with db(client) as s:
        before = current_cursor(s)
    ref = new_task(client)
    url = f"/api/ws?history_after={before.history}&events_after={before.events}"
    with ws_connect(client, url) as ws:
        assert ws.receive_json()["type"] == "hello"
        message = ws.receive_json()
    assert (message["type"], message["task"]) == ("task_changed", ref)


def test_a_change_after_connecting_is_pushed_live(client):
    with ws_connect(client, "/api/ws") as ws:
        ws.receive_json()  # hello
        ref = new_task(client)
        message = ws.receive_json()
    assert (message["type"], message["task"]) == ("task_changed", ref)


def test_silence_is_broken_by_a_ping(client, monkeypatch):
    monkeypatch.setattr(live, "PING_SECONDS", 0.3)
    with ws_connect(client, "/api/ws") as ws:
        hello = ws.receive_json()
        assert ws.receive_json() == {"type": "ping", "cursor": hello["cursor"]}


def test_a_cursor_ahead_of_the_base_announces_a_reset(client):
    with ws_connect(client, "/api/ws?history_after=999&events_after=999") as ws:
        assert ws.receive_json()["reset"] is True


def test_a_foreign_origin_is_refused(client):
    with pytest.raises(WebSocketDisconnect) as closed:
        with ws_connect(client, "/api/ws", headers={"origin": "https://evil.example"}):
            pass
    assert closed.value.code == 1008


def test_a_configured_origin_is_accepted(tmp_path):
    from conftest import ActorClient, tailscale_json

    from nexus.app import create_app

    settings = Settings(
        data_dir=tmp_path / "data", allowed_origins=frozenset({"tauri://localhost"})
    )
    with ActorClient(create_app(settings, nodes_runner=tailscale_json)) as client:
        with ws_connect(client, "/api/ws", headers={"origin": "tauri://localhost"}) as ws:
            assert ws.receive_json()["type"] == "hello"


def test_a_loopback_origin_is_accepted(client):
    with ws_connect(client, "/api/ws", headers={"origin": "http://localhost:5199"}) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_an_origin_header_name_in_any_case_is_read():
    """ASGI only recommends lowercase header names: a server may pass b"Origin" as is (#61)."""
    assert not origin_allowed_in_scope(
        {"headers": [(b"Origin", b"https://evil.example")]}, frozenset()
    )
    assert origin_allowed_in_scope(
        {"headers": [(b"Origin", b"http://localhost:5173")]}, frozenset()
    )


def test_two_origin_headers_are_refused():
    """More than one Origin is ambiguous: refused whatever the order, and even with equal
    values, like the Host check (RFC 9112 §3.2)."""
    local, evil = b"http://localhost:5173", b"https://evil.example"
    for headers in ([(b"origin", local), (b"Origin", evil)],
                    [(b"Origin", evil), (b"origin", local)],
                    [(b"Origin", local), (b"origin", local)]):
        assert not origin_allowed_in_scope({"headers": headers}, frozenset())


def test_an_empty_origin_value_is_not_an_absent_origin():
    assert not origin_allowed_in_scope({"headers": [(b"Origin", b"")]}, frozenset())


def test_a_missing_origin_still_means_a_non_browser_client():
    assert origin_allowed_in_scope({"headers": []}, frozenset())


def test_the_origin_value_is_still_matched_exactly():
    """Only the header NAME is case-insensitive; the configured value stays exact."""
    assert not origin_allowed_in_scope(
        {"headers": [(b"Origin", b"TAURI://localhost")]}, frozenset({"tauri://localhost"})
    )


def test_a_real_server_refuses_a_foreign_origin_without_burning_the_ticket(tmp_path):
    """Real-path guard for #61: on today's uvicorn every ws mode lowercases names (see probe
    in the PR body), so the wire case is not exercised here — the scope unit tests carry that
    part. This one proves the real route refuses a foreign origin and that reusing the
    ticket still opens (the refusal happened before the ticket step) and stays 101.
    """
    from conftest import (
        issue_ticket_http,
        issue_token,
        raw_handshake,
        serve_real,
        stop_real,
        tailscale_json,
    )

    from nexus.app import create_app
    from nexus.live import LIVE_PROTOCOL

    app = create_app(Settings(data_dir=tmp_path / "data"), nodes_runner=tailscale_json)
    server, thread, port = serve_real(app, ws="websockets")
    try:
        protocols = f"{LIVE_PROTOCOL}, {issue_ticket_http(port, issue_token(app))}"
        refused = raw_handshake(port, f"localhost:{port}", protocols,
                                origin="https://evil.example")
        assert refused.startswith("HTTP/1.1 403"), refused.splitlines()[:1]
        admitted = raw_handshake(port, f"localhost:{port}", protocols,
                                 origin="http://localhost:5173")
    finally:
        stop_real(server, thread)
    assert admitted.startswith("HTTP/1.1 101"), admitted.splitlines()[:1]


def test_an_invalid_cursor_is_refused_without_echo(client):
    with pytest.raises(WebSocketDisconnect) as closed:
        with ws_connect(client, "/api/ws?history_after=ghp_trace&events_after=0"):
            pass
    assert closed.value.code == 1008
    assert closed.value.reason == ""  # no reason at all: nothing received is echoed


def test_allowed_origins_are_read_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_ALLOWED_ORIGINS", " tauri://localhost , ,http://tauri.localhost")
    assert Settings.from_env().allowed_origins == frozenset(
        {"tauri://localhost", "http://tauri.localhost"}
    )


def _hello(client, query=""):
    with ws_connect(client, "/api/ws" + query) as ws:
        return ws.receive_json()


def test_hello_instance_is_16_hex_and_stable_for_one_app(client):
    first, second = _hello(client), _hello(client)
    assert re.fullmatch(r"[0-9a-f]{16}", first["instance"])
    assert first["instance"] == second["instance"]


def test_hello_instance_differs_between_apps(tmp_path):
    from conftest import ActorClient, tailscale_json

    from nexus.app import create_app

    seen = []
    for name in ("a", "b"):
        settings = Settings(data_dir=tmp_path / name)
        with ActorClient(create_app(settings, nodes_runner=tailscale_json)) as c:
            seen.append(_hello(c)["instance"])
    assert seen[0] != seen[1]


def test_only_hello_carries_the_instance(client):
    new_task(client)
    with ws_connect(client, "/api/ws?history_after=0&events_after=0") as ws:
        ws.receive_json()
        assert "instance" not in ws.receive_json()


def test_a_cursor_without_instance_does_not_reset_over_websocket(client):
    ref = new_task(client)
    hello = _hello(client, "?history_after=1&events_after=0")
    assert hello["reset"] is False and ref


def test_a_restored_base_makes_the_old_instance_reset(tmp_path):
    """Restore an older copy then rewrite past the cursor: ids reused, cursor not ahead."""
    import shutil

    from conftest import ActorClient, tailscale_json

    from nexus.app import create_app

    settings = Settings(data_dir=tmp_path / "data")
    with ActorClient(create_app(settings, nodes_runner=tailscale_json)) as one:
        new_task(one)
        copy = tmp_path / "copy.db"
        shutil.copy(settings.db_path, copy)
        new_task(one, "B")
        new_task(one, "C")
        old = _hello(one)
        old_instance = old["instance"]
        with db(one) as s:
            old_cursor = current_cursor(s)
    # Hot-restore is out of scope: Nexus is stopped, then the older copy replaces the base.
    shutil.copy(copy, settings.db_path)
    for suffix in ("-wal", "-shm"):
        settings.db_path.with_name(settings.db_path.name + suffix).unlink(missing_ok=True)
    with ActorClient(create_app(settings, nodes_runner=tailscale_json)) as two:
        for title in ("X", "Y", "Z", "W"):
            new_task(two, title)  # rewrites past the old cursor
        with db(two) as s:
            current = current_cursor(s)
        assert current.history >= old_cursor.history
        query = (f"?history_after={old_cursor.history}&events_after={old_cursor.events}"
                 f"&instance={old_instance}")
        hello = _hello(two, query)
    assert hello["reset"] is True
    assert hello["cursor"] == current.as_dict()
    assert hello["instance"] != old_instance


@pytest.mark.parametrize(
    "query",
    ["?instance=0123456789abcdef", "?history_after=1&events_after=1&instance=ABCDEF0123456789",
     "?history_after=1&events_after=1&instance=" + "٣" * 16,
     "?history_after=1&events_after=1&instance=" + "0" * 10_000,
     "?history_after=1&events_after=1&instance=short"],
    ids=["no-cursor", "uppercase", "non-ascii", "too-long", "short"],
)
def test_a_bad_instance_is_refused_without_echo(client, query):
    value = query.rsplit("instance=", 1)[1]
    with pytest.raises(WebSocketDisconnect) as closed:
        with ws_connect(client, "/api/ws" + query):
            pass
    assert closed.value.code == 1008
    assert closed.value.reason == ""
    assert value not in str(closed.value.reason or "")
