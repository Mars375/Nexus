"""Acteurs connus de Nexus (DATA-MODEL §2.2)."""

from typing import Literal, get_args

Human = Literal["loic"]
Agent = Literal["helios", "mnema", "aether", "artemis", "claude", "codex", "orca", "hermes"]
Actor = Literal[Human, Agent]

HUMANS = frozenset(get_args(Human))
AGENTS = frozenset(get_args(Agent))
ACTORS = HUMANS | AGENTS

DEFAULT_ACTOR = "loic"
