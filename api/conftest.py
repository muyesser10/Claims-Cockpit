# api/conftest.py
"""Shared pytest setup for API tests.

api/database.py reads DATABASE_URL from the environment at import time. API
tests never touch that real engine (they override the get_db dependency
with their own in-memory SQLite session per test module), but the import
still has to succeed, so a placeholder is set here before anything under
api/ gets imported.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from sqlalchemy import BigInteger  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(type_, compiler, **kw):
    """SQLite only auto-increments a plain INTEGER PRIMARY KEY, not BIGINT.

    Production runs on Postgres (real BIGSERIAL via Alembic); this rule only
    changes DDL compiled against an in-memory SQLite test database.
    """
    return "INTEGER"
