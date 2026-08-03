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

import worker.pipeline as pipeline_module
from api.models.db import AuditTrail, Base, Claim, RawMessage
from worker.extraction.extractor import ExtractionResult
from worker.masking.sanity import SanityCheckResult

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
        lambda *a, **k: SanityCheckResult(leak_found=True, flagged_snippets=["Zülfikar Bey"]),
    )
    extract_mock = MagicMock()
    monkeypatch.setattr(pipeline_module, "extract", extract_mock)

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    extract_mock.assert_not_called()

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert "extraction" not in claim.data
    assert claim.data["masking_sanity_flags"] == [
        {"rule": "possible_pii_leak", "message": "Zülfikar Bey"}
    ]

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
