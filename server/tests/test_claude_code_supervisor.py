"""`claude-code` through the real supervisor and API: every closing shape is accepted by the event
protocol and closes the run (a closing event the protocol refuses would be skipped for ever)."""

import time
from contextlib import contextmanager

import pytest
from claude_code_support import (
    INIT_MCP,
    INIT_OK,
    OK_LINES,
    RESULT_IS_ERROR,
    Rig,
    settings_for,
    write,
)
from codex_support import git
from conftest import ActorClient, tailscale_json
from runs_support import code_of, dispatch, events_of, make_task, tick

from nexus.app import create_app

CLOSED = ("done", "review", "failed", "cancelled")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return lambda **scenario: Rig(tmp_path, monkeypatch, **scenario)


@contextmanager
def run_through(r, **dispatch_fields):
    """Hand a task to Claude, tick until the run closes; yields (client, task, run) once it has."""
    app = create_app(settings_for(r), nodes_runner=tailscale_json)
    with ActorClient(app) as client:
        task = make_task(client)
        fields = {"executor": "claude", "agent": "claude", "model": "sonnet",
                  "workdir": str(r.repo)} | dispatch_fields
        res = dispatch(client, task, **fields)
        assert res.status_code == 201, res.text
        deadline = time.monotonic() + 30
        run = res.json()
        while run["status"] not in CLOSED and time.monotonic() < deadline:
            tick(client)
            run = client.get("/api/runs/nx-run-1").json()
            time.sleep(0.05)
        yield client, task, run


def story(client, task):
    return [(e["kind"], e["origin"], e["subject"]) for e in events_of(client, task)]


def test_a_run_that_changed_a_file_ends_done_with_the_commit_as_proof(rig):
    r = rig(lines=OK_LINES, actions=[write()])
    with run_through(r) as (client, task, run):
        assert run["status"] == "done" and run["model"] == "sonnet"
        assert run["external_ref"] == "nexus/nx-run-1"
        got = events_of(client, task)
        assert got[-1]["kind"] == "done" and got[-1]["evidence"] == [f"commit:{r.head()[:12]}"]
        assert {e["origin"] for e in got} == {"claude-code"}
        assert [e["actor"] for e in got] == ["claude"] * len(got)
        assert "RAW-OUTPUT" not in str([e["body"] for e in got])
        assert git(r.repo, "rev-list", "--count", f"{r.start()}..{r.head()}") == "1"


def test_a_run_without_change_closes_in_review_with_the_branch_as_evidence(rig):
    with run_through(rig(lines=OK_LINES)) as (client, task, run):
        assert run["status"] == "review"
        last = events_of(client, task)[-1]
        assert last["kind"] == "review" and last["evidence"] == ["branch:nexus/nx-run-1"]


def test_a_refused_commit_closes_the_run_failed_with_its_motive_and_the_branch(rig):
    r = rig(lines=OK_LINES, actions=[write(), {"do": "nested_repo"}])
    with run_through(r) as (client, task, run):
        assert run["status"] == "failed"
        last = events_of(client, task)[-1]
        assert last["kind"] == "failed" and last["evidence"] == ["branch:nexus/nx-run-1"]
        assert last["payload"]["cause"] == "commit refusé par Nexus : dépôt git imbriqué"
        assert r.head() == r.start()


def test_a_breach_closes_the_run_failed_and_the_process_is_gone(rig):
    r = rig(lines=[INIT_MCP], hang=True)
    with run_through(r) as (client, task, run):
        assert run["status"] == "failed"
        last = events_of(client, task)[-1]
        assert last["payload"]["cause"].startswith("isolation non respectée")
        assert "claimed" not in [k for k, _, _ in story(client, task)]


def test_a_result_in_error_closes_the_run_failed_with_its_cause(rig):
    r = rig(lines=[INIT_OK, RESULT_IS_ERROR], actions=[write()])
    with run_through(r) as (client, task, run):
        assert run["status"] == "failed"
        assert events_of(client, task)[-1]["payload"]["cause"] == "Limite d'usage atteinte"


def test_a_launch_that_cannot_happen_is_failed_with_a_fixed_cause_and_nothing_is_started(rig):
    r = rig(lines=OK_LINES)
    git(r.repo, "config", "--unset", "user.name")
    git(r.repo, "config", "--unset", "user.email")
    with run_through(r) as (client, task, run):
        assert run["status"] == "failed"
        assert events_of(client, task)[-1]["payload"]["cause"] == "lancement impossible"
        assert not (r.dir / "args.json").exists() and not r.worktree.exists()
        assert git(r.repo, "branch", "--list", "nexus/*") == ""


def test_the_model_is_required_and_the_adapter_never_sees_a_run_without_one(rig):
    r = rig(lines=OK_LINES)
    app = create_app(settings_for(r), nodes_runner=tailscale_json)
    with ActorClient(app) as client:
        task = make_task(client)
        res = dispatch(client, task, executor="claude", agent="claude", workdir=str(r.repo))
        assert res.status_code == 409 and code_of(res) == "model_required"
