# worker/conftest.py
"""Shared pytest setup for worker tests that touch the DB models.

Mirrors api/conftest.py's SQLite shim: SQLite only auto-increments a plain
INTEGER PRIMARY KEY, not BIGINT. Production runs on Postgres (real BIGSERIAL
via Alembic); this only changes DDL compiled against an in-memory SQLite
test database.
"""

import pytest
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles

import worker.pipeline as pipeline_module
from worker.embedding.encoder import EMBEDDING_DIMENSIONS


@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest.fixture(autouse=True)
def _no_real_encoder(monkeypatch):
    """Keep the real embedding model out of every worker test.

    process_message runs step_embed, which loads a 470 MB model on first use.
    Left alone, any test that drives the pipeline would download it - on every
    CI run, with nothing in the output explaining why the job got slow.

    Autouse rather than per-test on purpose: the cost of forgetting is paid in
    CI by whoever writes the next pipeline test, and they have no reason to know
    this trap exists. A test that wants the real path monkeypatches
    pipeline_module.store_embedding itself; that overrides this.
    """

    def _fake_store_embedding(db, claim_id, text, *, encoder=None):
        from worker.embedding.store import EmbeddingResult

        return EmbeddingResult(
            dimensions=EMBEDDING_DIMENSIONS,
            text_length=len(text),
            model="test-stub",
            duration_ms=0,
        )

    monkeypatch.setattr(pipeline_module, "store_embedding", _fake_store_embedding)
