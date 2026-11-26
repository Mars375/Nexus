"""Models of the conversation index (ADR-025): metadata, the exact-name FTS filter, handles,
instants, and the FTS5 probe."""

import sqlite3
from datetime import UTC, datetime

import pytest
from conftest import ActorClient, tailscale_json
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus import backup, migrate
from nexus.app import create_app
from nexus.conversations import models as conv_models
from nexus.conversations.models import Conversation, ConversationCursor, ConversationMessage
from nexus.db import Base, make_engine

MEASURED = datetime(2026, 11, 11, 9, tzinfo=UTC)


def test_the_conversation_tables_are_registered_on_the_metadata():
    import nexus.models  # noqa: F401

    tables = set(Base.metadata.tables)
    assert {"conversations", "conversation_messages", "conversation_cursors"} <= tables
    assert not tables & conv_models.FTS_TABLES


def test_include_object_hides_only_the_fts_tables():
    def included(name, type_="table"):
        return conv_models.include_object(None, name, type_, True, None)

    assert conv_models.FTS_TABLES == {
        "conversation_fts", "conversation_fts_data", "conversation_fts_idx",
        "conversation_fts_docsize", "conversation_fts_config",
    }
    assert not any(included(name) for name in conv_models.FTS_TABLES)
    for name in ("conversations", "conversation_messages", "conversation_cursors",
                 "conversation_fts_extra"):
        assert included(name)
    assert included("conversation_fts", "index")


def test_refs_are_handles():
    assert Conversation(id=7).ref == "nx-conv-7"
    assert ConversationMessage(id=12).ref == "nx-msg-12"


@pytest.fixture
def session(settings):
    settings.data_dir.mkdir(parents=True)
    migrate.upgrade(settings.db_url)
    engine = make_engine(settings.db_url)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def test_instants_round_trip_across_the_fall_back_hour(session):
    later = datetime.fromisoformat("2026-10-25T02:15:00+01:00")
    earlier = datetime.fromisoformat("2026-10-25T02:30:00+02:00")
    far = datetime.fromisoformat("2999-12-31T23:59:59.999999+00:00")
    conversation = Conversation(source="claude-code", external_id="s1", message_count=2,
                                measured_at=MEASURED, last_message_at=far)
    session.add(conversation)
    session.flush()
    for external_id, at in (("m1", later), ("m2", earlier)):
        session.add(ConversationMessage(
            conversation_id=conversation.id, external_id=external_id, role="user",
            author="loic", at=at, body="bonjour", truncated=False, redacted=False,
        ))
    session.add(ConversationCursor(source="claude-code", path_key="slug/a.jsonl", state="ok",
                                   covered_since=earlier, updated_at=MEASURED))
    session.commit()
    session.expire_all()

    rows = session.scalars(select(ConversationMessage).order_by(ConversationMessage.at)).all()
    assert [m.external_id for m in rows] == ["m2", "m1"]
    assert rows[1].at.astimezone(UTC) == later.astimezone(UTC)
    assert session.get(Conversation, conversation.id).last_message_at.astimezone(UTC) == far
    cursor = session.get(ConversationCursor, ("claude-code", "slug/a.jsonl"))
    assert cursor.covered_since.astimezone(UTC) == earlier.astimezone(UTC)
    assert cursor.byte_offset == 0


class FakeConnection:
    def __init__(self, error=None):
        self.error = error
        self.closed = False

    def execute(self, _sql):
        if self.error:
            raise self.error

    def close(self):
        self.closed = True


def test_require_fts5_passes_here_and_fails_closed():
    conv_models.require_fts5()

    ok = FakeConnection()
    conv_models.require_fts5(connect=lambda _path: ok)
    assert ok.closed

    missing = FakeConnection(sqlite3.OperationalError("no such module: fts5"))
    with pytest.raises(RuntimeError) as exc:
        conv_models.require_fts5(connect=lambda _path: missing)
    assert str(exc.value) == "SQLite sans FTS5"
    assert exc.value.__cause__ is None and exc.value.__suppress_context__
    assert missing.closed


def test_startup_refuses_without_fts5_before_touching_disk(settings, monkeypatch):
    def no_fts5():
        raise RuntimeError(conv_models.NO_FTS5)

    copies = []
    monkeypatch.setattr(conv_models, "require_fts5", no_fts5)
    monkeypatch.setattr(backup, "backup", lambda *a, **k: copies.append(a))

    with pytest.raises(RuntimeError, match="^SQLite sans FTS5$"):
        with ActorClient(create_app(settings, nodes_runner=tailscale_json)):
            pass

    assert not settings.data_dir.exists()
    assert copies == []
