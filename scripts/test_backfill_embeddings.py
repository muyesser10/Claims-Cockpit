# scripts/test_backfill_embeddings.py
"""Tests for the embedding backfill.

The encoder is stubbed and SessionLocal is redirected at an in-memory database,
so nothing here loads a model or reaches Postgres.
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import scripts.backfill_embeddings as backfill_module
from api.models.db import Base, Claim, ClaimEmbedding
from worker.embedding.encoder import EMBEDDING_DIMENSIONS

# StaticPool matters here: the backfill opens its own session, and without a
# shared connection each one would get a private :memory: database and see none
# of the fixture's rows.
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class _StubEncoder:
    """Returns 0.1-filled vectors, so a backfilled row is distinguishable from
    a pre-existing 0.9-filled one."""

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * EMBEDDING_DIMENSIONS for _ in texts]


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch):
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(backfill_module, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(backfill_module, "get_encoder", lambda: _StubEncoder())
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_claim(db_session, *, masked_text: str | None = "Aracim hasar gordu.", flags=None):
    data: dict = {}
    if masked_text is not None:
        data["masked_text"] = masked_text
    if flags is not None:
        data["masking_sanity_flags"] = flags
    claim = Claim(raw_message_id=1, channel="email", data=data, status="in_human_review")
    db_session.add(claim)
    db_session.commit()
    return claim


def _vectors(db_session) -> dict[int, float]:
    """claim_id -> first component, which identifies which encoder wrote it."""
    db_session.expire_all()
    rows = db_session.execute(select(ClaimEmbedding)).scalars()
    return {row.claim_id: row.embedding[0] for row in rows}


def test_dry_run_writes_nothing(db):
    _make_claim(db)

    backfill_module.backfill(dry_run=True)

    assert _vectors(db) == {}


def test_embeds_only_claims_without_a_vector(db):
    already = _make_claim(db)
    db.add(ClaimEmbedding(claim_id=already.id, embedding=[0.9] * EMBEDDING_DIMENSIONS))
    db.commit()
    fresh = _make_claim(db)

    backfill_module.backfill()

    vectors = _vectors(db)
    assert vectors[already.id] == pytest.approx(0.9), "existing vector must be left alone"
    assert vectors[fresh.id] == pytest.approx(0.1)


def test_force_re_embeds_everything(db):
    """A model change makes old vectors incomparable - --force is how they go."""
    stale = _make_claim(db)
    db.add(ClaimEmbedding(claim_id=stale.id, embedding=[0.9] * EMBEDDING_DIMENSIONS))
    db.commit()

    backfill_module.backfill(force=True)

    assert _vectors(db)[stale.id] == pytest.approx(0.1)


def test_sanity_flagged_claims_are_skipped(db):
    """The pipeline refuses to embed these; the backfill must not fill them in."""
    flagged = _make_claim(db, flags=[{"rule": "possible_pii_leak", "kind": "name", "span": [0, 5]}])

    backfill_module.backfill()

    assert flagged.id not in _vectors(db)


def test_claim_without_masked_text_is_skipped_not_fatal(db):
    """One unusable row must not stop the run for everything after it."""
    broken = _make_claim(db, masked_text=None)
    good = _make_claim(db)

    backfill_module.backfill()

    vectors = _vectors(db)
    assert broken.id not in vectors
    assert vectors[good.id] == pytest.approx(0.1)
