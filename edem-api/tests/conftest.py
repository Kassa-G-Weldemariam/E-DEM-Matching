import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.db_utils import ensure_test_database

# 1. Force the test environment
os.environ["ENVIRONMENT"] = "test"

# 2. Clear settings cache BEFORE importing app modules
from app.core.config import get_settings

get_settings.cache_clear()
settings = get_settings()

# 3. Import app modules AFTER settings are cleared/reloaded
from app.db.base import Base
from app.db.session import get_db
from app.main import app as fastapi_app  # ← renamed

# 4. Engine setup
engine = create_engine(settings.active_database_url)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Creates the test database and its tables on test start, and drops the tables at the end."""
    ensure_test_database(settings.TEST_DATABASE_URL)  # new line
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def app():
    """Expose the FastAPI instance so test modules can register test-only routes."""
    return fastapi_app


@pytest.fixture
def db():
    """
    Each test runs inside an outer transaction that is thrown away at the end.
    join_transaction_mode="create_savepoint" makes the session's own commits and
    rollbacks work on savepoints, so a rollback inside a test only undoes the work
    since the last commit instead of wiping the whole test.
    """
    connection = engine.connect()
    transaction = connection.begin()

    session = TestingSessionLocal(
        bind=connection, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def client(db):
    """Overrides the get_db dependency for FastAPI test client calls."""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    fastapi_app.dependency_overrides[get_db] = override_get_db
    with TestClient(fastapi_app) as c:
        yield c

    fastapi_app.dependency_overrides.clear()
