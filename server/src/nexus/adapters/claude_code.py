"""The `claude-code` adapter (ADR-023, lot H): `claude -p` in a git worktree of its own.

How a run goes: the model, the repository, the git identity and the absence of any filter driver are
checked first (a failure launches nothing and leaves no branch); then a worktree and a branch
`nexus/nx-run-<n>` are made in a repository of `NEXUS_RUN_WORKDIRS`, and `claude -p` starts there
with the brief on its standard input, a settings file outside the worktree and a filtered
environment. The agent has five file tools and no Bash: it cannot commit. A reader thread turns the
stream-json it prints into events kept in memory; the isolation of the session is checked on
`system/init` and fails closed. When the process is really gone, and the run ended well, NEXUS
commits what the agent wrote (`run_commit`), and the end is judged on that commit (D6). Nothing
here pushes or merges, and every wait has a timeout.

A run is lost if the server stops (its story is in memory): the supervisor marks it `unknown`.
`recover` knows nothing, and a restart never commits.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from nexus.adapters import claude_code_cli as cli
from nexus.adapters import codex_git, codex_process, run_commit
from nexus.adapters.base import Dispatched, RunInfo, WatchResult
from nexus.adapters.claude_code_job import Job
from nexus.adapters.registry import AdapterRegistry
from nexus.config import Settings

log = logging.getLogger("nexus.claude_code")

PROBE_TIMEOUT = 10.0
SHORT_SHA = 12
KEEP_FINISHED = 20  # closed jobs kept in memory, for a late re-read
LABEL = "Claude Code"


class ClaudeCodeAdapter:
    name = "claude-code"

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
        self.settings_dir = data_dir.resolve() / "claude-code"
        self.keep_finished = KEEP_FINISHED
        self.max_seconds, self.environ = max_seconds, environ
        self.max_file_bytes = run_commit.MAX_FILE_BYTES  # smaller in tests
        self.commit_budget = run_commit.COMMIT_BUDGET
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def probe(self) -> bool:
        """Only `--version`: it starts no model and reads no account."""
        try:
            done = subprocess.run(
                [self.binary, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=PROBE_TIMEOUT, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return done.returncode == 0

    # --- dispatch ------------------------------------------------------------------------

    def dispatch(self, run: RunInfo) -> Dispatched:
        with self._lock:
            if run.ref in self._jobs:
                raise ValueError("run déjà lancé")
        # Everything that can fail comes before the worktree: a refusal leaves no branch behind.
        if run.model not in cli.MODELS:
            raise ValueError("modèle absent ou inconnu")
        repo = codex_git.choose_repo(self.workdirs, run.workdir)
        identity = run_commit.resolve_identity(repo)
        run_commit.check_no_filter_driver(repo)
        tree = codex_git.create_worktree(repo, self.worktrees, run.ref)
        settings: Path | None = None
        process: subprocess.Popen | None = None
        try:
            gitdir = run_commit.worktree_gitdir(tree)
            settings = cli.write_settings(self.settings_dir, run.ref)
            process = codex_process.spawn(
                cli.argv(self.binary, run.model, settings), str(tree.path),
                cli.child_env(self.environ, gitdir=gitdir, worktree=tree.path), text=False,
            )
            job = Job(tree, process, gitdir=gitdir, identity=identity, run_ref=run.ref,
                      model=run.model, settings=settings)
            job.reader = threading.Thread(target=job.read, daemon=True)
            job.reader.start()
            threading.Thread(target=self._feed, args=(process, run.brief), daemon=True).start()
        except BaseException:
            self._undo_launch(tree, settings, process)
            raise
        with self._lock:
            self._jobs[run.ref] = job
            self._prune()
        return Dispatched(external_ref=tree.branch, native_status="started")

    @staticmethod
    def _undo_launch(
        tree: codex_git.Worktree, settings: Path | None, process: subprocess.Popen | None
    ) -> None:
        """Remove what a failed launch created. A cleanup that fails never hides the cause."""
        steps = [
            lambda: process is not None and codex_process.kill_tree(process),
            lambda: codex_git.git(tree.repo, "worktree", "remove", "--force", str(tree.path)),
            lambda: codex_git.git(tree.repo, "branch", "-D", tree.branch),
            lambda: settings is not None and settings.unlink(missing_ok=True),
        ]
        for step in steps:
            try:
                step()
            except Exception as exc:
                log.warning("nettoyage d'un lancement : %s", type(exc).__name__)

    @staticmethod
    def _feed(process: subprocess.Popen, brief: str) -> None:
        text = (brief + cli.INSTRUCTION).encode("utf-8", "replace")  # bytes: no newline change
        try:
            process.stdin.write(text)
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

    def _job(self, ref: str) -> Job | None:
        with self._lock:
            return self._jobs.get(ref)

    # --- the end of a run ----------------------------------------------------------------

    def _stop_tree(self, job: Job) -> None:
        if not codex_process.kill_tree(job.process):
            raise RuntimeError("arrêt du processus non confirmé")
        job.reader.join(5.0)

    def _close(self, job: Job, kind: str, subject: str, **fields) -> None:
        """The closing event, then the settings file: gone whatever the end."""
        job.add(kind, subject, final=True, **fields)
        job.settings.unlink(missing_ok=True)

    def _fail(self, job: Job, subject: str, cause: str, evidence: list[str] | None = None) -> None:
        self._close(job, "failed", subject, payload={"cause": cause}, evidence=evidence)

    def _settle(self, job: Job) -> None:
        """Add the closing event, once the process is really over (D7, D6).

        Nothing is sealed before the closing event exists: a failed kill raises and leaves the run
        open, to be tried again on the next tick, so the executor is never freed while its process
        may still be working.
        """
        if job.settled or not job.settle_lock.acquire(blocking=False):
            return
        try:
            if job.breach is not None or job.unverified:
                self._stop_tree(job)  # at once: no wait for the end nor for the maximum duration
                cause = job.breach or "isolement de la session non vérifié"
                self._fail(job, "Isolation de la session non respectée", cause)
                return
            ended = not job.reader.is_alive() and job.process.poll() is not None
            elapsed = (job.ended_at or time.monotonic()) - job.started
            over = elapsed >= self.max_seconds  # judged on when it ended, not when we looked
            if not ended and not over:
                return
            if over:
                self._stop_tree(job)  # also when it already ended: its children may not have
                self._fail(job, "Durée maximale dépassée",
                           "durée maximale dépassée : processus arrêté")
                return
            self._close_ended(job)
        finally:
            job.settle_lock.release()

    def _close_ended(self, job: Job) -> None:
        code, result = job.process.returncode, job.result
        if result is not None and not result.ok:
            self._fail(job, "Claude Code a échoué", result.cause or "échec sans détail")
        elif code != 0:
            self._fail(job, "Claude Code a échoué", f"le processus s'est arrêté (code {code})")
        elif result is None:
            self._fail(job, "Claude Code a échoué", "le processus s'est arrêté sans résultat")
        elif not job.isolated:
            self._fail(job, "Isolation de la session non respectée",
                       "isolement de la session non vérifié")
        else:
            self._commit(job)

    def _commit(self, job: Job) -> None:
        """Nexus commits what the agent wrote: only here, the process being gone (run_commit,
        precondition 2). The words of the events are the adapter's; the git output is never
        copied."""
        request = run_commit.CommitRequest(
            tree=job.tree, gitdir=job.gitdir, identity=job.identity, run_ref=job.run_ref,
            adapter=self.name, label=LABEL, model=job.model,
        )
        outcome = run_commit.commit_run(
            request, max_file_bytes=self.max_file_bytes, budget=self.commit_budget)
        branch = [f"branch:{job.tree.branch}"]
        match outcome:
            case run_commit.Committed(sha):
                # Abbreviated: the scanner masks a full 40-hex hash as a secret, and a masked proof
                # proves nothing.
                self._close(job, "done", "Claude Code a terminé ; Nexus a commité",
                            evidence=[f"commit:{sha[:SHORT_SHA]}"])
            case run_commit.NothingToCommit():
                self._close(job, "review", "Claude Code a terminé sans changement",
                            body="aucun fichier modifié : à relire", evidence=branch)
            case run_commit.Refused(motive):
                self._fail(job, "Commit refusé par Nexus",
                           f"commit refusé par Nexus : {motive}", branch)
            case run_commit.GitFailed(step, timed_out):
                what = "délai dépassé" if timed_out else step
                self._fail(job, "Commit de Nexus impossible",
                           f"commit de Nexus impossible ({what})", branch)

    # --- supervisor calls ----------------------------------------------------------------

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
        job.settings.unlink(missing_ok=True)
        with self._lock:
            self._prune()

    def recover(self, run: RunInfo) -> str | None:
        return None  # a lost run is not picked up again, and never committed: a human decides

    # --- for tests and diagnostics -------------------------------------------------------

    def join(self, ref: str, timeout: float) -> None:
        job = self._job(ref)
        if job is not None:
            job.reader.join(timeout)


def register_configured(registry: AdapterRegistry, settings: Settings) -> bool:
    """Register Claude Code only when it can work: the binary named by `NEXUS_CLAUDE_BIN` (no
    fallback on the PATH: the real one is installed here and no test may reach it), a git
    repository to work in, and a probe that answers. Otherwise handing work to Claude stays a 409
    `executor_unavailable`."""
    if not settings.claude_bin or not settings.run_workdirs:
        return False
    found = shutil.which(settings.claude_bin)
    repos = [p for p in settings.run_workdirs
             if p.is_dir() and codex_git.toplevel(p) == p.resolve()
             and not codex_git.is_server_repo(p)]
    if found is None or not repos:
        return False
    adapter = ClaudeCodeAdapter(
        found, repos, settings.data_dir, max_seconds=settings.run_max_minutes * 60
    )
    if not adapter.probe():
        return False
    registry.register("claude", adapter)
    return True
