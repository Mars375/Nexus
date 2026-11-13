"""Pure translation of `claude -p --output-format stream-json` lines (spec 2026-11-11, §5.2).

Tests 1 to 12 of the spec.
"""

import json

import pytest
from claude_code_support import (
    ASSISTANT_BASH,
    ASSISTANT_EDIT,
    ASSISTANT_TEXT,
    INIT_BARE,
    INIT_BYPASS,
    INIT_EXTRA_TOOL,
    INIT_MCP,
    INIT_MISSING_TOOL,
    INIT_OK,
    RESULT_DENIALS,
    RESULT_ERROR_EXEC,
    RESULT_IS_ERROR,
    RESULT_OK,
    TOOLS,
    USER_TOOL_RESULT,
    assistant,
    init,
    line,
)

from nexus.adapters.claude_code_translate import translate_line


def kinds(text: str) -> list[str]:
    return [fact.kind for fact in translate_line(text)]


# --- 1: lines that say nothing --------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "not json", "[]", "null", "3", '""', "{}", '{"type": 3}', line(type="mystery"),
    line(type="rate_limit_event", rate_limit_info={}),
    line(type="system", subtype="vcs_state_changed"),
    line(type="system", subtype="thinking_tokens"), line(type="system"),
    "",
])
def test_lines_without_a_fact_give_nothing(text):
    assert translate_line(text) == ()


# --- 2, 3, 4: the isolation check on system/init --------------------------------------------------


def test_a_conform_init_claims_the_session_with_the_resolved_model():
    (fact,) = translate_line(INIT_OK)
    assert fact.kind == "claimed" and fact.payload == {"model": "claude-sonnet-5-5"}


def test_the_five_tools_are_compared_as_a_set():
    shuffled = init(tools=["Write", "Grep", "Read", "Edit", "Glob"])
    assert kinds(shuffled) == ["claimed"]


@pytest.mark.parametrize("text", [INIT_MCP, INIT_EXTRA_TOOL, INIT_MISSING_TOOL, INIT_BYPASS])
def test_a_departure_from_the_isolation_is_a_breach_in_fixed_words(text):
    (fact,) = translate_line(text)
    assert fact.kind == "breach"
    assert fact.body.startswith("isolation non respectée")
    assert "Bash" not in fact.body and "bypass" not in fact.body.lower()
    assert " m " not in fact.body  # the name of the MCP server is not copied


def test_the_breach_words_tell_the_four_causes_apart():
    bodies = {translate_line(t)[0].body for t in
              (INIT_MCP, INIT_EXTRA_TOOL, INIT_MISSING_TOOL, INIT_BYPASS)}
    assert len(bodies) == 4


@pytest.mark.parametrize("text", [
    INIT_BARE,
    init(mcp_servers=...), init(mcp_servers="none"), init(mcp_servers={}),
    init(tools=...), init(tools="Read"), init(tools=[*TOOLS, 3]),
    init(permissionMode=...), init(permissionMode=3),
])
def test_a_missing_or_mistyped_field_leaves_the_isolation_unknown(text):
    (fact,) = translate_line(text)
    assert fact.kind == "isolation_unknown"


# --- 5, 6: assistant and user messages ------------------------------------------------------------


def test_an_assistant_message_tells_its_text_and_its_file_changes():
    text = assistant(
        {"type": "text", "text": "Je modifie."},
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/a.py"}},
        {"type": "tool_use", "name": "Write", "input": {"file_path": "b.txt", "content": "x"}},
    )
    facts = translate_line(text)
    assert [f.kind for f in facts] == ["working", "progress", "progress", "progress"]
    assert [f.subject for f in facts[1:]] == [
        "Message de Claude Code", "Fichier modifié", "Fichier modifié"]
    assert [f.body for f in facts[1:]] == ["Je modifie.", "src/a.py", "b.txt"]


def test_reading_tools_unknown_tools_and_thinking_tell_nothing_more():
    reads = assistant(
        {"type": "tool_use", "name": "Read", "input": {"file_path": "a"}},
        {"type": "tool_use", "name": "Grep", "input": {"pattern": "x"}},
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},  # judged at init
        {"type": "thinking", "thinking": "hmm"},
    )
    assert kinds(reads) == ["working"]
    assert kinds(ASSISTANT_BASH) == ["working"]


@pytest.mark.parametrize("name", [["Edit"], {"Edit": 1}, None, 3, True])
def test_a_tool_name_of_the_wrong_type_never_raises(name):
    text = assistant({"type": "tool_use", "name": name, "input": {"file_path": "a.txt"}})
    assert kinds(text) == ["working"]


def test_a_file_change_without_a_usable_path_adds_nothing():
    for bad in ({}, {"file_path": 3}, {"file_path": ""}):
        text = assistant({"type": "tool_use", "name": "Edit", "input": bad})
        assert kinds(text) == ["working"]
    assert kinds(assistant({"type": "tool_use", "name": "Edit"})) == ["working"]


def test_a_message_with_unexpected_content_is_still_only_working():
    for message in (None, [], {"content": "text"}, {"content": [3, None, "x"]}):
        assert kinds(line(type="assistant", message=message)) == ["working"]
    assert kinds(ASSISTANT_TEXT) == ["working", "progress"]
    assert kinds(ASSISTANT_EDIT) == ["working", "progress"]


# --- 7: tool results are never read ---------------------------------------------------------------


def test_a_tool_result_is_never_read_into_a_fact():
    secret = "ghp_" + "A" * 36
    text = line(type="user", message={"content": [
        {"type": "tool_result", "content": f"RAW-OUTPUT-NEVER-STORED {secret}"}]})
    assert translate_line(text) == ()
    assert translate_line(USER_TOOL_RESULT) == ()


# --- 8, 9, 10: the result line --------------------------------------------------------------------


def test_a_strict_success_finishes_with_integers_only():
    (fact,) = translate_line(RESULT_OK)
    assert fact.kind == "finished"
    assert fact.payload == {"num_turns": 2, "duration_ms": 1500}
    odd = line(type="result", subtype="success", is_error=False, num_turns=True, duration_ms="9")
    (fact,) = translate_line(odd)
    assert fact.kind == "finished" and fact.payload == {}


@pytest.mark.parametrize("fields", [
    {"is_error": "false"}, {"is_error": 0}, {"is_error": None}, {},
    {"is_error": False, "subtype": "success_but_odd"},
])
def test_anything_but_a_strict_success_is_not_a_success(fields):
    text = line(type="result", **({"subtype": "success"} | fields))
    assert kinds(text) == ["failed"]


def test_a_result_flagged_as_error_fails_with_the_masked_message():
    secret = "ghp_" + "A" * 36
    text = line(type="result", subtype="success", is_error=True,
                result=f"Limite atteinte, reprise à 18h {secret}")
    (fact,) = translate_line(text)
    assert fact.kind == "failed"
    assert "Limite atteinte, reprise à 18h" in fact.body and secret not in fact.body
    assert translate_line(RESULT_IS_ERROR)[0].body == "Limite d'usage atteinte"


def test_error_lines_keep_only_the_strings_of_errors():
    text = line(type="result", subtype="error_during_execution", is_error=True,
                errors=["première", 3, None, {"x": 1}, "seconde"])
    (fact,) = translate_line(text)
    assert fact.kind == "failed" and fact.body == "première; seconde"
    assert translate_line(RESULT_ERROR_EXEC)[0].body == "boom"


def test_an_error_without_detail_names_only_a_known_subtype():
    known = line(type="result", subtype="error_max_turns", is_error=True)
    assert translate_line(known)[0].body == "échec sans détail (error_max_turns)"
    secret = "ghp_" + "A" * 36
    unknown = line(type="result", subtype=f"error_{secret}", is_error=True)
    body = translate_line(unknown)[0].body
    assert body == "échec sans détail" and secret not in body


# --- 11: permission denials -----------------------------------------------------------------------


def test_permission_denials_name_the_tools_and_never_their_input():
    secret = "ghp_" + "A" * 36
    text = line(type="result", subtype="success", is_error=False, permission_denials=[
        {"tool_name": "Bash", "tool_input": {"command": f"echo {secret}"}},
        {"tool_name": "Bash", "tool_input": {}}, {"tool_name": "Edit"}, "odd", {"tool_name": 3},
    ])
    facts = translate_line(text)
    assert [f.kind for f in facts] == ["finished", "progress"]
    assert facts[1].subject == "Outils refusés" and facts[1].body == "Bash, Edit"
    assert secret not in json.dumps([f.__dict__ for f in facts])
    assert [f.kind for f in translate_line(RESULT_DENIALS)] == ["finished", "progress"]


def test_an_empty_or_mistyped_denial_list_adds_nothing():
    for denials in ([], "none", {}, [{"tool_name": ""}]):
        text = line(type="result", subtype="success", is_error=False, permission_denials=denials)
        assert kinds(text) == ["finished"]


# --- 12: texts ------------------------------------------------------------------------------------


def test_odd_texts_never_make_an_empty_fact():
    secret = "ghp_" + "A" * 36
    for text in ("", "   ", secret):
        assert kinds(assistant({"type": "text", "text": text})) == ["working"]
    only_secret = translate_line(assistant({"type": "text", "text": secret}))
    assert [f.kind for f in only_secret] == ["working"]
    half = translate_line(assistant({"type": "text", "text": "a\ud800b"}))
    assert half[1].body is not None and half[1].body.encode("utf-8")
    assert [f.kind for f in translate_line(assistant({"type": "text", "text": ""}))] == ["working"]


def test_a_long_text_is_cut():
    (_, fact) = translate_line(assistant({"type": "text", "text": "x" * 5000}))
    assert len(fact.body) == 500
