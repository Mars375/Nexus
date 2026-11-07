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
MAX_PROGRESS = 300  # progress facts kept per run; the end is always kept


class _Job:
    """One running `codex exec`: its process, its worktree and the story told so far."""

    def __init__(self, tree: codex_git.Worktree, process: subprocess.Popen) -> None:
        self.tree, self.process = tree, process
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.events: list[RunEvent] = []
        self.progress = 0
        self.turn_done = False
        self.failure: str | None = None
        self.settled = False
        self.reader: threading.Thread | None = None

    def add(
        self,
        kind: str,
        subject: str,
        body: str | None = None,
        payload: dict | None = None,
        evidence: list[str] | None = None,
    ) -> None:
        with self.lock:
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
                self.turn_done = True
            elif fact.kind == "failed":
                self.failure = self.failure or fact.body
            elif fact.kind != "progress" or self.progress < MAX_PROGRESS:
                self.progress += fact.kind == "progress"
                self.add(fact.kind, fact.subject, fact.body)
        self.process.wait()


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
        self.worktrees = data_dir / "worktrees"
        self.max_seconds, self.environ = max_seconds, environ
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()

    def probe(self) -> bool:
        """Only `--version`: it starts no model."""
        try:
            done = subprocess.run(
                [self.binary, "--version"], capture_output=True, timeout=PROBE_TIMEOUT, check=False
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
        return Dispatched(external_ref=tree.branch, native_status="started")

    @staticmethod
    def _feed(process: subprocess.Popen, brief: str) -> None:
        try:
            process.stdin.write(brief)
            process.stdin.close()
        except OSError:  # the process already ended
            pass

    def _job(self, ref: str) -> _Job | None:
        with self._lock:
            return self._jobs.get(ref)

    def _settle(self, job: _Job) -> None:
        """Add the closing event once: the time limit, or the end judged on the proof."""
        with job.lock:
            if job.settled:
                return
            over = time.monotonic() - job.started >= self.max_seconds
            ended = not job.reader.is_alive() and job.process.poll() is not None
            if not ended and not over:
                return
            job.settled = True
        if not ended:
            codex_process.kill_tree(job.process)
            job.add("failed", "Durée maximale dépassée",
                    payload={"cause": "durée maximale dépassée : processus arrêté"})
            return
        code = job.process.returncode
        if job.failure or code != 0 or not job.turn_done:
            cause = job.failure or f"le processus s'est arrêté (code {code}) sans terminer son tour"
            job.add("failed", "Codex a échoué", payload={"cause": cause})
            return
        commit = codex_git.proof(job.tree)
        if commit:
            # Abbreviated: the scanner masks a full 40-hex hash as a secret, and a masked proof
            # proves nothing (the run would end in review).
            job.add("done", "Codex a terminé", evidence=[f"commit:{commit[:SHORT_SHA]}"])
        else:
            job.add("review", "Codex a terminé sans commit exploitable",
                    body="aucun commit descendant du départ : à relire",
                    evidence=[f"branch:{job.tree.branch}"])

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
            log.info("annulation de %s : aucun processus connu ici", run.ref)
            return
        if not codex_process.kill_tree(job.process):
            raise RuntimeError("arrêt du processus non confirmé")

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
             if p.is_dir() and codex_git.toplevel(p) == p.resolve()]
    if found is None or not repos:
        return False
    adapter = CodexAdapter(
        found, repos, settings.data_dir, max_seconds=settings.run_max_minutes * 60
    )
    if not adapter.probe():
        return False
    registry.register("codex", adapter)
    return True
