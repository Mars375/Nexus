"""A Claude Code pass against files that move (spec §5.1, §6.2, §6.6; plan PR 2 §5.6): the
descriptor, rotation, growth, substitution and presence. Sessions are invented, under `tmp_path`.
"""

import os
import threading
from datetime import timedelta

import pytest
from claude_sessions_support import NOW, conversation, migrated, touch, user, write_session
from conversations_support import junction, needs_windows, recording, under

from nexus.conversations import ingest, masking, paths
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


def run(db, root, *, state=None, now=NOW, **kwargs):
    return ingest.claude_pass(db.factory, root, POLICY, stopping=threading.Event(),
                              state=state or ProcessState(), now=now, **kwargs)


def count(db) -> int:
    return db.scalar("SELECT count(*) FROM conversation_messages")


def stale_listing(monkeypatch, root):
    """The listing as it was before the test touches the files (a race after the lstat)."""
    listing = paths.iter_claude(paths.check_root(root, "claude-code"))
    monkeypatch.setattr(paths, "iter_claude", lambda _root: listing)
    return listing


def test_the_descriptor_is_closed_before_any_masking(db, root, monkeypatch):
    write_session(root, conversation(3))
    order, opened = [], set()
    real_open, real_close, real_redact = paths.open_candidate, os.close, masking.redact

    def open_candidate(candidate):
        fd = real_open(candidate)
        opened.add(fd)
        return fd

    def close(fd):
        if fd in opened:
            order.append("close")
        return real_close(fd)

    def redact(text):
        order.append("redact")
        return real_redact(text)

    monkeypatch.setattr(paths, "open_candidate", open_candidate)
    monkeypatch.setattr(os, "close", close)
    monkeypatch.setattr(masking, "redact", redact)

    run(db, root)

    assert order[0] == "close" and "redact" in order


@needs_windows
def test_a_session_can_be_replaced_and_removed_right_after_a_pass(db, root):
    path = write_session(root, conversation(3))
    run(db, root)

    replacement = path.with_suffix(".tmp")
    replacement.write_bytes(path.read_bytes())
    os.replace(replacement, path)
    os.remove(path)
    assert not path.exists()


def test_a_truncated_file_is_read_again_from_zero(db, root):
    path = write_session(root, conversation(6))
    run(db, root)
    path.write_bytes(path.read_bytes()[: len(path.read_bytes()) // 3])
    with open(path, "ab") as handle:
        handle.write(b'{"type": "user"}\n')
    touch(path, NOW + timedelta(seconds=5))

    status = run(db, root)

    assert status.reads_from_zero == 1
    assert count(db) == 6  # what disappeared stays until the purge


def test_a_same_size_rewrite_is_caught_by_the_head_digest(db, root):
    path = write_session(root, conversation(4, body="avant"))
    run(db, root)
    data = path.read_bytes().replace(b"avant", b"apres").replace(b"-8000-0000", b"-9000-0000")
    with open(path, "r+b") as handle:  # in place: the same file id and the same size
        handle.write(data)
    assert len(data) == path.stat().st_size
    touch(path, NOW + timedelta(seconds=5))

    status = run(db, root)

    assert status.reads_from_zero == 1
    assert {r[0].split()[0] for r in db.rows("SELECT body FROM conversation_messages")} == {
        "avant", "apres"}


def test_a_small_file_that_grows_is_never_reset(db, root):
    session = "00000000-0000-4000-8000-00000000aaaa"
    lines = conversation(8)
    write_session(root, lines[:2], session=session)
    state, from_zero = ProcessState(), 0
    for step in range(1, 4):
        from_zero += run(db, root, state=state).reads_from_zero
        write_session(root, lines[2 * step:2 * step + 2], session=session, append=True,
                      mtime=NOW + timedelta(seconds=step))
    from_zero += run(db, root, state=state).reads_from_zero

    assert (root / "-F-Projet-Exemple" / f"{session}.jsonl").stat().st_size < 4096
    assert from_zero == 1 and count(db) == 8


def test_bytes_appended_during_the_read_are_read_at_the_next_pass(db, root, monkeypatch):
    session = "00000000-0000-4000-8000-00000000bbbb"
    lines = conversation(4)
    write_session(root, lines[:2], session=session)
    stale_listing(monkeypatch, root)
    write_session(root, lines[2:], session=session, append=True, mtime=NOW + timedelta(1))

    run(db, root)
    assert count(db) == 2
    monkeypatch.undo()
    run(db, root)
    assert count(db) == 4


def test_a_file_removed_after_the_listing_is_counted_and_the_pass_goes_on(db, root, monkeypatch):
    gone = write_session(root, conversation(2), mtime=NOW)
    write_session(root, conversation(3), mtime=NOW - timedelta(hours=1))
    stale_listing(monkeypatch, root)
    gone.unlink()

    status = run(db, root)

    assert status.codes["file_unreadable"] == 1 and count(db) == 3


def test_a_file_substituted_after_its_lstat_is_refused(db, root, monkeypatch):
    path = write_session(root, conversation(2))
    stale_listing(monkeypatch, root)
    other = path.with_suffix(".new")
    other.write_bytes(path.read_bytes())
    os.replace(other, path)

    status = run(db, root)

    assert status.codes["substituted"] == 1 and status.bytes_read == 0
    assert db.scalar("SELECT count(*) FROM conversation_cursors") == 0


def test_a_session_gone_from_the_source_is_missing_after_two_complete_listings(db, root):
    path = write_session(root, conversation(2))
    state = ProcessState()
    run(db, root, state=state)
    saved = path.read_bytes()
    path.unlink()

    run(db, root, state=state, now=NOW + timedelta(minutes=1))
    assert db.scalar("SELECT missing_since FROM conversations") is None
    run(db, root, state=state, now=NOW + timedelta(minutes=2))
    assert db.scalar("SELECT missing_since FROM conversations") is not None

    path.write_bytes(saved)
    touch(path, NOW)
    run(db, root, state=state, now=NOW + timedelta(minutes=3))
    assert db.scalar("SELECT missing_since FROM conversations") is None


def test_an_incomplete_listing_or_a_refused_root_marks_nothing_absent(db, root, monkeypatch):
    path = write_session(root, conversation(2))
    write_session(root, conversation(2), slug="autre")
    state = ProcessState()
    run(db, root, state=state)
    path.unlink()
    real = paths._names

    def unreadable(folder, listing, *, is_root):
        if folder.name == "autre":
            listing.skipped_dirs += 1
            listing.codes["level_dir_unreadable"] += 1
            return []
        return real(folder, listing, is_root=is_root)

    monkeypatch.setattr(paths, "_names", unreadable)
    for minute in (1, 2):
        run(db, root, state=state, now=NOW + timedelta(minutes=minute))
    monkeypatch.undo()
    renamed = root.with_name("projets")
    root.rename(renamed)
    for minute in (3, 4):
        status = run(db, root, state=state, now=NOW + timedelta(minutes=minute))

    assert (status.state, status.code) == ("unavailable", "root_missing")
    assert db.scalar("SELECT count(*) FROM conversations WHERE missing_since IS NOT NULL") == 0


@needs_windows
def test_a_root_swapped_for_a_junction_after_a_pass_is_refused(db, root, tmp_path):
    write_session(root, conversation(2))
    run(db, root)
    elsewhere = tmp_path / "ailleurs" / "projects"
    write_session(elsewhere, [user("ailleurs")])
    root.rename(root.with_name("old"))
    junction(root, elsewhere)

    with recording() as events:
        status = run(db, root)

    assert status.state == "unavailable" and status.code in ("root_is_link", "root_substituted")
    assert not under(events, elsewhere)
    assert count(db) == 2


def test_a_same_size_rewrite_during_a_resumed_read_is_read_again_from_zero(db, root,
                                                                           monkeypatch):
    session = "11111111-2222-4333-a444-555555555555"
    lines = conversation(4, body="avant")
    path = write_session(root, lines[:2], session=session)
    run(db, root)
    write_session(root, lines[2:], session=session, append=True, mtime=NOW + timedelta(seconds=1))
    data = path.read_bytes().replace(b"avant", b"apres").replace(b"-8000-0000", b"-9000-0000")
    real = ingest.read_tail

    def rewritten_first(fd, **kwargs):  # in place, between the digest and the read
        with open(path, "r+b") as handle:
            handle.write(data)
        return real(fd, **kwargs)

    monkeypatch.setattr(ingest, "read_tail", rewritten_first)
    run(db, root)
    monkeypatch.undo()
    assert len(data) == path.stat().st_size
    touch(path, NOW + timedelta(seconds=5))

    status = run(db, root)

    assert status.reads_from_zero == 1
    bodies = [r[0] for r in db.rows("SELECT body FROM conversation_messages")]
    assert sorted(b for b in bodies if b.startswith("apres")) == [f"apres {i}" for i in range(4)]
