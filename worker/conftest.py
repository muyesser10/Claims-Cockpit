# worker/conftest.py
"""Shared pytest setup for worker tests that touch the DB models.

Mirrors api/conftest.py's SQLite shim: SQLite only auto-increments a plain
INTEGER PRIMARY KEY, not BIGINT. Production runs on Postgres (real BIGSERIAL
via Alembic); this only changes DDL compiled against an in-memory SQLite
test database.
"""

from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles


@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"
