"""API of the runs (ADR-023, lot B): hand a task to an agent, cancel, read.

Writing is for humans only (403 `human_only`); reading is open to any authenticated actor, like
tasks. Nothing here starts a process: the supervisor does, through the registered adapter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, StringConstraints

from nexus import permissions
from nexus.actors import Agent, Executor
from nexus.auth.deps import Authenticated
from nexus.clock import now
from nexus.models import Run
from nexus.runs import service
from nexus.runs.rules import AGENTS_OF
from nexus.tasks import service as tasks
from nexus.tasks.api import ActorDep, SessionDep, commit, parse_ref
from nexus.validation import InputModel

BRIEF_MAX = 20_000
WORKDIR_MAX = 500

router = APIRouter(tags=["runs"], dependencies=Authenticated)


class RunIn(InputModel):
    executor: Executor
    agent: Agent
    # The caller's own key for this click: a resend with the same key is the same run.
    client_key: Annotated[str, StringConstraints(
        strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
    brief: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=BRIEF_MAX)
    ]
    workdir: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=WORKDIR_MAX)
    ] | None = None


class ExecutorOut(BaseModel):
    """An executor that can take work now: who it works for and where (what the dialog offers)."""

    executor: str
    agents: list[str]
    workdirs: list[str]
    source: str = "nexus.db"
    measured_at: datetime


class RunOut(BaseModel):
    id: str
    task: str
    executor: str
    agent: str
    dispatched_by: str
    client_key: str
    brief: str
    workdir: str | None
    external_ref: str | None
    status: str
    native_status: str | None  # the executor's own word, as given
    created_at: datetime
    ended_at: datetime | None
    cancel_requested_at: datetime | None
    version: int
    source: str = "nexus.db"
    measured_at: datetime


def to_out(run: Run) -> RunOut:
    return RunOut(
        id=run.ref, task=f"nx-task-{run.task_id}", executor=run.executor, agent=run.agent,
        dispatched_by=run.dispatched_by, client_key=run.client_key, brief=run.brief,
        workdir=run.workdir, external_ref=run.external_ref, status=run.status,
        native_status=run.native_status, created_at=run.created_at, ended_at=run.ended_at,
        cancel_requested_at=run.cancel_requested_at, version=run.version, measured_at=now(),
    )


@router.post("/api/tasks/{task_ref}/runs", status_code=status.HTTP_201_CREATED)
def dispatch(
    task_ref: str, body: RunIn, request: Request, response: Response, session: SessionDep,
    actor: ActorDep,
) -> RunOut:
    """Hand the task to an agent. A resend with the same `client_key` is a 200 read-back."""
    permissions.check_dispatch(actor)  # before any lookup: an agent learns nothing about refs
    task = tasks.get_task(session, parse_ref(task_ref))
    run, created = service.create_run(
        session, task, actor,
        service.NewRun(body.executor, body.agent, body.client_key, body.brief, body.workdir),
        request.app.state.adapters,
    )
    commit(session)
    if not created:
        response.status_code = status.HTTP_200_OK
    return to_out(run)


@router.post("/api/runs/{run_ref}/cancel")
def cancel(run_ref: str, session: SessionDep, actor: ActorDep) -> RunOut:
    """Ask for the run to be stopped (the supervisor stops it); a repeat is a 200."""
    permissions.check_dispatch(actor)
    run = service.request_cancel(session, service.get_run(session, run_ref), actor)
    commit(session)
    return to_out(run)


@router.get("/api/executors")
def executors(request: Request) -> list[ExecutorOut]:
    """The executors with a registered adapter. Empty: nothing can be handed over (409)."""
    registry = request.app.state.adapters
    return [
        ExecutorOut(
            executor=name, agents=sorted(AGENTS_OF.get(name, ())),
            workdirs=[str(p) for p in getattr(registry.get(name), "workdirs", [])],
            measured_at=now(),
        )
        for name in registry.executors()
    ]


@router.get("/api/runs/{run_ref}")
def read(run_ref: str, session: SessionDep) -> RunOut:
    return to_out(service.get_run(session, run_ref))


@router.get("/api/tasks/{task_ref}/runs")
def list_(task_ref: str, session: SessionDep) -> list[RunOut]:
    task = tasks.get_task(session, parse_ref(task_ref))
    return [to_out(r) for r in service.list_runs(session, task)]
