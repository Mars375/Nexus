"""Hermes adapter: environment, writes allowed, secrets and cursor (spec §7, tests 44-47)."""

import logging
import os
from datetime import UTC, datetime

import pytest
from hermes_support import (
    T0,
    TASK_ID,
    calls,
    created,
    event,
    make_fake_hermes,
    reply,
    run_info,
    show_payload,
)

from nexus.adapters.hermes import HermesAdapter
from nexus.adapters.hermes_cli import HermesUnavailable

FORBIDDEN = {"boards", "switch", "use", "assign", "complete", "block", "unblock", "comment",
             "promote", "rm", "unarchive"}
SECRET = "ghp_" + "A" * 36


def build(tmp_path, environ=None, **scenario):
    binary = make_fake_hermes(tmp_path / "fake", **scenario)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    adapter = HermesAdapter(str(binary), "default", tmp_path / "data", environ=environ)
    adapter.watch_seconds = 0.0
    adapter.clock = lambda: datetime.fromtimestamp(T0 + 60, UTC)
    return adapter, binary


def test_the_child_environment_is_an_allow_list(tmp_path):
    environ = dict(os.environ) | {
        "NEXUS_TOKEN": "nxt_" + "a" * 30, "NEXUS_DATA_DIR": "x", "HERMES_KANBAN_BOARD": "default",
        "HERMES_PROFILE": "autre", "CODEX_HOME": "c", "HERMES_HOME": "h", "OPENAI_API_KEY": "k",
    }
    adapter, binary = build(tmp_path, environ, create=[reply(created())])

    adapter.dispatch(run_info())

    (call,) = calls(binary)
    names = {n.upper() for n in call["env"]}
    assert not {n for n in names if n.startswith("NEXUS_")}
    assert not names & {"HERMES_KANBAN_BOARD", "HERMES_PROFILE", "CODEX_HOME", "OPENAI_API_KEY"}
    assert call["environ"]["HERMES_HOME"] == "h" and call["utf8"] == "1"


def test_only_create_and_archive_ever_write(tmp_path):
    first = show_payload("blocked", events=[event("blocked", T0 + 5, {"reason": "x"})])
    archived = show_payload("archived", events=[
        event("archive_worker_termination", T0 + 9, {"terminated": True, "prev_pid": 1})])
    adapter, binary = build(
        tmp_path, assignees=[reply([{"name": "default", "on_disk": True}])],
        create=[reply(created())], show=[reply(first), reply(archived)],
        archive=[reply("")], list=[reply([])], attachments=[reply([])])

    adapter.probe()
    adapter.dispatch(run_info())
    adapter.watch(run_info(external_ref=TASK_ID))
    adapter.cancel(run_info(native_status="dispatching"))

    for call in calls(binary):
        assert not set(call["argv"]) & FORBIDDEN
        assert call["argv"][:3] == ["kanban", "--board", "nexus"]
    assert {c["argv"][3] for c in calls(binary)} <= {
        "assignees", "create", "show", "archive", "list", "attachments"}


def test_secrets_never_reach_an_event_or_a_log(tmp_path, caplog):
    blocked = show_payload("blocked", events=[
        event("blocked", T0 + 5, {"reason": f"la clé {SECRET} manque"})])
    archived = show_payload("archived", events=[
        event("archive_worker_termination", T0 + 9, {"terminated": True, "prev_pid": 1})])
    metadata = {"changed_files": [f"C:/x/{SECRET}.txt"], "tests_run": 2}
    runs = [{"id": 1, "outcome": "completed", "summary": f"voici {SECRET}", "metadata": metadata}]
    done = show_payload("done", events=[event("completed", T0 + 5, {"summary": SECRET}, 1)],
                        runs=runs)
    first, _ = build(tmp_path / "a", show=[reply(blocked), reply(archived)], archive=[reply("")])
    second, _ = build(tmp_path / "b", show=[reply(done)], attachments=[reply([])])

    with caplog.at_level(logging.DEBUG):
        results = [first.watch(run_info(external_ref=TASK_ID)),
                   second.watch(run_info(external_ref=TASK_ID))]

    for result in results:
        published = str([(e.body, e.payload, e.evidence, e.subject) for e in result.events])
        assert result.events and SECRET not in published and "ghp_" not in published
    assert SECRET not in caplog.text


def test_a_secret_in_stderr_is_neither_raised_nor_logged(tmp_path, caplog):
    adapter, _ = build(tmp_path, show=[reply(exit=1, stderr=f"boom {SECRET}")])
    with caplog.at_level(logging.DEBUG), pytest.raises(HermesUnavailable) as error:
        adapter.watch(run_info(external_ref=TASK_ID))
    assert SECRET not in str(error.value) and SECRET not in caplog.text


@pytest.mark.parametrize("cursor", ["abc", "-3", "x" * 600, "٣", "1.5", ""])
def test_an_unreadable_cursor_reads_from_the_start(tmp_path, cursor):
    show = show_payload("running", events=[event("claimed", T0 + 1), event("spawned", T0 + 2)])
    adapter, _ = build(tmp_path, show=[reply(show)])
    result = adapter.watch(run_info(external_ref=TASK_ID, cursor=cursor))
    assert [e.seq for e in result.events] == [1, 2] and result.cursor == "2"
