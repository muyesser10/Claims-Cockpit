# rag/conftest.py
"""Shared pytest setup for the rag service.

Mirrors api/conftest.py: api/database.py reads DATABASE_URL at import time and
api/security.py reads JWT_SECRET the same way, both failing loud if missing.
These tests never touch the real Postgres - the get_db dependency is overridden
with an in-memory SQLite session - but the imports still have to succeed, so
placeholders are set before anything under api/ or rag/ is imported.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-only-secret-do-not-use-in-prod")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import BigInteger, create_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from api.database import get_db  # noqa: E402
from api.models.db import Base, User  # noqa: E402
from api.security import create_access_token, hash_password  # noqa: E402
from rag.main import app  # noqa: E402


@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(type_, compiler, **kw):
    """SQLite only auto-increments a plain INTEGER PRIMARY KEY, not BIGINT."""
    return "INTEGER"


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    """A client that does NOT run the lifespan.

    Deliberate: the lifespan loads the 470 MB e5 model, and no test here needs
    it. TestClient only runs startup when used as a context manager, so plain
    construction keeps the model out of the test run.
    """
    return TestClient(app)


@pytest.fixture
def test_user(db_session) -> User:
    user = User(
        email="operator@test.com",
        password_hash=hash_password("test-password"),
        role="operator",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    token = create_access_token(test_user)
    return {"Authorization": f"Bearer {token}"}
