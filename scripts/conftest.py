# scripts/conftest.py
"""Shared pytest setup for script tests.

Two jobs, both mirroring api/conftest.py:

api/database.py reads DATABASE_URL at import time and fails loud without it.
Script tests never reach the real Postgres - they redirect SessionLocal at an
in-memory database - but the import still has to succeed, so a placeholder is
set before anything under api/ is imported.

The BigInteger rule is the same SQLite shim api/ and worker/ carry. It is
repeated rather than imported because pytest only loads the conftest.py files
on the path to the test being collected.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-only-secret-do-not-use-in-prod")

from sqlalchemy import BigInteger  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"
