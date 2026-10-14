from datetime import datetime
from itertools import product

import pytest

from nexus.clock import TZ
from nexus.tasks import rules
from nexus.tasks.rules import RuleViolation

ALLOWED = {
    ("backlog", "todo"), ("backlog", "in_progress"), ("backlog", "dropped"),
    ("todo", "backlog"), ("todo", "in_progress"), ("todo", "dropped"),
    ("in_progress", "todo"), ("in_progress", "blocked"), ("in_progress", "review"),
    ("in_progress", "done"), ("in_progress", "dropped"),
    ("blocked", "todo"), ("blocked", "in_progress"), ("blocked", "dropped"),
    ("review", "in_progress"), ("review", "done"), ("review", "dropped"),
    ("dropped", "backlog"),
}


@pytest.mark.parametrize(("current", "target"), list(product(rules.STATUSES, repeat=2)))
def test_every_transition_is_explicitly_allowed_or_refused(current, target):
    if (current, target) in ALLOWED:
        rules.check_transition(current, target)
    else:
        with pytest.raises(RuleViolation):
            rules.check_transition(current, target)


def test_unknown_status_is_refused():
    with pytest.raises(RuleViolation, match="inconnu"):
        rules.check_transition("todo", "archived")


@pytest.mark.parametrize("status", sorted(rules.ACTIVE))
@pytest.mark.parametrize("next_action", [None, "", "   "])
def test_active_task_requires_next_action(status, next_action):
    with pytest.raises(RuleViolation) as exc:
        rules.check_next_action(status, next_action)
    assert exc.value.code == "next_action_required"


@pytest.mark.parametrize("status", ["backlog", "done", "dropped"])
def test_inactive_task_may_have_no_next_action(status):
    rules.check_next_action(status, None)


def test_block_requires_cause():
    with pytest.raises(RuleViolation) as exc:
        rules.check_block(None, "attendre la clé", None)
    assert exc.value.code == "block_cause_required"


def test_block_requires_follow_up_or_plan():
    with pytest.raises(RuleViolation) as exc:
        rules.check_block("SSH timeout", None, None)
    assert exc.value.code == "block_follow_up_required"
    rules.check_block("SSH timeout", "rallumer Artémis", None)
    rules.check_block("SSH timeout", None, datetime(2026, 9, 29, 9, tzinfo=TZ))


def test_drop_requires_reason():
    with pytest.raises(RuleViolation):
        rules.check_drop("  ")
    rules.check_drop("plus nécessaire")


def test_done_without_expected_evidence_is_done():
    assert rules.resolve_done(None, []) == "done"


def test_done_missing_expected_evidence_goes_to_review():
    assert rules.resolve_done("commit + tests verts", []) == "review"
    assert rules.resolve_done("commit + tests verts", ["commit:a1b2c3d"]) == "done"


@pytest.mark.parametrize("target", sorted(rules.GATED_BY_DEPENDENCIES))
def test_pending_dependencies_block_progress(target):
    with pytest.raises(RuleViolation) as exc:
        rules.check_dependencies(target, ["nx-task-3 (backlog)"])
    assert exc.value.code == "dependencies_pending"
    assert "nx-task-3" in exc.value.message


@pytest.mark.parametrize("target", ["todo", "backlog", "blocked", "dropped"])
def test_pending_dependencies_do_not_block_other_moves(target):
    rules.check_dependencies(target, ["nx-task-3 (backlog)"])


def test_first_operation_in_progress_becomes_main_then_auxiliary():
    assert rules.resolve_role(None, other_main_in_progress=False) == "main"
    assert rules.resolve_role(None, other_main_in_progress=True) == "auxiliary"


def test_second_explicit_main_is_refused():
    with pytest.raises(RuleViolation) as exc:
        rules.resolve_role("main", other_main_in_progress=True)
    assert exc.value.code == "main_operation_taken"
    assert rules.resolve_role("auxiliary", other_main_in_progress=False) == "auxiliary"


def test_unknown_status_refusal_does_not_echo_the_value():
    with pytest.raises(RuleViolation) as refused:
        rules.check_transition("todo", "ghp_" + "S" * 36)
    assert "S" * 36 not in refused.value.message
