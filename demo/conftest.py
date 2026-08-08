# demo/conftest.py
"""Env placeholders for the demo scripts' tests.

Same arrangement as api/conftest.py and rag/conftest.py: demo/seed_demo_db.py
imports api.database, which reads DATABASE_URL at import time and fails loud
without it. These tests never open a connection - the guard they exercise runs
before anything does - but the import still has to succeed, and relying on
another package's conftest having been loaded first makes the run depend on
collection order.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-only-secret-do-not-use-in-prod")
