"""Acteurs connus de Nexus (DATA-MODEL §2.2) et leurs groupes de permissions (ADR-020)."""

from typing import Literal, get_args

Human = Literal["loic"]
NodeAgent = Literal["helios", "mnema", "aether", "artemis"]
Executor = Literal["claude", "codex", "orca", "hermes"]
Agent = Literal[NodeAgent, Executor]
Actor = Literal[Human, Agent]

HUMANS = frozenset(get_args(Human))
NODE_AGENTS = frozenset(get_args(NodeAgent))
# Agents that run work on Loïc's machine (ADR-013); Hermes is one of them (spec 2026-10-07 §2).
EXECUTORS = frozenset(get_args(Executor))
AGENTS = NODE_AGENTS | EXECUTORS
ACTORS = HUMANS | AGENTS
