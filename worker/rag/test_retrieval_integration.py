# worker/rag/test_retrieval_integration.py
"""search() against a real Postgres with pgvector.

Skipped unless RAG_INTEGRATION_DB is set, because the ordering here is done by
pgvector's `<=>` operator and SQLite has no such thing - the query is a syntax
error there, not a wrong answer. CI therefore never runs this file; it is run
locally against the compose database:

    docker compose start db
    $env:RAG_INTEGRATION_DB = "postgresql+psycopg://claims:...@localhost:5432/claims_cockpit"
    pytest worker/rag/test_retrieval_integration.py -q

The encoder is still stubbed. What is being tested is the SQL - the join, the
ordering, the filters and the score - not the model.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from api.models.db import Base, Claim, ClaimEmbedding, RawMessage
from worker.embedding.encoder import EMBEDDING_DIMENSIONS
from worker.rag.retrieval import search

pytestmark = pytest.mark.skipif(
    not os.environ.get("RAG_INTEGRATION_DB"),
    reason="needs Postgres with pgvector; set RAG_INTEGRATION_DB to a connection URL",
)


def _vector(first: float, second: float = 0.0) -> list[float]:
    """A vector whose direction is set by its first two components."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[0] = first
    vector[1] = second
    return vector


# The question points along the first axis. Distances from it, by construction:
# NEAR is 0 (identical direction), SIDE is 1 (orthogonal), OPPOSITE is 2.
QUESTION = _vector(1.0)
NEAR = _vector(1.0)
SIDE = _vector(0.0, 1.0)
OPPOSITE = _vector(-1.0)


class StubEncoder:
    """Returns QUESTION for the question and a fixed vector for any sentence.

    Snippet selection is covered in test_retrieval.py; here every sentence
    scores the same, so the snippet is deterministic but uninteresting.
    """

    def embed_query(self, text: str) -> list[float]:
        return QUESTION

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [_vector(0.5) for _ in texts]


@pytest.fixture
def db():
    engine = create_engine(os.environ["RAG_INTEGRATION_DB"])
    with engine.connect() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.commit()
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    # Start from a known state: these tests own the rows they assert on.
    session.execute(text("TRUNCATE claim_embeddings, audit_trail, claims, raw_messages CASCADE"))
    session.commit()
    try:
        yield session
    finally:
        session.execute(
            text("TRUNCATE claim_embeddings, audit_trail, claims, raw_messages CASCADE")
        )
        session.commit()
        session.close()


def _add_claim(
    db_session,
    *,
    external_ref: str,
    vector: list[float],
    urgency: str = "normal",
    status: str = "in_human_review",
    masked_text: str = "Arac hasar gordu.",
    incident_date: str | None = None,
) -> Claim:
    message = RawMessage(channel="email", raw_text="ham metin", external_ref=external_ref)
    db_session.add(message)
    db_session.flush()

    data: dict = {"masked_text": masked_text}
    if incident_date is not None:
        data["extraction"] = {"incident_date": incident_date}

    claim = Claim(
        raw_message_id=message.id,
        channel="email",
        content_type="claim",
        urgency=urgency,
        data=data,
        status=status,
    )
    db_session.add(claim)
    db_session.flush()
    db_session.add(ClaimEmbedding(claim_id=claim.id, embedding=vector))
    db_session.commit()
    return claim


def test_returns_claims_nearest_first(db):
    far = _add_claim(db, external_ref="FAR", vector=OPPOSITE)
    near = _add_claim(db, external_ref="NEAR", vector=NEAR)
    side = _add_claim(db, external_ref="SIDE", vector=SIDE)

    results = search(db, "dolu hasari", encoder=StubEncoder())

    assert [r.claim_id for r in results] == [near.id, side.id, far.id]


def test_score_is_one_minus_distance(db):
    _add_claim(db, external_ref="NEAR", vector=NEAR)

    result = search(db, "dolu hasari", encoder=StubEncoder())[0]

    # Identical direction: cosine distance 0, so the similarity is 1.
    assert result.score == pytest.approx(1.0, abs=1e-4)


def test_limit_caps_the_result_count(db):
    for i in range(4):
        _add_claim(db, external_ref=f"C{i}", vector=NEAR)

    assert len(search(db, "soru", limit=2, encoder=StubEncoder())) == 2


def test_urgency_filter_excludes_other_claims(db):
    critical = _add_claim(db, external_ref="CRIT", vector=SIDE, urgency="critical")
    _add_claim(db, external_ref="NORM", vector=NEAR, urgency="normal")

    results = search(db, "soru", urgency="critical", encoder=StubEncoder())

    # The normal claim is nearer, so without the filter it would come first.
    assert [r.claim_id for r in results] == [critical.id]


def test_status_filter_excludes_other_claims(db):
    approved = _add_claim(db, external_ref="APPR", vector=SIDE, status="approved")
    _add_claim(db, external_ref="QUEUED", vector=NEAR, status="in_human_review")

    results = search(db, "soru", status="approved", encoder=StubEncoder())

    assert [r.claim_id for r in results] == [approved.id]


def test_carries_external_ref_and_incident_date(db):
    _add_claim(db, external_ref="GT-000123", vector=NEAR, incident_date="2026-07-14")

    result = search(db, "soru", encoder=StubEncoder())[0]

    assert result.external_ref == "GT-000123"
    assert result.incident_date == "2026-07-14"


def test_claim_without_extraction_has_no_incident_date(db):
    """Extraction can fail while the claim is still embedded and searchable."""
    _add_claim(db, external_ref="NO-EXTRACTION", vector=NEAR)

    result = search(db, "soru", encoder=StubEncoder())[0]

    assert result.incident_date is None


def test_empty_database_returns_no_results(db):
    assert search(db, "soru", encoder=StubEncoder()) == []
