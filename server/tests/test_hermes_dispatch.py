"""`HermesAdapter.dispatch` against a fake `hermes` (spec §3, tests 18-24)."""

import pytest
from hermes_support import (
    assignees,
    calls,
    created,
    make_fake_hermes,
    reply,
    run_info,
    set_scenario,
    subcommands,
)

from nexus.adapters.base import Dispatched, LaunchUncertain
from nexus.adapters.hermes import HermesAdapter
from nexus.adapters.hermes_cli import HermesRefused

TITLE = "Nexus nx-run-1 nx-task-1"


@pytest.fixture
def rig(tmp_path):
    binary = make_fake_hermes(tmp_path / "fake", create=[reply(created())])
    adapter = HermesAdapter(str(binary), "default", tmp_path / "data", max_seconds=1800.0)
    (tmp_path / "data").mkdir()
    return adapter, binary


def test_the_command_is_exact_and_the_brief_only_goes_through_stdin(rig):
    adapter, binary = rig
    brief = "Tâche à réécrire : « été » --json\n-x\nsecret-marker-42"

    sent = adapter.dispatch(run_info(brief=brief))

    assert sent == Dispatched(external_ref="t_9f3a01bc", native_status="ready")
    (call,) = calls(binary)
    assert call["argv"] == [
        "kanban", "--board", "nexus", "create", TITLE, "--body-file", "-",
        "--assignee", "default", "--idempotency-key", "nx-run-1", "--max-runtime", "1800",
        "--max-retries", "1", "--workspace", "scratch", "--created-by", "nexus", "--json"]
    assert "secret-marker-42" not in " ".join(call["argv"])
    assert call["stdin"].startswith(brief + "\n")
    assert "Consigne de Nexus" in call["stdin"] and "metadata.artifacts" in call["stdin"]
    assert call["utf8"] == "1"


def test_a_timeout_is_replayed_with_the_same_key_once_the_first_is_stopped(rig):
    adapter, binary = rig
    adapter.cli_timeout = 1.0
    set_scenario(binary.parent, create=[reply(hang=True), reply(created())])

    assert adapter.dispatch(run_info()).external_ref == "t_9f3a01bc"

    first, second = calls(binary)
    assert first["argv"] == second["argv"] and second["at"] >= first["at"]


def test_an_unreadable_answer_is_replayed(rig):
    adapter, binary = rig
    set_scenario(binary.parent, create=[reply("pas du json"), reply(created())])
    assert adapter.dispatch(run_info()).external_ref == "t_9f3a01bc"
    assert subcommands(binary) == ["create", "create"]


def test_two_refusals_are_an_ordinary_error(rig):
    adapter, binary = rig
    set_scenario(binary.parent, create=[reply(exit=1, stderr="nope")])
    with pytest.raises(HermesRefused):
        adapter.dispatch(run_info())
    assert subcommands(binary) == ["create", "create"]


def test_an_uncertain_outcome_is_not_an_ordinary_error(rig):
    adapter, binary = rig
    adapter.cli_timeout = 1.0
    for scenario in ([reply(hang=True)], [reply("x"), reply(exit=1)], [reply(exit=1), reply("x")],
                     [reply("x")]):
        set_scenario(binary.parent, create=scenario)
        with pytest.raises(LaunchUncertain):
            adapter.dispatch(run_info())


@pytest.mark.parametrize("bad", [
    {"id": "t_../x"}, {"id": "t_ABC"}, {"id": "t_9f3a01bc "}, {"id": "t_9f3a01bcd"},
    {"assignee": "autre"}, {"title": "Autre titre"}, {"status": "inconnu"},
])
def test_a_non_conforming_answer_is_unreadable(rig, bad):
    adapter, binary = rig
    set_scenario(binary.parent, create=[reply(created() | bad)])
    with pytest.raises(LaunchUncertain):
        adapter.dispatch(run_info())


def test_nothing_is_called_for_a_workdir_or_another_agent(rig):
    adapter, binary = rig
    for run in (run_info(workdir="C:/depot"), run_info(agent="mnema")):
        with pytest.raises(ValueError):
            adapter.dispatch(run)
    assert calls(binary) == []


def test_the_probe_reads_the_profile_on_the_nexus_board(rig):
    adapter, binary = rig
    set_scenario(binary.parent, assignees=[reply(assignees())])
    assert adapter.probe() is True
    assert calls(binary)[0]["argv"] == ["kanban", "--board", "nexus", "assignees", "--json"]
    for answer in (reply(assignees("autre")), reply(assignees(on_disk=False)),
                   reply(exit=1, stderr="board 'nexus' does not exist"), reply({"x": 1})):
        set_scenario(binary.parent, assignees=[answer])
        assert adapter.probe() is False
