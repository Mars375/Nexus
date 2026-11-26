from alembic import context

from nexus import models  # noqa: F401 — enregistre les tables sur Base.metadata
from nexus.config import Settings
from nexus.conversations.models import include_object
from nexus.db import Base, make_engine

config = context.config
url = config.get_main_option("sqlalchemy.url") or Settings.from_env().db_url


def run_migrations_offline() -> None:
    # include_object: the FTS tables of 0010 are raw SQL, outside the models (ADR-025).
    context.configure(
        url=url, target_metadata=Base.metadata, render_as_batch=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=Base.metadata, render_as_batch=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
