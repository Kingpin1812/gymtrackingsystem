"""The Alembic migrations must produce exactly the schema the models describe."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app.core.config import PROJECT_ROOT
from app.core.db import make_engine
from app.models import Base


def _config(url: str) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = url
    return cfg


def test_upgrade_matches_models_and_downgrade_is_clean(tmp_path):
    url = f"sqlite:///{(tmp_path / 'mig.db').as_posix()}"
    cfg = _config(url)
    command.upgrade(cfg, "head")

    engine = make_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"Models and migrations differ: {diff}"

    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()


def test_open_session_unique_index_exists(tmp_path):
    url = f"sqlite:///{(tmp_path / 'mig.db').as_posix()}"
    command.upgrade(_config(url), "head")
    engine = make_engine(url)
    indexes = {i["name"]: i for i in inspect(engine).get_indexes("attendance_sessions")}
    assert indexes["uq_attendance_one_open_per_member"]["unique"]
    engine.dispose()
