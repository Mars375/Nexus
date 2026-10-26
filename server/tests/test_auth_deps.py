"""Authentification par jeton porteur (#16, ADR-020) : lecture du jeton, 401 et 403 d'identité."""

import logging
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from fastapi import Depends
from sqlalchemy import select

from nexus.auth import tokens
from nexus.clock import TZ, now
from nexus.models import ActorToken, Approval, Task, TaskHistory

AT = "2026-09-28T09:05:00+02:00"
SECRET_FREE_TOKEN = "nxt_" + "A" * 43  # construit à l'exécution


def issue(client, actor="helios"):
    with client.app.state.sessionmaker() as session:
        row, token = tokens.issue(session, actor, "test")
        session.commit()
        return token, row.id


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def last_used_of(client, token_id):
    with client.app.state.sessionmaker() as s:
        return s.get(ActorToken, token_id).last_used_at


def outside_window():
    """An instant just outside the touch window, computed on the UTC timeline: wall-clock
    subtraction in Europe/Paris lands in a non-existent hour on the spring DST change and
    can end up in the future (#128)."""
    return now().astimezone(UTC) - timedelta(seconds=301)


def test_outside_window_is_in_the_past_on_the_spring_dst_change(monkeypatch):
    # 2027-03-28 03:02 CEST: 301 s earlier on the wall clock is 02:56:59, an hour that does
    # not exist that day; read back with fold=0 it would be 54 minutes in the future.
    moment = datetime(2027, 3, 28, 3, 2, tzinfo=TZ)
    monkeypatch.setitem(globals(), "now", lambda: moment)
    assert outside_window() == moment.astimezone(UTC) - timedelta(seconds=301)
    # Compare instants: two values sharing one tzinfo compare by wall clock and would pass.
    assert outside_window().astimezone(UTC) < moment.astimezone(UTC)


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


def test_a_valid_token_records_its_last_use(client):
    token, token_id = issue(client, "codex")
    assert last_used_of(client, token_id) is None
    assert create_task(client, **bearer(token)).status_code == 201
    stamp = last_used_of(client, token_id)
    assert stamp is not None
    assert abs((stamp - now()).total_seconds()) < 5


def test_a_recent_use_is_not_written_again(client):
    token, token_id = issue(client)
    recent = now() - timedelta(seconds=100)
    with client.app.state.sessionmaker() as s:
        s.get(ActorToken, token_id).last_used_at = recent
        s.commit()
    assert create_task(client, **bearer(token)).status_code == 201
    assert last_used_of(client, token_id) == recent


def test_a_use_after_the_window_is_recorded_again(client):
    token, token_id = issue(client)
    old = outside_window()
    with client.app.state.sessionmaker() as s:
        s.get(ActorToken, token_id).last_used_at = old
        s.commit()
    assert create_task(client, **bearer(token)).status_code == 201
    stamp = last_used_of(client, token_id)
    assert stamp is not None and stamp.astimezone(UTC) > old
    assert abs((stamp - now()).total_seconds()) < 5


def test_a_locked_database_does_not_delay_an_authenticated_request(client):
    token, token_id = issue(client, "codex")
    locker = sqlite3.connect(client.app.state.settings.db_path)
    locker.execute("BEGIN IMMEDIATE")  # holds the write lock: the diagnostic write cannot run
    try:
        start = time.perf_counter()
        res = client.get("/api/tasks", headers=bearer(token))
        elapsed = time.perf_counter() - start
    finally:
        locker.rollback()
        locker.close()
    assert res.status_code == 200
    assert elapsed < 2.0  # the driver default would block ~5 s here
    assert last_used_of(client, token_id) is None  # the touch was skipped, not the request
    assert client.get("/api/tasks", headers=bearer(token)).status_code == 200
    assert last_used_of(client, token_id) is not None  # the next request records it


def test_a_recent_use_never_waits_for_the_write_lock(client, caplog):
    # #94: inside the window nothing is due, so the request must not even ask for the lock
    # (an UPDATE matching no row still takes it) nor log a misleading warning.
    token, token_id = issue(client, "codex")
    recent = now() - timedelta(seconds=10)
    with client.app.state.sessionmaker() as s:
        s.get(ActorToken, token_id).last_used_at = recent
        s.commit()
    assert client.get("/api/tasks", headers=bearer(token)).status_code == 200  # warm-up
    caplog.set_level(logging.WARNING, logger="nexus")
    locker = sqlite3.connect(client.app.state.settings.db_path)
    locker.execute("BEGIN IMMEDIATE")
    try:
        start = time.perf_counter()
        res = client.get("/api/tasks", headers=bearer(token))
        elapsed = time.perf_counter() - start
    finally:
        locker.rollback()
        locker.close()
    assert res.status_code == 200
    # Asking for the lock costs at least the whole busy timeout (measured 0.36 s on the old
    # code). A fixed 50 ms flaked at 66-85 ms when the suite ran loaded: the deterministic proof
    # is the spy test below, this one only checks the request does not wait.
    assert elapsed < tokens.TOUCH_BUSY_TIMEOUT
    assert "dernière utilisation" not in caplog.text
    assert last_used_of(client, token_id) == recent


def test_a_recent_use_opens_no_touch_session(client, monkeypatch):
    token, token_id = issue(client, "codex")
    with client.app.state.sessionmaker() as s:
        s.get(ActorToken, token_id).last_used_at = now() - timedelta(seconds=10)
        s.commit()
    opened = []

    def spy():
        opened.append(1)
        raise AssertionError("no touch session expected inside the window")

    monkeypatch.setattr(client.app.state, "touch_sessionmaker", spy)
    assert client.get("/api/tasks", headers=bearer(token)).status_code == 200
    assert opened == []


def test_a_revoked_token_is_refused_without_touching_its_last_use(client):
    token, token_id = issue(client)
    old = outside_window()
    with client.app.state.sessionmaker() as s:
        row = s.get(ActorToken, token_id)
        row.last_used_at = old
        row.revoked_at = now()
        s.commit()
    assert create_task(client, **bearer(token)).status_code == 401
    assert last_used_of(client, token_id).astimezone(UTC) == old


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


@pytest.mark.parametrize("header", ["loic", "mallory", ""])
def test_actor_header_differing_from_the_token_does_not_touch_its_last_use(client, header):
    # The actor check comes before the touch: a refused request is not a use of the token.
    token, token_id = issue(client, "helios")
    old = outside_window()
    with client.app.state.sessionmaker() as s:
        s.get(ActorToken, token_id).last_used_at = old
        s.commit()
    res = create_task(client, **bearer(token), **{"X-Nexus-Actor": header})
    assert res.status_code == 403
    assert last_used_of(client, token_id).astimezone(UTC) == old


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


def _identity_client(client):
    from fastapi import APIRouter

    from nexus.auth.deps import TokenIdentity, authenticated_token

    router = APIRouter()

    @router.get("/api/_identity")
    def identity(who: Annotated[TokenIdentity, Depends(authenticated_token)]) -> dict:
        return {"token_id": who.token_id, "actor": who.actor}

    client.app.include_router(router)
    return client


def test_authenticated_token_gives_token_id_and_actor(client):
    _identity_client(client)
    token, token_id = issue(client, "codex")
    res = client.get("/api/_identity", headers=bearer(token))
    assert res.status_code == 200
    assert res.json() == {"token_id": token_id, "actor": "codex"}


def test_authenticated_token_refuses_like_authenticated_actor(client):
    _identity_client(client)
    token, token_id = issue(client, "codex")
    res = client.get("/api/_identity", headers={"Authorization": "Bearer"})
    assert res.status_code == 401 and res.json()["detail"]["code"] == "auth_required"
    unknown = "nxt_" + "B" * 43
    res = client.get("/api/_identity", headers=bearer(unknown))
    assert res.status_code == 401 and res.json()["detail"]["code"] == "invalid_token"
    assert unknown not in res.text
    res = client.get("/api/_identity", headers=bearer(token) | {"X-Nexus-Actor": "loic"})
    assert res.status_code == 403 and res.json()["detail"]["code"] == "actor_mismatch"
    with client.app.state.sessionmaker() as s:
        s.get(tokens.ActorToken, token_id).revoked_at = now()
        s.commit()
    res = client.get("/api/_identity", headers=bearer(token))
    assert res.status_code == 401 and res.json()["detail"]["code"] == "invalid_token"
    assert token not in res.text
