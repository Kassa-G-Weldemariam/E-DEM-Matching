"""Helpers for test databases."""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def ensure_test_database(database_url: str) -> None:
    """
    Create the target database if it does not exist.
    Safety rule: database name must end with '_test'.
    """
    url = make_url(database_url)
    db_name = url.database

    if not db_name or not db_name.endswith("_test"):
        raise ValueError(
            f"Refusing to create/use non-test database: {db_name!r}. "
            "Name must end with '_test'."
        )

    # Connect to the default maintenance DB
    admin_url = url.set(database="postgres")
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            ).scalar()

            if not exists:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        engine.dispose()
