"""Migration tests.

They use their OWN database (edem_migrations_test) so they never collide with the
database the other tests use. The schema is wiped before each use, so the tests do
not depend on each other or on run order.
"""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from alembic import command
from app.core.config import get_settings
from app.db.base import Base
from tests.db_utils import ensure_test_database

ROOT = Path(__file__).resolve().parents[1]  # the edem-api folder


@pytest.fixture(scope="module")
def db_url() -> str:
    base = make_url(get_settings().TEST_DATABASE_URL)
    url = base.set(database="edem_migrations_test").render_as_string(
        hide_password=False
    )
    ensure_test_database(url)  # name ends with "_test", so the safety rule passes
    return url


@pytest.fixture(scope="module")
def alembic_cfg(db_url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    # "%" is special in config files
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    return cfg


def _reset_schema(url: str) -> None:
    """Empty the database completely (tables, enum types, alembic_version)."""
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


def _table_names(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _enum_types(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT t.typname FROM pg_type t "
                    "JOIN pg_namespace n ON n.oid = t.typnamespace "
                    "WHERE n.nspname = 'public' AND t.typtype = 'e'"
                )
            )
            return {row[0] for row in rows}
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def migrated(db_url: str, alembic_cfg: Config) -> str:
    """A fresh database upgraded to head. Shared by the read-only tests below."""
    _reset_schema(db_url)
    command.upgrade(alembic_cfg, "head")
    return db_url


def test_upgrade_creates_every_table(migrated: str):
    assert _table_names(migrated) == set(Base.metadata.tables) | {"alembic_version"}


def test_database_is_at_the_latest_revision(migrated: str, alembic_cfg: Config):
    head = ScriptDirectory.from_config(alembic_cfg).get_current_head()
    engine = create_engine(migrated)
    try:
        with engine.connect() as conn:
            assert (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                == head
            )
    finally:
        engine.dispose()


def test_models_match_migrations(migrated: str, alembic_cfg: Config):
    """Fails if a model changed but no migration was generated (same as `alembic check`)."""
    command.check(alembic_cfg)


def test_downgrade_removes_everything_and_upgrade_works_again(
    db_url: str, alembic_cfg: Config
):
    """Catches enum types left behind by downgrade, which break the next upgrade."""
    _reset_schema(db_url)
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "base")

    assert _table_names(db_url) <= {"alembic_version"}
    assert _enum_types(db_url) == set()

    command.upgrade(alembic_cfg, "head")  # must work a second time
    assert _table_names(db_url) == set(Base.metadata.tables) | {"alembic_version"}
