"""Matrice des permissions (#16, ADR-020, spec §2) : règles pures, sans base."""

import pytest

from nexus import permissions
from nexus.actors import ACTORS, EXECUTORS, HUMANS, NODE_AGENTS
from nexus.permissions import Forbidden

OTHERS = sorted(ACTORS - {"claude"})


def test_the_groups_partition_the_actors():
    assert HUMANS == {"loic"}
    assert NODE_AGENTS == {"helios", "mnema", "aether", "artemis"}
    assert EXECUTORS == {"claude", "codex", "orca", "hermes"}
    assert HUMANS | NODE_AGENTS | EXECUTORS == ACTORS
    assert not (HUMANS & NODE_AGENTS or HUMANS & EXECUTORS or NODE_AGENTS & EXECUTORS)


@pytest.mark.parametrize("actor", sorted(ACTORS - EXECUTORS))
@pytest.mark.parametrize("target", sorted(ACTORS))
def test_humans_and_node_agents_may_assign_anyone_on_creation(actor, target):
    permissions.check_create(actor, lead_agent=target, collaborators=[target, "loic"])


@pytest.mark.parametrize("actor", sorted(EXECUTORS))
def test_an_executor_creates_for_itself_or_for_nobody(actor):
    permissions.check_create(actor, lead_agent=None, collaborators=[])
    permissions.check_create(actor, lead_agent=actor, collaborators=[actor])
    permissions.check_create(actor, lead_agent=actor, collaborators=[actor, actor])


@pytest.mark.parametrize("actor", sorted(EXECUTORS))
@pytest.mark.parametrize("other", OTHERS)
def test_an_executor_cannot_create_for_another_actor(actor, other):
    if other == actor:
        return
    for kwargs in (
        {"lead_agent": other, "collaborators": []},
        {"lead_agent": None, "collaborators": [other]},
        {"lead_agent": actor, "collaborators": [actor, other]},
    ):
        with pytest.raises(Forbidden) as refused:
            permissions.check_create(actor, **kwargs)
        assert refused.value.code == "assign_forbidden"
        assert other not in refused.value.message  # never echoes the value
        assert "lead_agent" in refused.value.message or "collaborators" in refused.value.message


@pytest.mark.parametrize("actor", sorted(ACTORS - EXECUTORS))
def test_non_executors_may_reassign_freely(actor):
    permissions.check_update(
        actor, lead_before="codex", lead_after="mnema",
        collaborators_before=["orca"], collaborators_after=["claude", "hermes"],
    )


@pytest.mark.parametrize("actor", sorted(EXECUTORS))
def test_an_executor_may_take_a_task_or_hand_it_back(actor):
    base = {"collaborators_before": [], "collaborators_after": []}
    for before in (None, "helios", actor):
        for after in (actor, "loic", None):
            permissions.check_update(actor, lead_before=before, lead_after=after, **base)


@pytest.mark.parametrize("actor", sorted(EXECUTORS))
def test_an_executor_cannot_give_the_lead_to_another_agent(actor):
    for other in sorted(ACTORS - HUMANS - {actor}):
        with pytest.raises(Forbidden) as refused:
            permissions.check_update(
                actor, lead_before=None, lead_after=other,
                collaborators_before=[], collaborators_after=[],
            )
        assert refused.value.code == "assign_forbidden"
        assert "lead_agent" in refused.value.message and other not in refused.value.message


@pytest.mark.parametrize("actor", sorted(EXECUTORS))
def test_unchanged_assignments_are_not_checked(actor):
    permissions.check_update(
        actor, lead_before="helios", lead_after="helios",
        collaborators_before=["mnema", "codex"], collaborators_after=["mnema", "codex"],
    )
    # Removing someone adds nobody: not an assignment.
    permissions.check_update(
        actor, lead_before="helios", lead_after="helios",
        collaborators_before=["mnema", "codex"], collaborators_after=["mnema"],
    )


@pytest.mark.parametrize("actor", sorted(EXECUTORS))
def test_an_executor_may_add_itself_or_a_human_as_collaborator_only(actor):
    permissions.check_update(
        actor, lead_before=None, lead_after=None,
        collaborators_before=["mnema"], collaborators_after=["mnema", actor, "loic"],
    )
    with pytest.raises(Forbidden) as refused:
        permissions.check_update(
            actor, lead_before=None, lead_after=None,
            collaborators_before=[], collaborators_after=["helios"],
        )
    assert refused.value.code == "assign_forbidden"
    assert "collaborators" in refused.value.message and "helios" not in refused.value.message


@pytest.mark.parametrize("actor", sorted(ACTORS))
def test_only_humans_drop_a_task(actor):
    for target in ("backlog", "todo", "in_progress", "blocked", "review", "done"):
        permissions.check_status(actor, target)
    if actor in HUMANS:
        permissions.check_status(actor, "dropped")
        return
    with pytest.raises(Forbidden) as refused:
        permissions.check_status(actor, "dropped")
    assert refused.value.code == "human_only"
    assert "needs_human" in refused.value.message


@pytest.mark.parametrize("bad", [None, 3, "helios"])
def test_a_non_list_collaborators_after_is_a_rule_violation_not_a_type_error(bad):
    from nexus.tasks.rules import RuleViolation

    with pytest.raises(RuleViolation):
        permissions.check_update(
            "codex", lead_before=None, lead_after=None,
            collaborators_before=[], collaborators_after=bad,
        )
