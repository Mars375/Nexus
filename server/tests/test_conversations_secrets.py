"""Secrets end to end (spec §3.1, §7.1, §7.3; plan PR 2 §6.8): after a real ingestion, no secret
and no forbidden field is in the raw bytes of `nexus.db` nor of its `-wal`, nor in a backup, nor
in a log line. Secrets are built at runtime; the sessions are invented, under `tmp_path`."""

import logging
import os
import threading
from datetime import timedelta

import pytest
from claude_sessions_support import (
    NOW,
    akia,
    assistant,
    ghp,
    marker,
    migrated,
    new_id,
    nxt,
    raw_bytes,
    sk_ant,
    stamp,
    text,
    title,
    user,
    write_session,
)
from sqlalchemy.exc import IntegrityError

from nexus import backup
from nexus.conversations import ingest, paths, retention, store
from nexus.conversations.cursor_rules import Policy
from nexus.conversations.state import ProcessState

POLICY = Policy.at(NOW, since_days=31, retention_days=31)


@pytest.fixture
def db(tmp_path):
    database = migrated(tmp_path)
    yield database
    database.engine.dispose()


@pytest.fixture
def root(tmp_path):
    path = tmp_path / ".claude" / "projects"
    path.mkdir(parents=True)
    return path


def run(db, root):
    return ingest.claude_pass(db.factory, root, POLICY, stopping=threading.Event(),
                              state=ProcessState(), now=NOW)


def secrets_session(root) -> list[str]:
    body, name, cwd, branch = ghp(), nxt(), sk_ant(), akia()
    edge = "x" + "B" * 39
    long_body = ("réunion " * 2000)[:15989] + " " + f"token={edge}" + " fin"
    write_session(root, [
        title(f"Titre {name}"),
        user(f"voici le jeton {body} à garder", cwd=f"F:\\Projet\\{cwd}",
             branch=f"feat/{branch}"),
        user(long_body),
        assistant([text("réponse sans secret")]),
    ])
    return [body, name, cwd, branch, edge]


def test_no_secret_reaches_the_raw_bytes_before_or_after_the_checkpoint(db, root):
    secrets = secrets_session(root)

    run(db, root)

    assert db.scalar("SELECT count(*) FROM conversation_messages") == 3
    for data in (raw_bytes(db.path), None):
        if data is None:
            assert retention.checkpoint(db.path)
            data = raw_bytes(db.path)
        assert not [s for s in secrets if s.encode() in data]
        assert not [s for s in secrets if s[-12:].encode() in data]


def test_a_prefix_search_finds_no_secret(db, root):
    secrets_session(root)
    run(db, root)

    for prefix in ('"ghp"*', '"nxt"*', '"AKIA"*', '"sk"*'):
        assert not db.rows(
            "SELECT rowid FROM conversation_fts WHERE conversation_fts MATCH ?", prefix)


def test_redacted_is_true_only_on_masked_messages(db, root):
    secrets_session(root)
    run(db, root)

    assert sorted(db.rows("SELECT redacted, truncated FROM conversation_messages")) == [
        (0, 0), (1, 0), (1, 1)]


def test_a_secret_in_place_of_an_identifier_is_refused_not_masked(db, root):
    line = user("contenu")
    line["uuid"] = ghp()
    write_session(root, [line, user("ok")])

    status = run(db, root)

    assert status.codes["field"] == 1
    assert db.scalar("SELECT count(*) FROM conversation_messages") == 1
    assert ghp().encode() not in raw_bytes(db.path)


def test_forbidden_fields_never_reach_the_index(db, root):
    m = {name: marker() for name in ("blob", "tool", "attach", "owner", "cost", "mcp",
                                     "thinking", "input")}
    session_id = new_id()
    write_session(root, [
        {"type": "api-request-blob", "uuid": new_id(), "timestamp": stamp(NOW),
         "sessionId": session_id, "request": {"system": m["blob"]}},
        user([{"type": "tool_result", "content": "sortie"}],
             toolUseResult={"originalFile": m["tool"]}),
        {"type": "attachment", "uuid": new_id(), "timestamp": stamp(NOW),
         "attachment": {"stdout": m["attach"]}},
        {"type": "session-owner", "accountUuid": m["owner"], "organizationUuid": m["owner"]},
        {"type": "cost-state", "costUSD": 1, "note": m["cost"]},
        user("garde", mcpMeta={"server": m["mcp"]}),
        assistant([{"type": "thinking", "thinking": m["thinking"]},
                   {"type": "tool_use", "name": "Bash", "input": {"command": m["input"]}},
                   text("réponse")]),
    ], session=session_id)

    run(db, root)
    data = raw_bytes(db.path)

    assert db.scalar("SELECT count(*) FROM conversation_messages") == 2
    assert not [k for k, v in m.items() if v.encode() in data]


def test_log_lines_carry_no_content_path_or_traceback(db, root, tmp_path, monkeypatch, caplog):
    secret_body = marker()
    session_ids = [new_id() for _ in range(4)]
    write_session(root, [b"{pas du json", user("x", origin={"kind": "task-notification"})],
                  session=session_ids[0], mtime=NOW)
    substituted = write_session(root, [user("a")], session=session_ids[1],
                                mtime=NOW - timedelta(minutes=1))
    removed = write_session(root, [user("b")], session=session_ids[2],
                            mtime=NOW - timedelta(minutes=2))
    write_session(root, [user(f"corps {secret_body}")], session=session_ids[3],
                  mtime=NOW - timedelta(minutes=3))
    listing = paths.iter_claude(paths.check_root(root, "claude-code"))
    monkeypatch.setattr(paths, "iter_claude", lambda _root: listing)
    other = substituted.with_suffix(".new")
    other.write_bytes(substituted.read_bytes())
    os.replace(other, substituted)
    removed.unlink()
    real = store._upsert_cursor

    def failing(session, source, cursor, now):
        if cursor.path_key.endswith(f"{session_ids[3]}.jsonl"):
            raise IntegrityError(f"INSERT … {secret_body}", {"body": secret_body},
                                 Exception(f"{secret_body} {tmp_path}"))
        return real(session, source, cursor, now)

    monkeypatch.setattr(store, "_upsert_cursor", failing)
    with caplog.at_level(logging.DEBUG):
        status = run(db, root)

    assert status.code == "db_error"
    assert {"json", "origin", "substituted", "file_unreadable"} <= set(status.codes)
    forbidden = [secret_body, "-F-Projet-Exemple", str(tmp_path), "Traceback", *session_ids]
    lines = [r.getMessage() for r in caplog.records] + [caplog.text]
    assert caplog.records and not [f for f in forbidden for ln in lines if f in ln]
    assert all(r.exc_info is None for r in caplog.records)


def test_a_backup_after_a_real_ingestion_holds_no_conversation_text(db, root):
    body, name, cwd = marker(), marker(), marker()
    write_session(root, [title(name), user(f"corps {body}", cwd=f"F:\\{cwd}")])
    run(db, root)
    assert db.scalar("SELECT count(*) FROM conversation_messages") == 1

    target = backup.backup(db.path, db.settings.backup_dir, keep=3)

    data = target.read_bytes()
    assert not [m for m in (body, name, cwd) if m.encode() in data]
    assert not target.with_name(target.name + "-wal").exists()
