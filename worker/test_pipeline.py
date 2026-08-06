# worker/test_pipeline.py
"""Integration tests for the S2-6 masking-sanity step wired into the pipeline.

Uses an in-memory SQLite DB (see worker/conftest.py for the BigInteger
shim). Extraction and the sanity LLM call are both stubbed via monkeypatch —
nothing here touches the network.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import worker.embedding.store as store_module
import worker.masking.sanity as sanity_module
import worker.pipeline as pipeline_module
from api.models.db import AuditTrail, Base, Claim, ClaimEmbedding, RawMessage
from worker.embedding.encoder import EMBEDDING_DIMENSIONS
from worker.embedding.store import store_embedding as real_store_embedding
from worker.extraction.extractor import ExtractionResult
from worker.masking.sanity import SanityCheckResult, SanityFlag

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


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


def _make_raw_message(db_session, text: str = "Merhaba, aracim hasar gordu.") -> RawMessage:
    msg = RawMessage(
        channel="email",
        raw_text=text,
        received_at=datetime.now(UTC),
        status="received",
    )
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)
    return msg


FAKE_EXTRACTION = ExtractionResult(
    extraction={"policy_no": None},
    reasoning="test",
    model="gpt-4o-mini",
    duration_ms=1,
    unverified_fields=[],
)


def test_sanity_disabled_skips_llm_call_but_still_writes_audit(db, monkeypatch):
    """Config off -> check_sanity is never called, but the audit row still
    records that the step ran (with enabled=False)."""
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    sanity_mock = MagicMock()
    monkeypatch.setattr(pipeline_module, "check_sanity", sanity_mock)
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: FAKE_EXTRACTION)

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    sanity_mock.assert_not_called()

    audit = db.execute(
        select(AuditTrail).where(
            AuditTrail.raw_message_id == msg.id, AuditTrail.step == "masking_sanity"
        )
    ).scalar_one()
    assert audit.detail["enabled"] is False
    assert audit.detail["leak_found"] is False


def test_sanity_leak_skips_extraction(db, monkeypatch):
    """A flagged leak must stop extraction from running at all — no OpenAI
    call over data the team just decided might still hold PII."""
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "true")
    monkeypatch.setattr(
        pipeline_module,
        "check_sanity",
        lambda *a, **k: SanityCheckResult(
            leak_found=True, flags=[SanityFlag(kind="name", span=(0, 5))]
        ),
    )
    extract_mock = MagicMock()
    monkeypatch.setattr(pipeline_module, "extract", extract_mock)

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    extract_mock.assert_not_called()

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert "extraction" not in claim.data
    assert claim.data["masking_sanity_flags"] == [
        {"rule": "possible_pii_leak", "kind": "name", "span": [0, 5]}
    ]

    audit = db.execute(
        select(AuditTrail).where(
            AuditTrail.claim_id == claim.id, AuditTrail.step == "extraction_skipped"
        )
    ).scalar_one()
    assert audit.detail == {"reason": "masking_sanity_flag"}


def test_sanity_leaked_text_never_persisted_to_db(db, monkeypatch):
    """Regression for the bug caught in review: the raw PII text sanity spots
    must never land in the masking_sanity audit row or masking_sanity_flags —
    only kind + span. (masked_text itself is a separate, pre-existing field
    that legitimately holds whatever masking left behind; this test is scoped
    to the sanity-derived fields the bug was actually in.)
    """
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "true")
    leaked_name = "Zülfikar Bey"
    monkeypatch.setattr(
        pipeline_module,
        "check_sanity",
        lambda *a, **k: SanityCheckResult(
            leak_found=True, flags=[SanityFlag(kind="name", span=(0, 5))]
        ),
    )
    monkeypatch.setattr(pipeline_module, "extract", MagicMock())

    msg = _make_raw_message(db, text=f"Karşı taraftaki sürücü {leaked_name}'di.")
    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    sanity_audit = db.execute(
        select(AuditTrail).where(
            AuditTrail.raw_message_id == msg.id, AuditTrail.step == "masking_sanity"
        )
    ).scalar_one()

    import json

    assert leaked_name not in json.dumps(claim.data["masking_sanity_flags"])
    assert leaked_name not in json.dumps(sanity_audit.detail)


class _RaisingLlmClientClass:
    """Stands in for the LlmClient *class*: raises on construction, like
    load_settings() does when OPENAI_API_KEY is unset."""

    def __init__(self, *args, **kwargs) -> None:
        raise RuntimeError("OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in.")


def test_sanity_real_fail_closed_path_skips_extraction(db, monkeypatch):
    """End-to-end proof for the fix: run the REAL check_sanity() (not a
    mocked SanityCheckResult) through a client-construction failure — the
    exact failure mode a missing OPENAI_API_KEY produces in production — and
    confirm the pipeline still routes to human review with extraction
    skipped, instead of the pipeline crashing (old bug #1) or extraction
    running anyway because flags came back empty (old bug #2).
    """
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "true")
    monkeypatch.setattr(sanity_module, "LlmClient", _RaisingLlmClientClass)
    # pipeline_module.check_sanity is NOT mocked here — the real function runs.
    extract_mock = MagicMock()
    monkeypatch.setattr(pipeline_module, "extract", extract_mock)

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    # The message must not have crashed the pipeline into dead_letter.
    assert msg.status != "dead_letter"

    extract_mock.assert_not_called()

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert claim.status == "in_human_review"
    assert "extraction" not in claim.data
    assert claim.data["masking_sanity_flags"] != []
    assert claim.data["masking_sanity_flags"][0]["kind"] == "other"

    audit = db.execute(
        select(AuditTrail).where(
            AuditTrail.claim_id == claim.id, AuditTrail.step == "extraction_skipped"
        )
    ).scalar_one()
    assert audit.detail == {"reason": "masking_sanity_flag"}


def test_sanity_clean_result_extraction_runs_normally(db, monkeypatch):
    """Regression: no leak -> extraction runs exactly as before S2-6."""
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "true")
    monkeypatch.setattr(
        pipeline_module, "check_sanity", lambda *a, **k: SanityCheckResult(leak_found=False)
    )
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: FAKE_EXTRACTION)

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert claim.data["masking_sanity_flags"] == []
    assert "extraction" in claim.data


# --- step_embed (S3-2, ADR-003) ---------------------------------------------
#
# conftest.py stubs store_embedding for every worker test so the pipeline never
# loads the real model. The tests below that assert on a stored vector put the
# real function back and stub the encoder underneath it instead.


class _StubEncoder:
    """Fixed-width vectors, no model. Mirrors worker/embedding/test_store.py."""

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * EMBEDDING_DIMENSIONS for _ in texts]


def _use_real_store_with_stub_encoder(monkeypatch):
    monkeypatch.setattr(pipeline_module, "store_embedding", real_store_embedding)
    monkeypatch.setattr(store_module, "get_encoder", lambda: _StubEncoder())


def test_embedding_writes_vector_and_audit(db, monkeypatch):
    """The happy path: a vector lands in claim_embeddings and the step is audited."""
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: FAKE_EXTRACTION)
    _use_real_store_with_stub_encoder(monkeypatch)

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    row = db.execute(select(ClaimEmbedding).where(ClaimEmbedding.claim_id == claim.id)).scalar_one()
    assert len(row.embedding) == EMBEDDING_DIMENSIONS

    audit = db.execute(
        select(AuditTrail).where(AuditTrail.claim_id == claim.id, AuditTrail.step == "embedding")
    ).scalar_one()
    assert audit.detail["dimensions"] == EMBEDDING_DIMENSIONS
    assert audit.duration_ms is not None


def test_sanity_leak_skips_embedding(db, monkeypatch):
    """Same rule as extraction: flagged PII must not reach the encoder either."""
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "true")
    monkeypatch.setattr(
        pipeline_module,
        "check_sanity",
        lambda *a, **k: SanityCheckResult(
            leak_found=True, flags=[SanityFlag(kind="name", span=(0, 5))]
        ),
    )
    embed_mock = MagicMock()
    monkeypatch.setattr(pipeline_module, "store_embedding", embed_mock)

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    embed_mock.assert_not_called()

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    audit = db.execute(
        select(AuditTrail).where(
            AuditTrail.claim_id == claim.id, AuditTrail.step == "embedding_skipped"
        )
    ).scalar_one()
    assert audit.detail == {"reason": "masking_sanity_flag"}


def test_embedding_failure_does_not_dead_letter_the_message(db, monkeypatch):
    """An embedding failure costs searchability, not triage.

    If this regresses, a model outage starts draining the human review queue
    into dead_letter - the exact failure step_extract was written to avoid.
    """
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: FAKE_EXTRACTION)

    def _boom(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(pipeline_module, "store_embedding", _boom)

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    db.refresh(msg)
    assert msg.status != "dead_letter"

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert claim.status == "in_human_review"

    audit = db.execute(
        select(AuditTrail).where(
            AuditTrail.claim_id == claim.id, AuditTrail.step == "embedding_error"
        )
    ).scalar_one()
    assert "model unavailable" in audit.detail["error"]


def test_embedding_runs_even_when_extraction_fails(db, monkeypatch):
    """The two steps are independent, which is why step_embed sits in
    process_message rather than inside step_extract. A claim nobody could
    extract is still a claim an operator may ask about."""
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")

    def _extraction_boom(*args, **kwargs):
        raise RuntimeError("openai down")

    monkeypatch.setattr(pipeline_module, "extract", _extraction_boom)
    _use_real_store_with_stub_encoder(monkeypatch)

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert "extraction" not in claim.data

    row = db.execute(select(ClaimEmbedding).where(ClaimEmbedding.claim_id == claim.id)).scalar_one()
    assert len(row.embedding) == EMBEDDING_DIMENSIONS
