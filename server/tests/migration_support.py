"""Schema comparison shared by the migration tests: the FTS tables are filtered by exact name."""

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from nexus.conversations.models import include_object
from nexus.db import Base


def schema_diff(db_url: str, *, filtered: bool = True) -> list:
    """`compare_metadata` of the database against the models (empty when they match)."""
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            opts = {"include_object": include_object} if filtered else {}
            context = MigrationContext.configure(conn, opts=opts)
            return compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()
