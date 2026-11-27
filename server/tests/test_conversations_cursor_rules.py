"""The cursor decision (spec §6.1, §6.2; plan PR 2 §5.5): read, skip or mark `skipped_old`."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nexus.conversations.cursor_rules import Plan, Policy, plan
from nexus.conversations.models import CURSOR_STATES, ConversationCursor
from nexus.conversations.paths import Candidate

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
POLICY = Policy.at(NOW, since_days=31, retention_days=31)
RET = POLICY.retention_start


def candidate(*, size=1000, mtime=NOW - timedelta(hours=1), ident=(1, 2)) -> Candidate:
    return Candidate("slug/x.jsonl", Path("x"), ident, size, int(mtime.timestamp() * 1e9))


def cursor(state="ok", *, size=1000, mtime=NOW - timedelta(hours=1), file_id="1:2",
           offset=1000, covered=RET) -> ConversationCursor:
    return ConversationCursor(
        source="claude-code", path_key="slug/x.jsonl", file_id=file_id, size=size,
        mtime_ns=int(mtime.timestamp() * 1e9), byte_offset=offset, head_sha256="0" * 64,
        covered_since=covered, state=state, updated_at=NOW)


FROM_ZERO = Plan("read", covered_since=RET)
OLD = NOW - timedelta(days=40)
CHANGED = {"size": 2000}


@pytest.mark.parametrize(("cur", "cand", "expected"), [
    # 1: outside the window, no cursor or skipped_old -> never opened
    (None, {"mtime": OLD}, Plan("mark_old")),
    (cursor("skipped_old", covered=None), {"mtime": OLD}, Plan("mark_old")),
    # 2: no cursor or skipped_old, inside the window -> from 0
    (None, {}, FROM_ZERO),
    (cursor("skipped_old", covered=None), {}, FROM_ZERO),
    # 3: covered_since null or more recent than the threshold, any state
    (cursor("ok", covered=None), {}, FROM_ZERO),
    # 4: another file, or truncated
    (cursor("ok"), {"ident": (1, 3)}, FROM_ZERO),
    (cursor("ok", offset=1000), {"size": 999}, FROM_ZERO),
    # 5: unchanged ok / too_large
    (cursor("ok"), {}, Plan("skip")),
    (cursor("too_large"), {}, Plan("skip")),
    # 6: unchanged, a skip that reached the end
    (cursor("skipping", offset=1000), {}, Plan("skip")),
    # 7: unchanged unreadable
    (cursor("unreadable"), {}, Plan("skip")),
    # 8: partial or skipping, resumed at the offset
    (cursor("partial", offset=400), {}, Plan("read", 400, False, RET, True)),
    (cursor("skipping", offset=400), CHANGED, Plan("read", 400, True, RET, True)),
    # 9: an ok file that grew
    (cursor("ok"), CHANGED, Plan("read", 1000, False, RET, True)),
    (cursor("too_large"), CHANGED, Plan("read", 1000, False, RET, True)),
])
def test_rules_in_order(cur, cand, expected):
    assert plan(cur, candidate(**cand), POLICY) == expected


@pytest.mark.parametrize("state", ["partial", "skipping", "ok", "too_large", "unreadable"])
def test_a_covered_since_more_recent_than_the_threshold_reads_from_zero_in_every_state(state):
    recent = RET + timedelta(days=1)
    assert plan(cursor(state, covered=recent, offset=400), candidate(), POLICY) == FROM_ZERO


def test_a_skipped_old_file_entering_a_wider_window_is_read_from_zero():
    wider = Policy.at(NOW, since_days=60, retention_days=60)
    got = plan(cursor("skipped_old", covered=None), candidate(mtime=OLD), wider)
    assert got == Plan("read", covered_since=wider.retention_start)


def test_an_ok_file_with_covered_since_equal_to_the_threshold_is_skipped():
    assert plan(cursor("ok", covered=RET), candidate(), POLICY) == Plan("skip")


def test_a_future_mtime_is_inside_the_window():
    assert plan(None, candidate(mtime=NOW + timedelta(days=2)), POLICY) == FROM_ZERO


def test_a_finished_skip_resumes_once_the_file_grows():
    assert plan(cursor("skipping"), candidate(), POLICY) == Plan("skip")
    assert plan(cursor("skipping"), candidate(size=1500), POLICY) == Plan(
        "read", 1000, True, RET, True)


def test_unreadable_is_judged_again_when_it_changes_and_by_rule_3_first():
    recent = RET + timedelta(hours=1)
    assert plan(cursor("unreadable", covered=recent), candidate(), POLICY) == FROM_ZERO
    assert plan(cursor("unreadable"), candidate(ident=(9, 9)), POLICY) == FROM_ZERO
    assert plan(cursor("unreadable"), candidate(size=10), POLICY) == FROM_ZERO
    assert plan(cursor("unreadable"), candidate(size=5000), POLICY) == FROM_ZERO


def test_an_ok_or_partial_file_leaving_the_window_is_not_marked_old():
    assert plan(cursor("ok", mtime=OLD), candidate(mtime=OLD), POLICY) == Plan("skip")
    got = plan(cursor("partial", offset=10, mtime=OLD), candidate(mtime=OLD), POLICY)
    assert got.action == "read" and got.start == 10


def test_every_state_of_the_model_is_handled():
    for state in CURSOR_STATES:
        assert plan(cursor(state), candidate(), POLICY).action in ("skip", "read")
