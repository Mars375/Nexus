"""The Hermes adapter (ADR-023, lot G): a task on the `nexus` Kanban board of Hermes.

How a run goes: `dispatch` creates a task for the profile that works for Helios, with the brief on
standard input and an idempotency key `nx-run-<n>`; `watch` reads `show --json` (at most every
`WATCH_SECONDS`) and translates it as a pure function (`hermes_translate`); `cancel` archives the
task and confirms the worker is gone. The adapter holds no story: everything comes from
`external_ref`, the cursor and Hermes itself, so a restart of Nexus loses nothing but the pacing.

Nexus writes to Hermes only to create a task (dispatch) and to archive one (cancel, maximum
duration, ends other than `done`). The board is created by Loïc by hand (spec §2).
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from nexus.adapters import hermes_cli as cli
from nexus.adapters.base import Dispatched, LaunchUncertain, RunEvent, RunInfo, WatchResult
from nexus.adapters.hermes_cli import HermesRefused, HermesUnavailable, Result
from nexus.adapters.hermes_proof import proofs_from
from nexus.adapters.hermes_translate import SEQ_MISSING, Translation, translate
from nexus.adapters.registry import AdapterRegistry
from nexus.clock import now
from nexus.config import Settings

log = logging.getLogger("nexus.hermes")

WATCH_SECONDS = 10.0
CURSOR_DIGITS = 12
INSTRUCTION = (
    "\n\n---\n"
    "Consigne de Nexus : quand le travail est fini, termine la tâche avec kanban_complete.\n"
    "Mets un résumé dans summary et, si tu produis des fichiers, liste leurs chemins absolus\n"
    "dans metadata.artifacts : Hermes les conserve et Nexus les relit comme preuve.\n"
    "Sans livrable, Nexus demandera une relecture à Loïc.\n"
)


def _created_ok(data: object, profile: str, title: str) -> Dispatched | None:
    """The task Hermes answered with, if it is the one that was asked for."""
    if not isinstance(data, dict):
        return None
    if (not isinstance(data.get("id"), str) or not cli.TASK_ID.fullmatch(data["id"])
            or data.get("status") not in cli.KNOWN_STATUSES
            or data.get("assignee") != profile or data.get("title") != title):
        return None
    return Dispatched(external_ref=data["id"], native_status=data["status"])


class HermesAdapter:
    name = "hermes"
    agents = frozenset({"helios"})  # the only profile reachable from this machine (spec §1)

    def __init__(
        self,
        binary: str,
        profile: str,
        data_dir: Path,
        max_seconds: float = 3600.0,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.binary, self.profile = binary, profile
        self.data_dir, self.max_seconds, self.environ = data_dir, max_seconds, environ
        self.cli_timeout = cli.CLI_TIMEOUT
        self.watch_seconds = WATCH_SECONDS
        self.clock: Callable[[], datetime] = now
        self._last_read: dict[str, float] = {}
        self._lock = threading.Lock()

    # --- calls ---------------------------------------------------------------------------

    def _call(self, args: list[str], *, stdin: str | None = None,
              timeout: float | None = None) -> Result:
        self.data_dir.mkdir(parents=True, exist_ok=True)  # the working directory of the child
        return cli.call(self.binary, args, stdin=stdin, timeout=timeout or self.cli_timeout,
                        cwd=str(self.data_dir), environ=self.environ)

    def _show(self, task_id: str) -> Result:
        return self._call(["show", task_id, "--json"])

    @staticmethod
    def _vanished(result: Result) -> bool:
        return result.code not in (0, None) and result.stderr.startswith(cli.NO_SUCH_TASK)

    def probe(self) -> bool:
        """One read: the binary runs, the board `nexus` exists and the profile is on disk."""
        try:
            result = self._call(["assignees", "--json"], timeout=cli.PROBE_TIMEOUT)
            data = cli.read_json(result)
        except (OSError, HermesUnavailable):
            return False
        return isinstance(data, list) and any(
            isinstance(a, dict) and a.get("name") == self.profile and a.get("on_disk") is True
            for a in data)

    # --- dispatch ------------------------------------------------------------------------

    def _create(self, run: RunInfo, title: str) -> tuple[Dispatched | None, str]:
        """One attempt: the task, or why not (`refused`, `unreadable`, `timeout`, `unconfirmed`)."""
        args = ["create", title, "--body-file", "-", "--assignee", self.profile,
                "--idempotency-key", run.ref, "--max-runtime", str(int(self.max_seconds)),
                "--max-retries", "1", "--workspace", "scratch", "--created-by", "nexus", "--json"]
        try:
            result = self._call(args, stdin=run.brief + INSTRUCTION)
        except OSError:
            return None, "refused"  # the binary did not even start: nothing was created
        if result.timed_out:
            return None, "timeout" if result.stopped else "unconfirmed"
        if result.code != 0:
            return None, "refused"
        try:
            sent = _created_ok(cli.read_json(result), self.profile, title)
        except HermesUnavailable:
            sent = None
        return (sent, "ok") if sent else (None, "unreadable")

    def dispatch(self, run: RunInfo) -> Dispatched:
        if run.workdir:
            raise ValueError("Hermes travaille dans un espace jetable : pas de dossier")
        if run.agent != "helios":
            raise ValueError("Hermes ne sert que Helios")
        title = cli.title_of(run.ref, run.task)
        outcomes = []
        for _ in range(2):
            sent, why = self._create(run, title)
            if sent:
                return sent
            outcomes.append(why)
            if why == "unconfirmed":  # the first attempt may still be running: no second one
                break
        if outcomes == ["refused", "refused"]:
            raise HermesRefused("Hermes a refusé de créer la tâche")
        raise LaunchUncertain("issue du lancement incertaine")

    # --- watch ---------------------------------------------------------------------------

    def _due(self, ref: str) -> bool:
        with self._lock:
            last = self._last_read.get(ref)
            if last is not None and time.monotonic() - last < self.watch_seconds:
                return False
            self._last_read[ref] = time.monotonic()
            return True

    @staticmethod
    def _after(cursor: str | None) -> int:
        if cursor and cursor.isascii() and cursor.isdecimal() and len(cursor) <= CURSOR_DIGITS:
            return int(cursor)
        return 0  # unreadable: read it all, stable ids make every known fact a re-read

    def watch(self, run: RunInfo) -> WatchResult:
        task_id = cli.check_task_id(run.external_ref)
        if not self._due(run.ref):
            return WatchResult()
        result = self._show(task_id)
        if self._vanished(result):
            return WatchResult(events=(self._missing(),))
        show = cli.read_json(result)
        if (not isinstance(show, dict) or not isinstance(show.get("task"), dict)
                or not isinstance(show.get("events", []), list)):
            raise HermesUnavailable("forme inattendue")
        after = self._after(run.watch_cursor)

        def read() -> Translation:
            return translate(show, after, proofs=proofs, now=self.clock(),
                             max_seconds=self.max_seconds)

        proofs: list[str] = []
        found = read()
        if found.needs_proofs:  # a completion: judged on the files, read now (never a guess)
            proofs = proofs_from(cli.read_json(self._call(["attachments", task_id, "--json"])))
            found = read()
        if found.archive:
            self._archive(task_id, run.ref)
        return WatchResult(events=found.events, cursor=found.cursor,
                           native_status=found.native_status)

    def _missing(self) -> RunEvent:
        cause = "tâche Hermes introuvable"
        return RunEvent(seq=SEQ_MISSING, at=self.clock(), kind="failed", subject=cause,
                        payload={"seq": SEQ_MISSING, "cause": cause})

    # --- cancel --------------------------------------------------------------------------

    def _stopped_marker(self, ref: str) -> Path:
        return self.data_dir / "hermes" / ".stopped" / ref

    def _archive(self, task_id: str, ref: str) -> None:
        """Archive the task and confirm its worker is gone; raise otherwise (the caller retries)."""
        self._call(["archive", task_id])  # the code is ignored: "cannot archive" may mean done
        result = self._show(task_id)
        if self._vanished(result):
            return
        if result.timed_out or result.code != 0:
            raise HermesUnavailable("arrêt non confirmé")
        show = cli.read_json(result)
        task = show.get("task") if isinstance(show, dict) else None
        if not isinstance(task, dict) or task.get("status") != "archived":
            raise RuntimeError("tâche Hermes non archivée : arrêt non confirmé")
        ends = [e for e in show.get("events") or []
                if isinstance(e, dict) and e.get("kind") == "archive_worker_termination"]
        payload = ends[-1].get("payload") if ends else None
        if not isinstance(payload, dict) or payload.get("terminated") is True:
            return
        if payload.get("prev_pid") is None or self._stopped_marker(ref).exists():
            return  # nothing to stop yet, or stopped by hand
        raise RuntimeError("worker Hermes non arrêté : arrêt non confirmé")

    def cancel(self, run: RunInfo) -> None:
        if run.external_ref is not None:
            self._archive(cli.check_task_id(run.external_ref), run.ref)
            return
        if run.native_status != "dispatching":
            return  # never launched: nothing to call
        title = cli.title_of(run.ref, run.task)
        found = cli.read_json(self._call(
            ["list", "--archived", "--assignee", self.profile, "--json"]))
        if not isinstance(found, list):
            raise HermesUnavailable("liste illisible")
        ids = [t["id"] for t in found
               if isinstance(t, dict) and t.get("title") == title and t.get("created_by") == "nexus"
               and isinstance(t.get("id"), str) and cli.TASK_ID.fullmatch(t["id"])]
        for task_id in ids:
            self._archive(task_id, run.ref)

    def close(self) -> None:
        """Hermes tasks outlive Nexus: archiving them at every shutdown would stop Helios."""

    def recover(self, run: RunInfo) -> str | None:
        return None  # ADR-023 D3: a lost run is not picked up again


def register_configured(registry: AdapterRegistry, settings: Settings) -> bool:
    """Register Hermes only when asked (`NEXUS_HERMES_BIN`) and able: binary, board, profile.

    No fallback on PATH: the test suite creates apps and must never reach the real Hermes.
    """
    if not settings.hermes_bin:
        return False
    found = shutil.which(settings.hermes_bin)
    if found is None:
        return False
    adapter = HermesAdapter(found, settings.hermes_profile, settings.data_dir,
                            max_seconds=settings.run_max_minutes * 60)
    if not adapter.probe():
        log.warning("adaptateur hermes non enregistré : tableau `nexus` ou profil absent "
                    "(voir INTEGRATIONS §A.1)")
        return False
    registry.register("hermes", adapter)
    return True
