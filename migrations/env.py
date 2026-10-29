from alembic import context

from app.core.config import get_settings
from app.core.db import UTCDateTime, make_engine
from app.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # Tests (or tooling) may pass an explicit URL; otherwise use the app's configuration.
    return config.attributes.get("database_url") or get_settings().database_url


def render_item(type_, obj, autogen_context):
    """Render the app's UTCDateTime as a plain DateTime so migrations don't import app code."""
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime()"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite needs batch mode for ALTER TABLE
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
