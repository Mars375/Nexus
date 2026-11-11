"""`HermesAdapter.watch` against a fake `hermes` (spec §4, tests 25-31)."""

from datetime import UTC, datetime

import pytest
from hermes_support import (
    T0,
    TASK_ID,
    attachment,
    calls,
    event,
    make_fake_hermes,
    reply,
    run_info,
    run_row,
    set_scenario,
    show_payload,
    subcommands,
)

from nexus.adapters.hermes import HermesAdapter
from nexus.adapters.hermes_cli import HermesUnavailable
from nexus.adapters.hermes_translate import GRACE_SECONDS, SEQ_MISSING, SEQ_WATCHDOG

REF = run_info(external_ref=TASK_ID)
TERMINATED = event("archive_worker_termination", T0 + 9, {"terminated": True, "prev_pid": 5})


@pytest.fixture
def rig(tmp_path):
    binary = make_fake_hermes(tmp_path / "fake")
    (tmp_path / "data").mkdir()
    adapter = HermesAdapter(str(binary), "default", tmp_path / "data", max_seconds=600.0)
    adapter.watch_seconds = 0.0
    adapter.clock = lambda: datetime.fromtimestamp(T0 + 60, UTC)
    return adapter, binary


def scenario(binary, **answers):
    set_scenario(binary.parent, **answers)


def test_two_reads_within_the_spacing_make_one_call(rig):
    adapter, binary = rig
    adapter.watch_seconds = 10.0
    scenario(binary, show=[reply(show_payload("ready"))])

    first = adapter.watch(REF)
    second = adapter.watch(REF)

    assert subcommands(binary) == ["show"]
    assert first.native_status == "ready" and second.events == () and second.cursor is None


@pytest.mark.parametrize("answer", [
    reply(exit=1, stderr="database is locked"), reply("pas du json"), reply({"task": 3}),
    reply({"task": {}, "events": "x"}), reply(hang=True),
])
def test_a_failing_read_is_unavailable(rig, answer):
    adapter, binary = rig
    adapter.cli_timeout = 1.0
    scenario(binary, show=[answer])
    with pytest.raises(HermesUnavailable):
        adapter.watch(REF)


def test_a_vanished_task_is_a_failure(rig):
    adapter, binary = rig
    scenario(binary, show=[reply(exit=1, stderr=f"no such task {TASK_ID}")])
    result = adapter.watch(REF)
    assert [(e.seq, e.kind) for e in result.events] == [(SEQ_MISSING, "failed")]
    assert "introuvable" in result.events[0].payload["cause"]


def test_the_maximum_duration_archives_before_the_close(rig):
    adapter, binary = rig
    adapter.clock = lambda: datetime.fromtimestamp(T0 + 600 + GRACE_SECONDS + 5, UTC)
    scenario(binary, show=[reply(show_payload("running", events=[event("spawned")])),
                           reply(show_payload("archived", events=[event("spawned"), TERMINATED]))],
             archive=[reply("")])

    result = adapter.watch(REF)

    assert subcommands(binary) == ["show", "archive", "show"]
    assert result.events[-1].seq == SEQ_WATCHDOG and result.events[-1].kind == "failed"


def test_an_unconfirmed_archive_publishes_nothing(rig):
    adapter, binary = rig
    adapter.clock = lambda: datetime.fromtimestamp(T0 + 600 + GRACE_SECONDS + 5, UTC)
    scenario(binary, show=[reply(show_payload("running", events=[event("spawned")]))],
             archive=[reply("")])
    with pytest.raises(RuntimeError):
        adapter.watch(REF)


@pytest.mark.parametrize("closing", [
    event("blocked", T0 + 5, {"reason": "besoin d'une clé"}),
    event("gave_up", T0 + 5, {"trigger_outcome": "crashed", "error": "boum"}),
])
def test_blocked_and_gave_up_archive_the_task_first(rig, closing):
    adapter, binary = rig
    first = show_payload("blocked", events=[event("spawned"), closing])
    scenario(binary, show=[reply(first),
                           reply(show_payload("archived", events=[*first["events"], TERMINATED]))],
             archive=[reply("")])

    result = adapter.watch(REF)

    assert subcommands(binary) == ["show", "archive", "show"]
    assert result.events[-1].kind in ("blocked", "failed")


def test_a_blocked_close_with_an_unconfirmed_archive_publishes_nothing(rig):
    adapter, binary = rig
    show = show_payload("blocked", events=[event("blocked", T0 + 5, {"reason": "x"})])
    scenario(binary, show=[reply(show)], archive=[reply("")])
    with pytest.raises(RuntimeError):
        adapter.watch(REF)


def test_a_completion_reads_the_attachments_as_proofs(rig, tmp_path):
    adapter, binary = rig
    f = tmp_path / "rapport.md"
    f.write_text("cinq lignes", encoding="utf-8")
    show = show_payload("done", events=[event("completed", T0 + 5, None, 1)],
                        runs=[run_row(1, "completed", "ok")])
    scenario(binary, show=[reply(show)], attachments=[reply([attachment(f, f.stat().st_size)])])

    result = adapter.watch(REF)

    assert subcommands(binary) == ["show", "attachments"]
    assert result.events[-1].kind == "done" and result.events[-1].evidence[0] == f"file:{f}"
    assert result.cursor == "1" and result.native_status == "done/completed"


def test_attachments_failing_is_not_a_review(rig):
    adapter, binary = rig
    show = show_payload("done", events=[event("completed", T0 + 5, None, 1)])
    scenario(binary, show=[reply(show)], attachments=[reply(exit=1, stderr="locked")])
    with pytest.raises(HermesUnavailable):
        adapter.watch(REF)


def test_an_invalid_reference_starts_nothing(rig):
    adapter, binary = rig
    for ref in ("t_x & calc", "../t_9f3a01bc", None, "t_9f3a01bc\n--rm"):
        with pytest.raises(ValueError):
            adapter.watch(run_info(external_ref=ref))
    assert calls(binary) == []
