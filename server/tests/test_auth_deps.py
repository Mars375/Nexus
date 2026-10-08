"""Authentification par jeton porteur (#16, ADR-020) : lecture du jeton, 401 et 403 d'identité."""

import logging

import pytest
from sqlalchemy import select

from nexus.auth import tokens
from nexus.clock import now
from nexus.models import Approval, Task, TaskHistory

AT = "2026-09-28T09:05:00+02:00"
SECRET_FREE_TOKEN = "nxt_" + "A" * 43  # construit à l'exécution


def issue(client, actor="helios"):
    with client.app.state.sessionmaker() as session:
        row, token = tokens.issue(session, actor, "test")
        session.commit()
        return token, row.id


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def create_task(client, **headers):
    return client.post("/api/tasks", json={"title": "t", "objective": "o"}, headers=headers)


def test_a_valid_token_sets_the_actor(client):
    token, _ = issue(client, "codex")
    res = create_task(client, **bearer(token))
    assert res.status_code == 201
    assert res.json()["created_by"] == "codex"
    with client.app.state.sessionmaker() as s:
        assert s.scalars(select(TaskHistory.actor)).all() == ["codex"]


def test_scheme_is_case_insensitive(client):
    token, _ = issue(client, "codex")
    res = create_task(client, Authorization=f"bearer {token}")
    assert res.status_code == 201


def test_token_actor_authors_comments(client):
    token, _ = issue(client, "orca")
    ref = create_task(client).json()["id"]
    res = client.post(f"/api/tasks/{ref}/comments", json={"body": "ok"}, headers=bearer(token))
    assert res.json()["author"] == "orca"


def test_token_actor_decides_approvals(client):
    token, _ = issue(client, "loic")
    client.post("/api/events", json={
        "id": "e1", "at": AT, "actor": "mnema", "kind": "question",
        "subject": "Quelle version publier ?",
        "needs": ["loic"],
    })
    res = client.post("/api/approvals/nx-appr-1/answer", json={"text": "oui"},
                      headers=bearer(token))
    assert res.status_code == 200, res.text
    with client.app.state.sessionmaker() as s:
        assert s.get(Approval, 1).status == "answered"
    assert client.get("/api/approvals/nx-appr-1").json()["decided_by"] == "loic"


def test_a_token_that_is_not_addressee_gets_the_old_409(client):
    token, _ = issue(client, "helios")
    client.post("/api/events", json={
        "id": "e1", "at": AT, "actor": "mnema", "kind": "question",
        "subject": "Quelle version publier ?",
        "needs": ["loic"],
    })
    res = client.post("/api/approvals/nx-appr-1/answer", json={"text": "oui"},
                      headers=bearer(token))
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "not_addressee"


@pytest.mark.parametrize("value", [
    "", "Bearer", "Bearer ", "Bearer  ", "Basic dXNlcjpwYXNz", "Token abc",
    "Bearer nxt_short", "Bearer " + "x" * 10_000, "Bearer " + "é" * 50,
    "Bearer nxt_" + "é" * 43, f"Bearer {'nxt_' + 'A' * 43} extra", "nxt_" + "A" * 43,
    "Bearer\tnxt_" + "A" * 43, "Bearer ghp_" + "A" * 36,
])
def test_malformed_authorization_is_401_auth_required_and_never_echoed(client, value):
    res = client.post("/api/tasks", json={"title": "t", "objective": "o"},
                      headers={"Authorization": value.encode("latin-1", "replace")
                               if not value.isascii() else value})
    assert res.status_code == 401, res.text
    assert res.json()["detail"]["code"] == "auth_required"
    assert res.headers["www-authenticate"] == "Bearer"
    fragment = value.removeprefix("Bearer ").strip()
    if len(fragment) > 3 and fragment != "Bearer":  # the scheme word is in the fixed message
        assert fragment not in res.text


def test_non_ascii_header_bytes_are_a_401_not_a_500(client):
    res = client.post("/api/tasks", json={"title": "t", "objective": "o"},
                      headers={"Authorization": b"Bearer nxt_" + "é".encode() * 43})
    assert res.status_code == 401


def test_unknown_and_revoked_tokens_share_one_answer(client):
    token, tid = issue(client)
    with client.app.state.sessionmaker() as s:
        from nexus.models import ActorToken
        s.get(ActorToken, tid).revoked_at = now()
        s.commit()
    revoked = create_task(client, **bearer(token))
    unknown = create_task(client, **bearer(SECRET_FREE_TOKEN))
    assert revoked.status_code == unknown.status_code == 401
    assert revoked.json() == unknown.json()
    assert revoked.json()["detail"]["code"] == "invalid_token"
    assert revoked.headers["www-authenticate"] == "Bearer"
    assert token not in revoked.text and SECRET_FREE_TOKEN not in unknown.text


def test_revocation_is_effective_on_the_next_request(client):
    token, tid = issue(client)
    assert create_task(client, **bearer(token)).status_code == 201
    from nexus.models import ActorToken
    with client.app.state.sessionmaker() as s:
        s.get(ActorToken, tid).revoked_at = now()
        s.commit()
    assert create_task(client, **bearer(token)).status_code == 401


def test_actor_header_matching_the_token_is_accepted(client):
    token, _ = issue(client, "helios")
    res = create_task(client, **bearer(token), **{"X-Nexus-Actor": "helios"})
    assert res.status_code == 201


@pytest.mark.parametrize("header", ["loic", "mallory", ""])
def test_actor_header_differing_from_the_token_is_403_without_echo(client, header):
    token, _ = issue(client, "helios")
    res = create_task(client, **bearer(token), **{"X-Nexus-Actor": header})
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "actor_mismatch"
    if header:
        assert header not in res.text
    assert token not in res.text
    with client.app.state.sessionmaker() as s:
        assert s.scalars(select(Task)).all() == []


def event(actor, id="e1"):
    return {"id": id, "at": AT, "actor": actor, "kind": "question", "subject": "avance ?",
            "needs": ["loic"]}


def test_events_body_actor_must_match_the_token(client):
    token, _ = issue(client, "helios")
    res = client.post("/api/events", json=event("codex"), headers=bearer(token))
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "actor_mismatch"
    assert client.get("/api/events").json() == []
    ok = client.post("/api/events", json=event("helios"), headers=bearer(token))
    assert ok.status_code == 201 and ok.json()["actor"] == "helios"


def test_events_header_mismatch_with_token_is_403(client):
    token, _ = issue(client, "helios")
    res = client.post("/api/events", json=event("helios"),
                      headers=bearer(token) | {"X-Nexus-Actor": "codex"})
    assert res.status_code == 403


def test_events_with_a_malformed_authorization_are_401(client):
    res = client.post("/api/events", json=event("helios"), headers={"Authorization": "Basic x"})
    assert res.status_code == 401


def test_the_token_never_reaches_the_access_log(client, caplog):
    caplog.set_level(logging.DEBUG)
    token, _ = issue(client)
    create_task(client, **bearer(token))
    create_task(client, **bearer(SECRET_FREE_TOKEN))
    assert token not in caplog.text and SECRET_FREE_TOKEN not in caplog.text


def test_a_token_pasted_in_a_comment_is_redacted(client):
    token, _ = issue(client, "helios")
    ref = create_task(client).json()["id"]
    res = client.post(f"/api/tasks/{ref}/comments", json={"body": f"voici {token} ok"})
    assert token not in res.text
    assert "[REDACTED]" in res.json()["body"]


def test_a_token_pasted_in_an_event_is_redacted(client):
    body = event("helios") | {"subject": f"clé {SECRET_FREE_TOKEN}", "body": SECRET_FREE_TOKEN}
    res = client.post("/api/events", json=body)
    assert SECRET_FREE_TOKEN not in res.text
    assert res.status_code == 201
    assert "actor_token" in res.json()["redacted"]
