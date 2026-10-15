"""WebSocket ticket (#57): issuing, handshake, revocation of open sockets."""

import logging
import re

import pytest
from conftest import (
    ActorClient,
    issue_ticket_http,
    issue_token,
    raw_handshake,
    serve_real,
    stop_real,
    tailscale_json,
    ws_connect,
)
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from nexus import live
from nexus.app import create_app
from nexus.auth import tokens
from nexus.auth.tickets import TicketStore
from nexus.clock import now
from nexus.live import LIVE_PROTOCOL, ticket_from_subprotocols
from nexus.models import ActorToken

TICKET = re.compile(r"nxw_[A-Za-z0-9_-]{43}")


def test_issue_requires_a_token(anonymous, client):
    res = anonymous.post("/api/ws-ticket")
    assert res.status_code == 401 and res.json()["detail"]["code"] == "auth_required"
    unknown = "nxt_" + "B" * 43
    res = anonymous.post("/api/ws-ticket", headers={"Authorization": f"Bearer {unknown}"})
    assert res.status_code == 401 and res.json()["detail"]["code"] == "invalid_token"
    assert unknown not in res.text
    res = client.post("/api/ws-ticket", headers={"X-Nexus-Actor": "codex",
                                                 **client.headers_for("loic")})
    assert res.status_code == 403 and res.json()["detail"]["code"] == "actor_mismatch"
    assert "codex" not in res.text


def test_a_revoked_token_cannot_issue(client):
    headers = client.headers_for("loic")
    with client.app.state.sessionmaker() as session:
        for row in session.scalars(select(ActorToken)):
            row.revoked_at = now()
        session.commit()
    res = client.post("/api/ws-ticket", headers=headers)
    assert res.status_code == 401 and res.json()["detail"]["code"] == "invalid_token"
    assert headers["Authorization"].split()[1] not in res.text


def test_issue_answers_a_well_formed_ticket_not_cached(client):
    res = client.post("/api/ws-ticket")
    assert res.status_code == 200
    body = res.json()
    assert TICKET.fullmatch(body["ticket"])
    assert body["protocol"] == "nexus.live.v1"
    assert body["expires_in"] == 30
    assert res.headers["cache-control"] == "no-store"
    assert set(body) == {"ticket", "protocol", "expires_in"}


def test_two_issues_give_two_tickets(client):
    first = client.post("/api/ws-ticket").json()["ticket"]
    second = client.post("/api/ws-ticket").json()["ticket"]
    assert first != second


def test_the_ticket_never_reaches_the_access_log(client, caplog):
    caplog.set_level(logging.INFO, logger="nexus.access")
    ticket = client.post("/api/ws-ticket").json()["ticket"]
    text = "\n".join(r.getMessage() for r in caplog.records if r.name == "nexus.access")
    assert "POST /api/ws-ticket 200" in text
    assert ticket not in text and ticket[len("nxw_"):] not in text


# --- Handshake (spec 3.3) ---

P = LIVE_PROTOCOL
T = "nxw_" + "A" * 43
T2 = "nxw_" + "C" * 43


@pytest.mark.parametrize("protocols,expected", [
    ([P, T], T),
    ([T, P], T),
    ([], None),
    ([P], None),
    ([T], None),
    ([T, T2], None),
    ([P, P], None),
    ([P, T, "autre"], None),
    ([P, "nxw_" + "A" * 42], None),
    ([P, "nxw_" + "A" * 44], None),
    ([P, "nxw_" + "١" * 43], None),
    ([P, "nxw_" + "A" * 42 + "="], None),
    ([P, "nxt_" + "A" * 43], None),
])
def test_ticket_from_subprotocols(protocols, expected):
    assert ticket_from_subprotocols(protocols) == expected


def _refused(client, protocols, url="/api/ws", **kwargs):
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(url, subprotocols=protocols, **kwargs):
            pass
    assert closed.value.code == 1008
    assert closed.value.reason == ""  # no reason: nothing received is echoed


def _ticket(client, actor="loic"):
    return client.post("/api/ws-ticket", headers=client.headers_for(actor)).json()["ticket"]


def test_a_connection_without_a_ticket_is_refused_without_reason(client):
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/api/ws"):
            pass
    assert closed.value.code == 1008 and closed.value.reason == ""


@pytest.mark.parametrize("shape", [
    "none", "protocol-only", "ticket-only", "two-tickets", "protocol-twice", "one-more-name",
    "short", "long", "padded", "actor-token", "unknown",
])
def test_handshake_refusals_carry_no_reason(client, shape):
    ticket = _ticket(client)
    actor_token = client.token_for("loic")
    protocols = {
        "none": [],
        "protocol-only": [P],
        "ticket-only": [ticket],
        "two-tickets": [ticket, _ticket(client)],
        "protocol-twice": [P, P],
        "one-more-name": [P, ticket, "autre"],
        "short": [P, ticket[:-1]],
        "long": [P, ticket + "A"],
        "padded": [P, ticket[:-1] + "="],
        "actor-token": [P, actor_token],
        "unknown": [P, "nxw_" + "Z" * 43],
    }[shape]
    _refused(client, protocols)


def test_a_ticket_from_a_previous_run_is_refused(settings):
    with ActorClient(create_app(settings, nodes_runner=tailscale_json)) as first:
        ticket = _ticket(first)
    with ActorClient(create_app(settings, nodes_runner=tailscale_json)) as second:
        _refused(second, [P, ticket])


def test_an_expired_ticket_is_refused(client):
    state = {"now": 1000.0}
    store = TicketStore(monotonic=lambda: state["now"], wall=lambda: 1_792_000_000.0 + state["now"])
    client.app.state.ws_tickets = store
    ticket = _ticket(client)
    state["now"] += 30
    _refused(client, [P, ticket])


def test_a_used_ticket_is_refused_even_after_the_first_socket_closed(client):
    ticket = _ticket(client)
    with client.websocket_connect("/api/ws", subprotocols=[P, ticket]) as ws:
        assert ws.receive_json()["type"] == "hello"
    _refused(client, [P, ticket])


@pytest.mark.parametrize("how", ["revoked", "deleted"])
def test_revoked_or_deleted_token_between_issue_and_use_is_refused(client, how):
    ticket = _ticket(client)
    with client.app.state.sessionmaker() as session:
        row = session.scalars(select(ActorToken)).one()
        if how == "revoked":
            row.revoked_at = now()
        else:
            session.delete(row)
        session.commit()
    _refused(client, [P, ticket])


def test_a_foreign_origin_does_not_burn_the_ticket(client):
    ticket = _ticket(client)
    _refused(client, [P, ticket], headers={"origin": "https://evil.example"})
    with client.websocket_connect("/api/ws", subprotocols=[P, ticket],
                                  headers={"origin": "http://localhost:5173"}) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_a_foreign_host_does_not_burn_the_ticket(client):
    ticket = _ticket(client)
    _refused(client, [P, ticket], headers={"host": "evil.example"})
    with client.websocket_connect("/api/ws", subprotocols=[P, ticket]) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_an_invalid_cursor_burns_the_ticket_without_reason(client):
    ticket = _ticket(client)
    _refused(client, [P, ticket], url="/api/ws?history_after=ghp_trace&events_after=0")
    _refused(client, [P, ticket])


def test_the_accepted_subprotocol_is_nexus_live_v1(client):
    with ws_connect(client) as ws:
        assert ws.accepted_subprotocol == "nexus.live.v1"


def test_a_real_server_answers_101_with_the_protocol_never_the_ticket(settings):
    app = create_app(settings, nodes_runner=tailscale_json)
    server, thread, port = serve_real(app)
    try:
        ticket = issue_ticket_http(port, issue_token(app))
        answer = raw_handshake(port, f"localhost:{port}", f"{P}, {ticket}")
    finally:
        stop_real(server, thread)
    head = answer.split("\r\n\r\n", 1)[0]
    assert head.startswith("HTTP/1.1 101"), head.splitlines()[:1]
    assert "sec-websocket-protocol: nexus.live.v1" in head.lower()
    assert ticket not in answer and ticket[len("nxw_"):] not in answer


def test_a_real_server_refuses_a_replayed_ticket(settings):
    app = create_app(settings, nodes_runner=tailscale_json)
    server, thread, port = serve_real(app)
    try:
        ticket = issue_ticket_http(port, issue_token(app))
        first = raw_handshake(port, f"localhost:{port}", f"{P}, {ticket}")
        second = raw_handshake(port, f"localhost:{port}", f"{P}, {ticket}")
    finally:
        stop_real(server, thread)
    assert first.startswith("HTTP/1.1 101"), first.splitlines()[:1]
    assert second.startswith("HTTP/1.1 403"), second.splitlines()[:1]
    assert ticket not in second


# --- Open connection (spec 3.4) ---

def _next_real_message(ws):
    while True:
        message = ws.receive_json()
        if message["type"] != "ping":
            return message


def _revoke(client, token_id, how):
    with client.app.state.sessionmaker() as session:
        row = session.get(ActorToken, token_id)
        if how == "revoked":
            row.revoked_at = now()
        else:
            session.delete(row)
        session.commit()


def _token_id(client, actor="loic"):
    token = client.token_for(actor)
    with client.app.state.sessionmaker() as session:
        return tokens.lookup_row(session, token).id


@pytest.mark.parametrize("how", ["revoked", "deleted"])
def test_revoking_the_token_closes_the_socket_with_4401(client, monkeypatch, how):
    monkeypatch.setattr(live, "POLL_SECONDS", 0.01)
    token_id = _token_id(client)
    with ws_connect(client) as ws:
        assert ws.receive_json()["type"] == "hello"
        _revoke(client, token_id, how)
        with pytest.raises(WebSocketDisconnect) as closed:
            _next_real_message(ws)
    assert closed.value.code == 4401
    assert closed.value.reason == "jeton révoqué"


def test_only_the_socket_of_the_revoked_token_closes(client, monkeypatch):
    monkeypatch.setattr(live, "POLL_SECONDS", 0.01)
    first_id = _token_id(client)
    with client.app.state.sessionmaker() as session:
        _, second_token = tokens.issue(session, "loic", "second")
        session.commit()
    headers = {"Authorization": f"Bearer {second_token}"}
    second_ticket = client.post("/api/ws-ticket", headers=headers).json()["ticket"]
    with ws_connect(client) as first:
        with client.websocket_connect("/api/ws", subprotocols=[P, second_ticket]) as second:
            assert first.receive_json()["type"] == "hello"
            assert second.receive_json()["type"] == "hello"
            _revoke(client, first_id, "revoked")
            with pytest.raises(WebSocketDisconnect) as closed:
                _next_real_message(first)
            assert closed.value.code == 4401
            res = client.post("/api/tasks", json={"title": "t", "objective": "o"},
                              headers=headers)
            assert res.status_code == 201
            assert _next_real_message(second)["type"] == "task_changed"
