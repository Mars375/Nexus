"""Pure translation of `codex exec --json` lines to facts.

The line shapes are those of codex-cli 0.166 as far as they could be known without running a
model: to be confirmed on the first real run (ADR-023, D8).
"""

import json

import pytest
from codex_support import COMMAND, DONE, FAILED, MESSAGE, THREAD, TURN

from nexus.adapters.codex_translate import translate_line


def test_the_session_and_the_turn_open_the_story():
    assert translate_line(THREAD).kind == "claimed"
    assert translate_line(TURN).kind == "working"


def test_a_message_and_a_command_are_progress_without_the_raw_output():
    message, command = translate_line(MESSAGE), translate_line(COMMAND)
    assert (message.kind, message.body) == ("progress", "Je commence.")
    assert command.kind == "progress" and "pytest -q" in command.body
    assert "RAW-OUTPUT" not in repr(command)


def test_changed_files_are_listed():
    line = json.dumps({"type": "item.completed", "item": {
        "type": "file_change", "changes": [{"path": "a.py", "kind": "update"}]}})
    fact = translate_line(line)
    assert fact.kind == "progress" and "a.py" in fact.body


def test_the_end_of_a_turn_is_finished_and_a_failure_is_failed():
    assert translate_line(DONE).kind == "finished"
    failed = translate_line(FAILED)
    assert (failed.kind, failed.body) == ("failed", "le modèle a échoué")
    assert translate_line(json.dumps({"type": "error", "message": "x"})).kind == "failed"


@pytest.mark.parametrize("line", [
    "", "not json", "[]", "42", '{"type": 7}', '{"type": "item.started"}',
    '{"type": "item.completed", "item": "x"}', '{"type": "something.new"}',
    '{"type": "item.completed", "item": {"type": "reasoning", "text": "secret thoughts"}}',
])
def test_anything_unexpected_is_ignored_never_raised(line):
    assert translate_line(line) is None


def test_long_texts_are_cut():
    line = json.dumps({"type": "item.completed", "item": {
        "type": "agent_message", "text": "x" * 5000}})
    assert len(translate_line(line).body) <= 500
