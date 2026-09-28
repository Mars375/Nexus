"""Modèle de données Nexus (DATA-MODEL.md)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

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
