"""Extraction of one Claude Code line (spec §3.1, §6.5; plan PR 2 §5.4): pure, on bytes.

A marker put in a forbidden field never leaves `parse_line`, by any of its outputs.
"""

from datetime import timedelta

import pytest
from claude_sessions_support import (
    NOW,
    assistant,
    encode,
    ghp,
    marker,
    new_id,
    stamp,
    text,
    title,
    user,
)

from nexus.conversations.parse_claude import parse_line
from nexus.secrets import REDACTED

STEM = new_id()
NOT_BEFORE = NOW - timedelta(days=31)


def parse(line, *, at_file_start=False, crlf=False):
    data = encode(line, eol=b"\r" if crlf else b"")
    return parse_line(data, at_file_start=at_file_start, stem=STEM, not_before=NOT_BEFORE)


def leaks(result, value: str) -> bool:
    outputs = (result.message.body if result.message else "", result.title or "",
               result.workspace or "", result.git_branch or "", result.reason or "")
    return any(value in out for out in outputs)


def with_session(line: dict) -> dict:
    return dict(line, sessionId=STEM)


def test_a_human_user_line_is_kept_as_loic():
    line = with_session(user("bonjour Claude"))

    got = parse(line)

    assert got.kind == "message"
    assert got.message.author == "loic" and got.message.role == "user"
    assert got.message.body == "bonjour Claude"
    assert got.message.external_id == line["uuid"]
    assert got.message.at == NOW and not got.session_id_differs


def test_a_user_line_without_origin_is_unknown():
    assert parse(with_session(user("salut", origin=None))).message.author == "unknown"


@pytest.mark.parametrize("origin", [{"kind": "task-notification"}, "loic", {"kind": 1}, [], {}])
def test_any_other_origin_is_skipped(origin):
    got = parse(with_session(user("notif", origin=origin)))
    assert (got.kind, got.reason) == ("skipped", "origin")


def test_a_tool_result_line_is_skipped_and_its_payload_never_read():
    secret = marker()
    line = with_session(user([{"type": "tool_result", "content": secret}, text("ok")],
                             toolUseResult={"originalFile": secret}))

    got = parse(line)

    assert (got.kind, got.reason) == ("skipped", "tool_result")
    assert not leaks(got, secret)


def test_text_blocks_of_a_user_list_are_joined():
    got = parse(with_session(user([text("un"), text("deux")])))
    assert got.message.body == "un\n\ndeux"


def test_an_assistant_line_keeps_only_its_text_blocks():
    secret = marker()
    blocks = [{"type": "thinking", "thinking": secret}, text("réponse"),
              {"type": "tool_use", "name": "Bash", "input": {"command": secret}},
              {"type": "server_tool_use", "input": {"q": secret}},
              {"type": "advisor_tool_result", "content": secret}, text("suite")]

    got = parse(with_session(assistant(blocks)))

    assert got.message.body == "réponse\n\nsuite"
    assert got.message.author == "claude" and got.message.model == "claude-opus-5-5"
    assert not leaks(got, secret)


def test_an_assistant_line_with_thinking_only_is_empty():
    got = parse(with_session(assistant([{"type": "thinking", "thinking": "hmm"}])))
    assert (got.kind, got.reason) == ("skipped", "empty")


def test_sidechain_and_meta_are_skipped_only_when_true():
    assert parse(with_session(user("x", isSidechain=True))).reason == "sidechain"
    assert parse(with_session(user("x", isMeta=True))).reason == "meta"
    assert parse(with_session(user("x", isMeta="true"))).kind == "message"
    assert parse(with_session(user("x", isSidechain="true"))).kind == "message"


@pytest.mark.parametrize("kind", ["api-request-blob", "attachment", "session-owner",
                                  "cost-state", "system", "type-inventé"])
def test_other_types_are_ignored_and_never_read(kind):
    secret = marker()
    line = {"type": kind, "uuid": new_id(), "timestamp": stamp(NOW), "sessionId": STEM,
            "systemPrompt": secret, "accountUuid": secret, "content": secret, "cwd": secret,
            "message": {"role": "user", "content": secret}}

    got = parse(line)

    assert (got.kind, got.message, got.title, got.workspace) == ("ignored", None, None, None)
    assert not leaks(got, secret)


def test_titles_are_masked_with_their_kind():
    secret = ghp()
    custom = parse(title(f"Titre {secret}"))
    ai = parse(title("Titre IA", kind="ai-title"))

    assert (custom.kind, custom.title, custom.title_kind) == (
        "title", f"Titre {REDACTED}", "custom")
    assert (ai.title, ai.title_kind) == ("Titre IA", "ai")
    assert parse({"type": "custom-title", "customTitle": 3}).kind == "ignored"


@pytest.mark.parametrize("change", [
    {"uuid": None}, {"uuid": 3}, {"uuid": "ABCDEF00-0000-4000-8000-000000000000"},
    {"uuid": new_id() + "0"}, {"uuid": ghp()}, {"timestamp": None},
    {"timestamp": "2026-11-27T12:00:00"}, {"timestamp": "hier"}, {"message": None},
    {"message": {"role": "assistant", "content": "x"}}, {"message": "x"},
])
def test_a_missing_or_invalid_required_field_is_bad(change):
    line = with_session(user("x"))
    for key, value in change.items():
        if value is None:
            line.pop(key)
        else:
            line[key] = value

    got = parse(line)

    assert (got.kind, got.reason) == ("bad", "field")
    assert got.message is None


def test_undecodable_bytes_invalid_json_and_non_objects_are_bad():
    assert parse(b'{"type": "user", "x": "\xff"}').reason == "utf8"
    assert parse(b'{"type": ').reason == "json"
    assert parse(b"[1, 2]").reason == "not_object"
    assert parse(b"").kind == "ignored"


def test_a_bom_is_only_admitted_at_the_start_of_the_file():
    data = b"\xef\xbb\xbf" + encode(with_session(user("x")), eol=b"")

    assert parse(data, at_file_start=True).kind == "message"
    assert parse(data).kind == "bad"


def test_a_line_older_than_the_retention_is_never_kept():
    got = parse(with_session(user("vieux", at=NOT_BEFORE - timedelta(seconds=1))))
    assert (got.kind, got.reason) == ("skipped", "old")


def test_a_crlf_line_is_parsed():
    assert parse(with_session(user("x")), crlf=True).kind == "message"


def test_a_synthetic_assistant_line_is_skipped():
    got = parse(with_session(assistant([text("No response requested.")], model="<synthetic>")))
    assert (got.kind, got.reason) == ("skipped", "synthetic")


def test_a_foreign_session_id_is_kept_and_flagged():
    got = parse(user("x", session=new_id()))
    assert got.kind == "message" and got.session_id_differs


def test_session_fields_are_masked():
    secret = ghp()
    got = parse(with_session(user("x", cwd=f"F:\\Projet\\{secret}", branch=f"feat/{secret}")))
    assert got.workspace == f"F:\\Projet\\{REDACTED}"
    assert got.git_branch == f"feat/{REDACTED}"


def test_microseconds_and_offsets_are_parsed_as_aware():
    line = with_session(user("x"))
    line["timestamp"] = "2026-11-27T13:00:00.123456+01:00"
    got = parse(line)
    assert got.message.at == NOW.replace(microsecond=123456)


@pytest.mark.parametrize("kind", [[], {}, ["user"], {"user": 1}, 7, None])
def test_a_type_that_is_not_a_string_is_ignored_without_raising(kind):
    assert parse({"type": kind, "message": {"role": "user", "content": "x"}}).kind == "ignored"
