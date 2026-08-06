# worker/embedding/test_store.py
"""Tests for the embedding store.

Nothing here loads the real model - every test passes a stub encoder, same rule
as test_encoder.py. CI has neither the 470 MB nor the time.
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from api.models.db import Base, Claim, ClaimEmbedding
from worker.embedding.encoder import EMBEDDING_DIMENSIONS
from worker.embedding.store import store_embedding

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class FakeEncoder:
    """Records which method was called with what, and returns fixed vectors.

    The two methods are recorded separately because which one runs is the point
    of one of the tests: e5 needs the passage marker on stored text, and getting
    that wrong degrades retrieval without failing anything (ADR-002).
    """

    def __init__(self, fill: float = 0.1) -> None:
        self.passage_calls: list[list[str]] = []
        self.query_calls: list[str] = []
        self.fill = fill

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        self.passage_calls.append(list(texts))
        return [[self.fill] * EMBEDDING_DIMENSIONS for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return [self.fill] * EMBEDDING_DIMENSIONS


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_claim(db_session) -> Claim:
    claim = Claim(
        raw_message_id=1,
        channel="email",
        data={"masked_text": "Aracim [PLATE_1] hasar gordu."},
        status="in_human_review",
    )
    db_session.add(claim)
    db_session.commit()
    return claim


def test_empty_text_is_refused_and_nothing_is_written(db):
    """An empty vector would rank against real ones and explain nothing."""
    claim = _make_claim(db)
    encoder = FakeEncoder()

    with pytest.raises(ValueError):
        store_embedding(db, claim.id, "   ", encoder=encoder)

    assert db.execute(select(ClaimEmbedding)).all() == []
    # The model is never asked to encode whitespace.
    assert encoder.passage_calls == []


def test_stores_a_vector_of_the_column_width(db):
    claim = _make_claim(db)

    result = store_embedding(db, claim.id, "park halinde carpilmis", encoder=FakeEncoder())
    db.commit()

    row = db.execute(select(ClaimEmbedding)).scalar_one()
    assert row.claim_id == claim.id
    assert len(row.embedding) == EMBEDDING_DIMENSIONS
    assert result.dimensions == EMBEDDING_DIMENSIONS


def test_second_call_overwrites_instead_of_colliding(db):
    """claim_id is the primary key: reprocessing a message must not raise."""
    claim = _make_claim(db)

    store_embedding(db, claim.id, "ilk metin", encoder=FakeEncoder(fill=0.1))
    db.commit()
    store_embedding(db, claim.id, "duzeltilmis metin", encoder=FakeEncoder(fill=0.9))
    db.commit()

    rows = db.execute(select(ClaimEmbedding)).scalars().all()
    assert len(rows) == 1
    assert rows[0].embedding[0] == pytest.approx(0.9)


def test_claim_text_goes_in_as_a_passage_not_a_query(db):
    """e5's markers are asymmetric. Stored text is what gets searched *through*."""
    claim = _make_claim(db)
    encoder = FakeEncoder()

    store_embedding(db, claim.id, "dolu yagdi araba hasar gordu", encoder=encoder)

    assert encoder.passage_calls == [["dolu yagdi araba hasar gordu"]]
    assert encoder.query_calls == []


def test_result_carries_what_the_audit_trail_needs(db):
    claim = _make_claim(db)
    text = "arac park halindeyken arkadan carpildi"

    result = store_embedding(db, claim.id, text, encoder=FakeEncoder())

    assert result.text_length == len(text)
    assert result.model  # resolved from EMBED_MODEL or the ADR-002 default
    assert result.duration_ms >= 0
