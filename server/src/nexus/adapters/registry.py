"""Registry of the adapters available in this process, by executor (empty by default)."""

from __future__ import annotations

from nexus.actors import EXECUTORS
from nexus.adapters.base import Adapter


class AdapterRegistry:
    """executor name -> adapter. Without an entry, dispatching to that executor is a 409."""

    def __init__(self) -> None:
        self._adapters: dict[str, Adapter] = {}

    def register(self, executor: str, adapter: Adapter) -> None:
        if executor not in EXECUTORS:
            raise ValueError(f"exécutant inconnu : {executor}")
        self._adapters[executor] = adapter

    def unregister(self, executor: str) -> None:
        self._adapters.pop(executor, None)

    def get(self, executor: str) -> Adapter | None:
        return self._adapters.get(executor)

    def executors(self) -> list[str]:
        return sorted(self._adapters)
