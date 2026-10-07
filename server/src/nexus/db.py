"""Accès à nexus.db (SQLite)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

from nexus.clock import TZ


class Base(DeclarativeBase):
    pass


class AwareDateTime(TypeDecorator):
    """Instant avec fuseau : stocké en ISO-8601 UTC, relu en Europe/Paris (DATA-MODEL §1)."""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("instant sans fuseau refusé")
        return value.astimezone(UTC).isoformat()

    def process_result_value(self, value: str | None, dialect) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value).astimezone(TZ)


def make_engine(url: str, *, timeout: float | None = None) -> Engine:
    """`timeout`: seconds sqlite waits on a locked database (the driver default when None)."""
    connect_args = {} if timeout is None else {"timeout": timeout}
    engine = create_engine(url, connect_args=connect_args)

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine
