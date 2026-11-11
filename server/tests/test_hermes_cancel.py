"""`HermesAdapter.cancel` against a fake `hermes` (spec §5, tests 32-35)."""

import pytest
from hermes_support import (
    T0,
    TASK_ID,
    calls,
    event,
    make_fake_hermes,
    reply,
    run_info,
    set_scenario,
    show_payload,
    subcommands,
)

from nexus.adapters.hermes import HermesAdapter

REF = run_info(external_ref=TASK_ID)


@pytest.fixture
def rig(tmp_path):
    binary = make_fake_hermes(tmp_path / "fake")
    (tmp_path / "data").mkdir()
    return HermesAdapter(str(binary), "default", tmp_path / "data"), binary, tmp_path / "data"


def archived(termination: dict | None, status: str = "archived") -> dict:
    events = [event("archived")]
    if termination is not None:
        events.append(event("archive_worker_termination", T0 + 1, termination))
    return show_payload(status, events=events)


def test_archive_then_an_archived_task_is_confirmed(rig):
    adapter, binary, _ = rig
    for archive in (reply(""), reply(exit=1, stderr="cannot archive")):  # already archived
        set_scenario(binary.parent, archive=[archive],
                     show=[reply(archived({"terminated": True, "prev_pid": 7}))])
        adapter.cancel(REF)
    assert subcommands(binary) == ["archive", "show", "archive", "show"]


@pytest.mark.parametrize("termination", [
    {"terminated": False, "prev_pid": 7},
    {"terminated": False, "prev_pid": 7, "signal_refused": True},
    {"terminated": False, "prev_pid": 7, "host_local": False},
])
def test_a_worker_not_stopped_raises_unless_stopped_by_hand(rig, termination):
    adapter, binary, data = rig
    set_scenario(binary.parent, archive=[reply("")], show=[reply(archived(termination))])
    with pytest.raises(RuntimeError):
        adapter.cancel(REF)

    marker = data / "hermes" / ".stopped" / "nx-run-1"
    marker.parent.mkdir(parents=True)
    marker.touch()
    adapter.cancel(REF)


def test_a_claimed_task_without_a_worker_is_confirmed(rig):
    adapter, binary, _ = rig
    set_scenario(binary.parent, archive=[reply("")],
                 show=[reply(archived({"terminated": False, "prev_pid": None}))])
    adapter.cancel(REF)


def test_a_task_still_alive_after_the_archive_raises(rig):
    adapter, binary, _ = rig
    set_scenario(binary.parent, archive=[reply("")], show=[reply(archived(None, "running"))])
    with pytest.raises(RuntimeError):
        adapter.cancel(REF)


def test_a_vanished_task_is_confirmed(rig):
    adapter, binary, _ = rig
    set_scenario(binary.parent, archive=[reply(exit=1, stderr="no such task")],
                 show=[reply(exit=1, stderr=f"no such task {TASK_ID}")])
    adapter.cancel(REF)


def test_never_launched_calls_nothing(rig):
    adapter, binary, _ = rig
    adapter.cancel(run_info(native_status=None))
    assert calls(binary) == []


def test_an_uncertain_launch_is_searched_by_title(rig):
    adapter, binary, _ = rig
    mine = {"id": "t_00000001", "title": "Nexus nx-run-1 nx-task-1", "created_by": "nexus"}
    other = {"id": "t_00000002", "title": "Nexus nx-run-2 nx-task-1", "created_by": "nexus"}
    foreign = {"id": "t_00000003", "title": "Nexus nx-run-1 nx-task-1", "created_by": "loic"}
    twin = {"id": "t_00000004", "title": "Nexus nx-run-1 nx-task-1", "created_by": "nexus"}
    uncertain = run_info(native_status="dispatching")

    set_scenario(binary.parent, list=[reply([other, foreign])])
    adapter.cancel(uncertain)
    assert subcommands(binary) == ["list"]
    assert calls(binary)[0]["argv"][3:] == ["list", "--archived", "--assignee", "default", "--json"]

    set_scenario(binary.parent, list=[reply([mine, other, foreign, twin])],
                 archive=[reply("")], show=[reply(archived({"terminated": True, "prev_pid": 1}))])
    adapter.cancel(uncertain)
    ids = [c["argv"][-1] for c in calls(binary) if c["argv"][3] == "archive"]
    assert ids == ["t_00000001", "t_00000004"]
