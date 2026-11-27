"""The masking factory (spec §7.1, ADR-025 D5): mask the whole text, then cut, never the reverse.

`ParsedMessage` is only built by `make_message`; no raw text reaches the index.
"""

import json
import sqlite3
from datetime import datetime

import pytest
from claude_sessions_support import NOW, ghp, migrated

from nexus.conversations import masking
from nexus.conversations.masking import BODY_MAX, ParsedMessage, cut, make_message, mask_field
from nexus.secrets import REDACTED


def message(text: object = "bonjour", **overrides) -> ParsedMessage | None:
    fields = {"external_id": "m1", "role": "user", "author": "loic", "at": NOW, "text": text}
    fields.update(overrides)
    return make_message(**fields)


def insert(tmp_path, parsed: ParsedMessage) -> None:
    db = migrated(tmp_path)
    try:
        with db.engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO conversations (source, external_id, message_count, measured_at) "
                "VALUES ('claude-code', 's', 0, '2026-11-27T12:00:00+00:00')")
            conn.exec_driver_sql(
                "INSERT INTO conversation_messages (conversation_id, external_id, role, author, "
                "at, body, truncated, redacted) VALUES (1, ?, 'user', 'loic', ?, ?, 0, 0)",
                (parsed.external_id, "2026-11-27T12:00:00+00:00", parsed.body))
    finally:
        db.engine.dispose()


def test_a_secret_across_the_16000th_character_is_masked_whole():
    secret = ghp()
    text = ("réunion " * 2000)[:15989] + " " + secret + " fin"
    assert text.index(secret) == 15990

    parsed = message(text)

    assert secret[:4] not in parsed.body and "A" * 5 not in parsed.body
    assert len(parsed.body) <= BODY_MAX
    assert parsed.truncated and parsed.redacted


@pytest.mark.parametrize("shift", range(1, 10))
def test_a_cut_never_lands_inside_a_redaction_mark(shift):
    masked = "a" * (BODY_MAX - shift) + REDACTED + " suite"

    body, truncated = cut(masked, BODY_MAX)

    assert truncated
    assert body == "a" * (BODY_MAX - shift)
    assert not body.endswith(REDACTED[:shift])


def test_the_limit_counts_characters_not_bytes():
    exact = message("é" * BODY_MAX)
    over = message("é" * (BODY_MAX + 1))

    assert len(exact.body) == BODY_MAX and not exact.truncated
    assert len(over.body) == BODY_MAX and over.truncated


def test_nul_and_snippet_marks_are_removed_and_the_body_passes_the_check(tmp_path):
    parsed = message("a\x00b\x02c\x03d")

    assert parsed.body == "abcd"
    insert(tmp_path, parsed)


def test_a_lone_surrogate_becomes_a_replacement_character(tmp_path):
    text = json.loads('"a\\ud800b"')
    with pytest.raises(UnicodeEncodeError), sqlite3.connect(":memory:") as conn:
        conn.execute("SELECT ?", (text,))  # why the factory replaces it

    parsed = message(text)

    assert parsed.body == "a\ufffdb"
    insert(tmp_path, parsed)


def test_empty_text_gives_none_and_a_lone_redaction_is_kept():
    assert message("") is None
    assert message("  \n\t ") is None
    kept = message(f"  {ghp()}  ")
    assert kept.body == REDACTED and kept.redacted
    assert not message("bonjour").redacted


def test_session_fields_are_masked_then_cut():
    secret = ghp()
    assert mask_field(f"titre {secret}", 200) == f"titre {REDACTED}"
    assert len(mask_field("t" * 300, 200)) == 200
    assert len(mask_field("F:\\" + "d" * 600, 500)) == 500
    assert mask_field(f"feat/{secret}", 200) == f"feat/{REDACTED}"
    assert mask_field(42, 200) is None
    assert mask_field(None, 200) is None
    assert mask_field("   ", 200) is None


@pytest.mark.parametrize("overrides", [
    {"role": "system"}, {"author": ""}, {"author": "x" * 33},
    {"at": datetime(2026, 11, 27, 12, 0)}, {"text": 42},
])
def test_invalid_fields_raise(overrides):
    with pytest.raises(ValueError):
        message(**({"text": "bonjour"} | overrides))


@pytest.mark.parametrize(("model", "kept"), [
    ("claude-opus-5-5", "claude-opus-5-5"), ("x y", None), ("a" * 65, None),
    ("<synthetic>", None), (None, None), (7, None),
])
def test_model_is_kept_only_when_it_matches_the_whitelist(model, kept):
    assert message("bonjour", model=model).model == kept


def test_parsed_message_cannot_be_built_outside_the_factory():
    with pytest.raises(ValueError):
        ParsedMessage(external_id="m", role="user", author="loic", at=NOW, body="brut",
                      truncated=False, redacted=False, model=None)
    assert masking.TITLE_MAX == 200 and masking.WORKSPACE_MAX == 500
