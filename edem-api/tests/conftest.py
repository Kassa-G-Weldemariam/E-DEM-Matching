import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

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
    """Creates tables on test start and drops them when tests complete."""
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
    Wraps each test in an isolated transaction using savepoints
    so internal session.commit() calls inside application routes work cleanly.
    """
    connection = engine.connect()
    transaction = connection.begin()

    session = TestingSessionLocal(bind=connection)
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(session, ended_transaction):
        if ended_transaction.nested and not ended_transaction.parent.nested:
            session.begin_nested()

    yield session

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
