"""Registry of the adapters available in this process, by executor (empty by default)."""

from __future__ import annotations

import logging
import threading

from nexus.actors import EXECUTORS
from nexus.adapters.base import ADAPTER_NAME, Adapter

log = logging.getLogger("nexus.adapters")


class AdapterRegistry:
    """executor name -> adapter. Without an entry, dispatching to that executor is a 409."""

    def __init__(self) -> None:
        self._adapters: dict[str, Adapter] = {}
        self.stopping = threading.Event()
        self.tick_lock = threading.Lock()

    def register(self, executor: str, adapter: Adapter) -> None:
        if executor not in EXECUTORS:
            raise ValueError(f"exécutant inconnu : {executor}")
        name = getattr(adapter, "name", None)
        if not isinstance(name, str) or not ADAPTER_NAME.fullmatch(name):
            # Refused now, not at the first event: `publish()` rejects such an `origin`.
            raise ValueError("nom d'adaptateur invalide : minuscules, chiffres et tirets")
        self._adapters[executor] = adapter

    def unregister(self, executor: str) -> None:
        self._adapters.pop(executor, None)

    def get(self, executor: str) -> Adapter | None:
        return self._adapters.get(executor)

    def close_all(self) -> None:
        """At server shutdown: let each adapter stop what it started. Never raises."""
        self.stopping.set()  # no tick starts a launch from now on
        with self.tick_lock:  # and the tick in progress is waited for
            for adapter in self._adapters.values():
                close = getattr(adapter, "close", None)
                if close is not None:
                    try:
                        close()
                    except Exception as exc:  # shutdown goes on whatever one adapter does
                        log.warning("fermeture de %s : %s", adapter.name, type(exc).__name__)

    def executors(self) -> list[str]:
        return sorted(self._adapters)
