"""The Codex adapter (ADR-023, lot C): `codex exec` in a git worktree of its own.

How a run goes: a worktree and a branch `nexus/nx-run-<n>` are made in a repository of
`NEXUS_RUN_WORKDIRS`; after the checks of `codex_cli` (locations, home of Nexus, MCP servers and
skills, spec #186 §5.3), `codex exec --json --sandbox workspace-write` starts there with the brief
on its standard input (never in an argument) and a filtered environment; a reader thread turns the
JSONL it prints into events kept in memory (the raw output is never written anywhere);
`watch` hands them to the supervisor, which publishes them (masking secrets). The agent never
commits (its sandbox cannot write the git directory): when its turn ended well, the whole process
tree is stopped, the branch and the worktree's `.git` file are checked untouched, and NEXUS
commits what it wrote (`run_commit`, spec #186 §1.3); the end is judged on that commit (D6).
Nexus never pushes or merges. Nothing here blocks: every wait has a timeout.

A run is lost if the server stops (its in-memory story goes with it): the supervisor then marks it
`unknown` and a human cancels or reviews the branch. `recover` knows nothing.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from nexus.adapters import codex_cli, codex_git, codex_process, run_commit
from nexus.adapters.base import Dispatched, RunInfo, WatchResult
from nexus.adapters.codex_job import Job as _Job
from nexus.adapters.codex_translate import BREACH_SUBJECT
from nexus.adapters.registry import AdapterRegistry
from nexus.adapters.run_commit_end import closing, commit_wins
from nexus.config import Settings

log = logging.getLogger("nexus.codex")

PROBE_TIMEOUT = 10.0
KEEP_FINISHED = 20  # closed jobs kept in memory, for a late re-read


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
        self.codex_home = data_dir.resolve() / "codex-home"  # Loïc logs in there once (§5.2)
        self.control_timeout = codex_cli.CONTROL_TIMEOUT  # each control call of the launch
        self.keep_finished = KEEP_FINISHED
        self.max_seconds, self.environ = max_seconds, environ
        self.max_file_bytes = run_commit.MAX_FILE_BYTES  # smaller in tests
        self.commit_budget = run_commit.COMMIT_BUDGET
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
        identity = run_commit.resolve_identity(repo)  # pinned for the commit (§1.4, 2)
        run_commit.check_no_filter_driver(repo)  # before `worktree add` runs a smudge (§1.4, 3)
        common = codex_git.common_dir(repo)
        if common is None:
            raise ValueError("dossier git du dépôt illisible")
        env = codex_cli.child_env(self.environ, self.codex_home)
        windows = sys.platform == "win32"
        places = {"common_dir": common, "codex_home": self.codex_home}
        # Before the worktree exists: a refusal leaves neither branch nor worktree (§1.4, 4).
        codex_cli.check_locations(env, gitdir=None, worktree=self.worktrees / run.ref, **places)
        self.codex_home.mkdir(parents=True, exist_ok=True)
        tree = codex_git.create_worktree(repo, self.worktrees, run.ref)
        try:
            gitdir = run_commit.worktree_gitdir(tree)
            codex_cli.check_locations(env, gitdir=gitdir, worktree=tree.path, **places)
            dotgit = (tree.path / ".git").read_bytes()  # checked unchanged before the commit
            codex_cli.check_isolation(self.binary, tree.path, env, windows=windows,
                                      timeout=self.control_timeout)
            process = codex_process.spawn(
                codex_cli.argv(self.binary, tree.path, windows=windows), str(tree.path), env,
                contain=True)
        except codex_cli.ControlNotStopped:
            log.warning("contrôle de %s non arrêté : worktree laissé en place", run.ref)
            raise
        except BaseException:
            self._undo_launch(tree)
            raise
        job = _Job(tree, process, gitdir=gitdir, identity=identity, run_ref=run.ref,
                   dotgit=dotgit)
        job.reader = threading.Thread(target=job.read, daemon=True)
        job.reader.start()
        threading.Thread(target=self._feed, args=(process, run.brief), daemon=True).start()
        with self._lock:
            self._jobs[run.ref] = job
            self._prune()
        return Dispatched(external_ref=tree.branch, native_status="started")

    @staticmethod
    def _undo_launch(tree: codex_git.Worktree) -> None:
        """Remove the worktree and branch of a launch that failed; never hides the cause."""
        for args in (("worktree", "remove", "--force", str(tree.path)),
                     ("branch", "-D", tree.branch)):
            try:
                codex_git.git(tree.repo, *args)
            except Exception as exc:
                log.warning("nettoyage d'un lancement : %s", type(exc).__name__)

    @staticmethod
    def _feed(process: subprocess.Popen, brief: str) -> None:
        text = (brief + codex_cli.INSTRUCTION).encode("utf-8", "replace")  # no newline change
        try:
            process.stdin.buffer.write(text)
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

        The end is judged on the main process alone (spec #186, §1.3, end detection): a
        background process of the agent may inherit the output pipe, and waiting for the reader
        would keep the run open until the maximum duration. Once it has exited, the whole tree is
        stopped (confirmed), which closes the last writers of the pipe, and the reader is joined:
        what the pipe already held is still read. A reader still alive after that leaves the run
        open (no decision on half-read output).
        """
        if job.settled or not job.settle_lock.acquire(blocking=False):
            return
        try:
            if job.breach is not None:  # at once: no wait for the end nor the maximum duration
                self._stop_tree(job)
                self._fail_breach(job)
                return
            if job.commit_attempted:  # step 0: an earlier pass called `commit_run`; it wins
                self._stop_tree(job)
                self._commit(job)
                return
            ended = codex_process.exited(job.process)
            if ended and job.ended_at is None:  # a pipe held open must not age the run
                job.ended_at = time.monotonic()
            elapsed = (job.ended_at or time.monotonic()) - job.started
            over = elapsed >= self.max_seconds  # judged on when it ended, not when we looked
            if not ended and not over:
                return
            if over:
                self._stop_tree(job)  # also when it already ended: its children may not have
                job.add("failed", "Durée maximale dépassée", final=True,
                        payload={"cause": "durée maximale dépassée : processus arrêté"})
                return
            self._stop_tree(job)  # also after a clean exit
            if job.reader.is_alive():
                raise RuntimeError("lecture de la sortie non terminée")
            self._close_ended(job)
        finally:
            job.settle_lock.release()

    @staticmethod
    def _stop_tree(job: _Job) -> None:
        if not codex_process.kill_tree(job.process):
            raise RuntimeError("arrêt du processus non confirmé")
        job.reader.join(5.0)

    @staticmethod
    def _fail_breach(job: _Job) -> None:
        job.add("failed", BREACH_SUBJECT, payload={"cause": job.breach}, final=True)

    def _close_ended(self, job: _Job) -> None:
        # Checked again now that the reader is over: a breach may have come in its last lines.
        if job.breach is not None:
            self._fail_breach(job)
            return
        code = job.process.returncode
        with job.lock:
            failure, last_error, turn_done = job.failure, job.last_error, job.turn_done
        if failure or code != 0 or not turn_done:
            stopped = f"le processus s'est arrêté (code {code})"
            if turn_done and not failure:  # the turn ended, the exit did not: the exit is the cause
                cause = stopped
            else:  # an `error` line alone never decides, but it beats a bare exit code (#176)
                cause = failure or last_error or f"{stopped} sans terminer son tour"
            job.add("failed", "Codex a échoué", payload={"cause": cause}, final=True)
            return
        cause = job.tampered()  # skipped after a commit attempt: `_settle` took it first
        if cause is not None:
            job.add("failed", BREACH_SUBJECT, payload={"cause": cause},
                    evidence=[f"branch:{job.tree.branch}"], final=True)
            return
        self._commit(job)

    def _commit(self, job: _Job) -> None:
        """Nexus commits what the agent wrote, the tree being stopped (precondition 2 of
        `run_commit`) and the guards held, or an earlier pass having tried already."""
        job.commit_attempted = True
        request = run_commit.CommitRequest(
            tree=job.tree, gitdir=job.gitdir, identity=job.identity, run_ref=job.run_ref,
            adapter=self.name, label="Codex", model=None,
        )
        if not isinstance(job.outcome, run_commit.Committed):  # a commit made is kept: a
            # second pass whose proof read fails must not turn it into a failure
            job.outcome = run_commit.commit_run(
                request, max_file_bytes=self.max_file_bytes, budget=self.commit_budget)
        kind, subject, fields = closing(job.outcome, "Codex", job.tree.branch)
        job.add(kind, subject, final=True, **fields)

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
        status = "exited" if codex_process.exited(job.process) else "running"
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
        commit_wins(job, self._settle)  # after a commit attempt, the commit wins (§1.3)
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
        return job is not None and codex_process.exited(job.process)


def register_configured(
    registry: AdapterRegistry, settings: Settings, *, windows: bool | None = None
) -> bool:
    """Register Codex only when it can work: a usable binary, a git repository to work in, and a
    confirmed stop of its process tree. Outside Windows that stop is not confirmed (a descendant
    may leave the process group, spec #186 §4.3): Codex is then registered only with
    `NEXUS_RUN_WEAK_CONTAINMENT=1`, never for a real run.

    Otherwise nothing is registered and handing work to Codex stays a 409 `executor_unavailable`.
    """
    windows = sys.platform == "win32" if windows is None else windows
    if settings.run_weak_containment:
        log.warning("NEXUS_RUN_WEAK_CONTAINMENT=1 : arrêt des processus des runs non garanti "
                    "hors Windows, jamais pour un vrai run")
    elif not windows:
        return False
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
