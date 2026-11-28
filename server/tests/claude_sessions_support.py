"""Invented Claude Code sessions and a migrated database for the ingestion tests (ADR-025).

Everything lives under `tmp_path`: no test ever reads Loïc's real `~/.claude`. Secrets are built
at runtime; markers are `"zq" + uuid4().hex[:10]`, unique and never secret.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from nexus import migrate
from nexus.config import Settings
from nexus.db import make_engine

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
SLUG = "-F-Projet-Exemple"


def marker() -> str:
    return "zq" + uuid.uuid4().hex[:10]


def ghp() -> str:
    return "ghp_" + "A" * 36


def nxt() -> str:
    return "nxt_" + "B" * 43


def sk_ant() -> str:
    return "sk-ant-" + "C" * 40


def akia() -> str:
    return "AKIA" + "D" * 16


def new_id() -> str:
    return str(uuid.uuid4())


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _base(kind: str, *, at: datetime, line_id: str | None, session: str | None,
          cwd: str, branch: str, **extra) -> dict:
    line = {"type": kind, "uuid": line_id or new_id(), "timestamp": stamp(at),
            "sessionId": session, "isSidechain": False, "cwd": cwd, "gitBranch": branch,
            "version": "2.1.0"}
    line.update(extra)
    return line


def user(content: str | list, *, at: datetime = NOW, origin: object = "human",
         line_id: str | None = None, session: str | None = None, cwd: str = "F:\\Projet\\Ex",
         branch: str = "master", **extra) -> dict:
    """A `user` line; `origin="human"` gives `{"kind": "human"}`, None leaves it out."""
    line = _base("user", at=at, line_id=line_id, session=session, cwd=cwd, branch=branch,
                 message={"role": "user", "content": content}, **extra)
    if origin == "human":
        line["origin"] = {"kind": "human"}
    elif origin is not None:
        line["origin"] = origin
    return line


def assistant(content: str | list, *, at: datetime = NOW, model: str = "claude-opus-5-5",
              line_id: str | None = None, session: str | None = None,
              cwd: str = "F:\\Projet\\Ex", branch: str = "master", **extra) -> dict:
    return _base("assistant", at=at, line_id=line_id, session=session, cwd=cwd, branch=branch,
                 message={"role": "assistant", "model": model, "content": content}, **extra)


def text(value: str) -> dict:
    return {"type": "text", "text": value}


def title(value: str, *, kind: str = "custom-title") -> dict:
    key = "customTitle" if kind == "custom-title" else "aiTitle"
    return {"type": kind, key: value, "sessionId": None}


def encode(line: dict | str | bytes, *, eol: bytes = b"\n") -> bytes:
    if isinstance(line, bytes):
        return line + eol
    if isinstance(line, str):
        return line.encode("utf-8") + eol
    return json.dumps(line, ensure_ascii=False).encode("utf-8") + eol


def write_session(root: Path, lines: list, *, slug: str = SLUG, session: str | None = None,
                  mtime: datetime | None = NOW, append: bool = False) -> Path:
    """`<root>/<slug>/<session>.jsonl` with the encoded lines; `sessionId` filled in."""
    session = session or new_id()
    path = root / slug / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = b""
    for line in lines:
        if isinstance(line, dict) and "sessionId" in line and line["sessionId"] is None:
            line = dict(line, sessionId=session)
        data += encode(line)
    with open(path, "ab" if append else "wb") as handle:
        handle.write(data)
    if mtime is not None:
        touch(path, mtime)
    return path


def touch(path: Path, at: datetime) -> None:
    ns = int(at.timestamp() * 1e9)
    os.utime(path, ns=(ns, ns))


def conversation(n: int, *, start: datetime = NOW - timedelta(hours=1),
                 step: timedelta = timedelta(seconds=1), body: str = "message") -> list[dict]:
    """`n` alternating user and assistant lines, one second apart, ids in order."""
    lines = []
    for i in range(n):
        at = start + i * step
        line_id = f"00000000-0000-4000-8000-{i:012d}"
        make = user if i % 2 == 0 else assistant
        lines.append(make(f"{body} {i}", at=at, line_id=line_id))
    return lines


@dataclass
class Db:
    settings: Settings
    engine: Engine
    factory: sessionmaker[Session]

    @property
    def path(self) -> Path:
        return self.settings.db_path

    def raw(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def rows(self, sql: str, *params) -> list[tuple]:
        conn = self.raw()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def scalar(self, sql: str, *params):
        return self.rows(sql, *params)[0][0]

    def with_settings(self, **changes) -> Settings:
        return replace(self.settings, **changes)


def migrated(tmp_path: Path, *, timeout: float | None = None, **settings) -> Db:
    config = Settings(data_dir=tmp_path / "data", **settings)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    migrate.upgrade(config.db_url)
    engine = make_engine(config.db_url, timeout=timeout)
    return Db(config, engine, sessionmaker(engine, expire_on_commit=False))


def raw_bytes(db_path: Path) -> bytes:
    """The bytes of `nexus.db` and of its `-wal`, read as files (never through SQLite)."""
    data = db_path.read_bytes()
    wal = db_path.with_name(db_path.name + "-wal")
    if wal.exists():
        data += wal.read_bytes()
    return data
