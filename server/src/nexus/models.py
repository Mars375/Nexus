"""Modèle de données Nexus (DATA-MODEL.md)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.actors import ACTORS
from nexus.db import AwareDateTime, Base


class AppMeta(Base):
    """Métadonnées de l'instance (date de création, etc.)."""

    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Task(Base):
    """Unité de travail durable ; source de vérité : nexus.db (ADR-012, DATA-MODEL §2.4)."""

    __tablename__ = "tasks"
    __table_args__ = (
        # ADR-004, garanti par la base même en cas de requêtes simultanées.
        Index(
            "uq_tasks_one_main_in_progress", "human_owner", unique=True,
            sqlite_where=text("status = 'in_progress' AND operation_role = 'main'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), index=True)
    human_owner: Mapped[str] = mapped_column(String(32), index=True)
    lead_agent: Mapped[str | None] = mapped_column(String(32))
    collaborators: Mapped[list[str]] = mapped_column(JSON, default=list)
    next_action: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(AwareDateTime)
    follow_up_at: Mapped[datetime | None] = mapped_column(AwareDateTime)
    block_cause: Mapped[str | None] = mapped_column(Text)
    block_plan: Mapped[str | None] = mapped_column(Text)
    drop_reason: Mapped[str | None] = mapped_column(Text)
    expected_evidence: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    priority: Mapped[str] = mapped_column(String(16))
    operation_role: Mapped[str | None] = mapped_column(String(16))
    origin: Mapped[str | None] = mapped_column(Text)
    context: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(AwareDateTime)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime)
    # Verrou optimiste : une écriture fondée sur un état périmé échoue au lieu d'écraser.
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": version}

    @property
    def ref(self) -> str:
        return f"nx-task-{self.id}"


class TaskDependency(Base):
    """`task_id` n'entre en in_progress, review ou done que si `depends_on_id` est traitée.

    Traitée = done ou dropped (rules.DEPENDENCY_RESOLVED).
    """

    __tablename__ = "task_dependencies"

    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )


class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(AwareDateTime)


class TaskHistory(Base):
    """Journal immuable des mutations d'une tâche : qui, quoi, quand, avant/après."""

    __tablename__ = "task_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(32))
    at: Mapped[datetime] = mapped_column(AwareDateTime)
    action: Mapped[str] = mapped_column(String(32))
    changes: Mapped[dict] = mapped_column(JSON, default=dict)


class Event(Base):
    """Fait publié par un acteur (EVENT-PROTOCOL) ; immuable une fois écrit."""

    __tablename__ = "events"
    __table_args__ = (
        # Un même identifiant d'acteur ne crée jamais deux événements (renvoi = relecture).
        UniqueConstraint("actor", "actor_event_id", name="uq_events_actor_event_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(32), index=True)
    actor_event_id: Mapped[str] = mapped_column(String(128))
    at: Mapped[datetime] = mapped_column(AwareDateTime)
    received_at: Mapped[datetime] = mapped_column(AwareDateTime)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    run_ref: Mapped[str | None] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16), index=True)
    requested_kind: Mapped[str | None] = mapped_column(String(16))
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    needs: Mapped[list[str]] = mapped_column(JSON, default=list)
    redacted: Mapped[list[str]] = mapped_column(JSON, default=list)
    # D'où vient l'événement : « api » (agent direct) ou le nom d'un adaptateur (hermes…).
    origin: Mapped[str] = mapped_column(String(32))
    effects: Mapped[list[dict]] = mapped_column(JSON, default=list)

    @property
    def ref(self) -> str:
        return f"nx-evt-{self.id}"


class Approval(Base):
    """Decision state of an ask addressed to a human (DATA-MODEL §2.10, ADR-019).

    A light state table: the content (subject, body, requester, task, options, consequence) is
    never copied, it is read from the immutable request event. `status` stores only
    pending|approved|rejected|answered; `expired` is computed at read time from `expires_at`.
    """

    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("request_event_id", name="uq_approvals_request_event_id"),
        UniqueConstraint("response_event_id", name="uq_approvals_response_event_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    ask_kind: Mapped[str] = mapped_column(String(16))  # question | needs_human, from the event
    # Typed copy of payload.expires_at, an instant: compared as such, never as text.
    expires_at: Mapped[datetime | None] = mapped_column(AwareDateTime)
    status: Mapped[str] = mapped_column(String(16), index=True)
    response_event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"))
    # Optimistic lock, as Task: two simultaneous decisions cannot both win.
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": version}

    @property
    def ref(self) -> str:
        return f"nx-appr-{self.id}"


class ActorToken(Base):
    """Bearer token of an actor (ADR-020). Only the SHA-256 digest is stored, never the token:
    the digest cannot authenticate and does not reveal the token (SECURITY §1)."""

    __tablename__ = "actor_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_actor_tokens_token_hash"),
        CheckConstraint(
            "actor IN (" + ", ".join(f"'{a}'" for a in sorted(ACTORS)) + ")",
            name="ck_actor_tokens_actor",
        ),
        CheckConstraint("length(label) BETWEEN 1 AND 64", name="ck_actor_tokens_label"),
        CheckConstraint("length(token_hash) = 64", name="ck_actor_tokens_token_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(AwareDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(AwareDateTime)

    @property
    def ref(self) -> str:
        return f"nx-tok-{self.id}"
