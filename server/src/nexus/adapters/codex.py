"""The Codex adapter (ADR-023, lot C): `codex exec` in a git worktree of its own.

How a run goes: a worktree and a branch `nexus/nx-run-<n>` are made in a repository of
`NEXUS_RUN_WORKDIRS`; `codex exec --json --sandbox workspace-write` starts there with the brief on
its standard input (never in an argument) and a filtered environment; a reader thread turns the
JSONL it prints into events kept in memory (the raw output is never written anywhere);
`watch` hands them to the supervisor, which publishes them (masking secrets). The end is judged on
a commit that descends from the start commit, not on Codex's word (D6). Nexus never pushes or
merges. Nothing here blocks: every wait has a timeout, and the process runs in threads.

A run is lost if the server stops (its in-memory story goes with it): the supervisor then marks it
`unknown` and a human cancels or reviews the branch. `recover` knows nothing.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from nexus.adapters import codex_git, codex_process
from nexus.adapters.base import Dispatched, RunEvent, RunInfo, WatchResult
from nexus.adapters.codex_translate import translate_line
from nexus.adapters.registry import AdapterRegistry
from nexus.clock import now
from nexus.config import Settings

log = logging.getLogger("nexus.codex")

PROBE_TIMEOUT = 10.0
SHORT_SHA = 12
KEEP_FINISHED = 20  # closed jobs kept in memory, for a late re-read
MAX_PROGRESS = 300  # progress facts kept per run; the end is always kept


class _Job:
    """One running `codex exec`: its process, its worktree and the story told so far."""

    def __init__(self, tree: codex_git.Worktree, process: subprocess.Popen) -> None:
        self.tree, self.process = tree, process
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.events: list[RunEvent] = []
        self.progress = 0
        self.opened: set[str] = set()
        self.turn_done = False
        self.failure: str | None = None
        self.settled = False
        self.settle_lock = threading.Lock()  # one closing attempt at a time
        self.ended_at: float | None = None  # when the process was seen gone, whatever the polling
        self.reader: threading.Thread | None = None

    def add(
        self,
        kind: str,
        subject: str,
        body: str | None = None,
        payload: dict | None = None,
        evidence: list[str] | None = None,
        final: bool = False,
    ) -> None:
        """Append a fact. The closing one (`final`) seals the story: nothing follows it."""
        with self.lock:
            if self.settled:
                return
            self.settled = final
            seq = len(self.events) + 1
            # `seq` in the payload makes two identical progress facts distinct (anti-noise).
            self.events.append(RunEvent(
                seq=seq, at=now(), kind=kind, subject=subject, body=body,
                payload={"seq": seq} | (payload or {}), evidence=evidence or [],
            ))

    def read(self) -> None:
        """Reader thread: translate each line as it comes, keep only the translation."""
        for line in self.process.stdout:
            fact = translate_line(line)
            if fact is None:
                continue
            if fact.kind == "finished":
                with self.lock:
                    self.turn_done = True
            elif fact.kind == "failed":
                with self.lock:
                    self.failure = self.failure or fact.body
            elif fact.kind in ("claimed", "working"):
                if fact.kind not in self.opened:  # once each: a loop of them would flood
                    self.opened.add(fact.kind)
                    self.add(fact.kind, fact.subject, fact.body)
            elif self.progress < MAX_PROGRESS:
                self.progress += 1
                self.add(fact.kind, fact.subject, fact.body)
        self.process.wait()
        self.ended_at = time.monotonic()


class CodexAdapter:
    name = "codex"

    def __init__(
        self,
        binary: str,
        workdirs: Sequence[Path],
        data_dir: Path,
        max_seconds: float = 3600.0,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.binary, self.workdirs = binary, list(workdirs)
        self.worktrees = data_dir.resolve() / "worktrees"
        self.keep_finished = KEEP_FINISHED
        self.max_seconds, self.environ = max_seconds, environ
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()

    def probe(self) -> bool:
        """Only `--version`: it starts no model."""
        try:
            done = subprocess.run(
                [self.binary, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=PROBE_TIMEOUT, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return done.returncode == 0

    def dispatch(self, run: RunInfo) -> Dispatched:
        with self._lock:
            if run.ref in self._jobs:
                raise ValueError("run déjà lancé")
        repo = codex_git.choose_repo(self.workdirs, run.workdir)
        tree = codex_git.create_worktree(repo, self.worktrees, run.ref)
        argv = [self.binary, "exec", "--json", "--sandbox", "workspace-write",
                "--cd", str(tree.path), "-"]  # "-": the prompt is read from stdin
        process = codex_process.spawn(argv, str(tree.path), codex_process.child_env(self.environ))
        job = _Job(tree, process)
        job.reader = threading.Thread(target=job.read, daemon=True)
        job.reader.start()
        threading.Thread(target=self._feed, args=(process, run.brief), daemon=True).start()
        with self._lock:
            self._jobs[run.ref] = job
            self._prune()
        return Dispatched(external_ref=tree.branch, native_status="started")

    @staticmethod
    def _feed(process: subprocess.Popen, brief: str) -> None:
        try:
            process.stdin.write(brief)
            process.stdin.close()
        except OSError:  # the process already ended
            pass

    def _prune(self) -> None:
        """Forget the oldest closed jobs beyond `keep_finished` (caller holds `_lock`)."""
        closed = sorted((r for r, j in self._jobs.items() if j.settled),
                        key=lambda r: self._jobs[r].started)
        for ref in closed[: max(0, len(closed) - self.keep_finished)]:
            del self._jobs[ref]

    def _stopped_marker(self, ref: str) -> Path:
        return self.worktrees / ".stopped" / ref

    def close(self) -> None:
        """At server shutdown: stop every process still running, and note it, so that a run
        lost by the restart can be cancelled with its stop confirmed."""
        with self._lock:
            jobs = dict(self._jobs)
        for ref, job in jobs.items():
            try:  # one job that cannot be stopped or noted never spares the next
                if codex_process.kill_tree(job.process):
                    self._stopped_marker(ref).parent.mkdir(parents=True, exist_ok=True)
                    self._stopped_marker(ref).touch()
                else:
                    log.warning("arrêt de %s non confirmé", ref)
            except Exception as exc:
                log.warning("arrêt de %s : %s", ref, type(exc).__name__)

    def _job(self, ref: str) -> _Job | None:
        with self._lock:
            return self._jobs.get(ref)

    def _settle(self, job: _Job) -> None:
        """Add the closing event, once the process is really over (D7, D6).

        Nothing is sealed before the closing event exists: a failed kill raises and leaves the
        run open, to be tried again on the next tick, so the executor is never freed while its
        process may still be working.
        """
        if job.settled or not job.settle_lock.acquire(blocking=False):
            return
        try:
            ended = not job.reader.is_alive() and job.process.poll() is not None
            elapsed = (job.ended_at or time.monotonic()) - job.started
            over = elapsed >= self.max_seconds  # judged on when it ended, not when we looked
            if not ended and not over:
                return
            if over:
                # Also when it already ended: its children may not have.
                if not codex_process.kill_tree(job.process):
                    raise RuntimeError("arrêt du processus non confirmé")
                job.reader.join(5.0)
                job.add("failed", "Durée maximale dépassée", final=True,
                        payload={"cause": "durée maximale dépassée : processus arrêté"})
                return
            self._close_ended(job)
        finally:
            job.settle_lock.release()

    @staticmethod
    def _close_ended(job: _Job) -> None:
        code = job.process.returncode
        with job.lock:
            failure, turn_done = job.failure, job.turn_done
        if failure or code != 0 or not turn_done:
            cause = failure or f"le processus s'est arrêté (code {code}) sans terminer son tour"
            job.add("failed", "Codex a échoué", payload={"cause": cause}, final=True)
            return
        commit = codex_git.proof(job.tree)
        if commit:
            # Abbreviated: the scanner masks a full 40-hex hash as a secret, and a masked proof
            # proves nothing (the run would end in review).
            job.add("done", "Codex a terminé", evidence=[f"commit:{commit[:SHORT_SHA]}"],
                    final=True)
        else:
            job.add("review", "Codex a terminé sans commit exploitable",
                    body="aucun commit descendant du départ : à relire",
                    evidence=[f"branch:{job.tree.branch}"], final=True)

    def watch(self, run: RunInfo) -> WatchResult:
        job = self._job(run.ref)
        if job is None:
            return WatchResult()  # unknown here (server restarted): nothing to tell
        self._settle(job)
        try:
            after = int(run.watch_cursor or 0)
        except ValueError:
            after = 0
        with job.lock:
            fresh = tuple(e for e in job.events if e.seq > after)
            last = job.events[-1].seq if job.events else after
        status = "exited" if job.process.poll() is not None else "running"
        return WatchResult(events=fresh, cursor=str(last), native_status=status)

    def cancel(self, run: RunInfo) -> None:
        job = self._job(run.ref)
        if job is None:
            # After a restart nothing is known of the process. Stopped at a clean shutdown
            # (marker), never launched, or unconfirmable: only the first two may return.
            never_launched = run.external_ref is None and run.native_status != "dispatching"
            if never_launched or self._stopped_marker(run.ref).exists():
                return
            raise RuntimeError("processus inconnu depuis le redémarrage : arrêt non confirmé")
        if not codex_process.kill_tree(job.process):
            raise RuntimeError("arrêt du processus non confirmé")
        with job.lock:
            job.settled = True  # over for good: it may now be pruned, and nothing follows
        with self._lock:
            self._prune()

    def recover(self, run: RunInfo) -> str | None:
        return None  # a lost run is not picked up again: a human decides

    # --- for tests and diagnostics -------------------------------------------------------

    def join(self, ref: str, timeout: float) -> None:
        job = self._job(ref)
        if job is not None:
            job.reader.join(timeout)

    def is_finished(self, ref: str) -> bool:
        job = self._job(ref)
        return job is not None and job.process.poll() is not None


def register_configured(registry: AdapterRegistry, settings: Settings) -> bool:
    """Register Codex only when it can work: a usable binary and a git repository to work in.

    Otherwise nothing is registered and handing work to Codex stays a 409 `executor_unavailable`.
    """
    if not settings.run_workdirs:
        return False
    found = shutil.which(settings.codex_bin or "codex")
    repos = [p for p in settings.run_workdirs
             if p.is_dir() and codex_git.toplevel(p) == p.resolve()
             and not codex_git.is_server_repo(p)]
    if found is None or not repos:
        return False
    adapter = CodexAdapter(
        found, repos, settings.data_dir, max_seconds=settings.run_max_minutes * 60
    )
    if not adapter.probe():
        return False
    registry.register("codex", adapter)
    return True
