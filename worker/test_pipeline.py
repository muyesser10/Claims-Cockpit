# worker/test_pipeline.py
"""Integration tests for the pipeline steps: masking sanity, classification,
extraction and embedding, as process_message wires them together.

Uses an in-memory SQLite DB (see worker/conftest.py for the BigInteger
shim). Extraction, classification and the sanity LLM call are all stubbed —
nothing here touches the network. Classification is stubbed by an autouse
fixture in conftest; a test that wants a particular verdict overrides it.
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
from worker.classification.classifier import (
    FALLBACK,
    INJURY_OVERRIDE,
    LLM_URGENCY,
    ClassificationResult,
)
from worker.classification.classifier import classify as real_classify
from worker.classification.schema import ContentType, Urgency
from worker.embedding.encoder import EMBEDDING_DIMENSIONS
from worker.embedding.store import store_embedding as real_store_embedding
from worker.extraction.extractor import ExtractionResult
from worker.llm.client import OFFLINE_CHEAP_MODEL
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


def _classification(**kwargs) -> ClassificationResult:
    defaults = {
        "content_type": ContentType.CLAIM,
        "urgency": Urgency.NORMAL,
        "llm_urgency": Urgency.NORMAL,
        "urgency_source": LLM_URGENCY,
        "injury_signals": [],
        "reasoning": "test",
        "model": "gpt-4o-mini",
        "duration_ms": 5,
    }
    return ClassificationResult(**{**defaults, **kwargs})


def _stub_classify(monkeypatch, result: ClassificationResult) -> None:
    """Override conftest's autouse stub with one particular verdict."""
    monkeypatch.setattr(pipeline_module, "classify", lambda *a, **k: result)


def _audit(db_session, step: str, msg_id: int) -> AuditTrail:
    return db_session.execute(
        select(AuditTrail).where(AuditTrail.raw_message_id == msg_id, AuditTrail.step == step)
    ).scalar_one()


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


# --- classification ------------------------------------------------------


def test_the_classifiers_verdict_reaches_the_claim(db, monkeypatch):
    """Both fields used to be decided without the classifier: content_type was
    the literal "claim" and urgency came from a keyword check."""
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: FAKE_EXTRACTION)
    _stub_classify(monkeypatch, _classification(urgency=Urgency.HIGH, llm_urgency=Urgency.HIGH))

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert claim.content_type == "claim"
    # The tier that could not exist before: the old rule produced critical or
    # normal and nothing else, so the queue had two levels instead of three.
    assert claim.urgency == "high"


def test_the_audit_row_can_explain_who_caught_a_critical_claim(db, monkeypatch):
    """Critical recall (CLAUDE.md §7, >= 97%) is a number that has to be
    explainable: the model finding an injury and the deterministic rule catching
    one the model missed are different facts about the system."""
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: FAKE_EXTRACTION)
    _stub_classify(
        monkeypatch,
        _classification(
            urgency=Urgency.CRITICAL,
            llm_urgency=Urgency.NORMAL,
            urgency_source=INJURY_OVERRIDE,
            injury_signals=["yarali"],
        ),
    )

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    detail = _audit(db, "classification", msg.id).detail
    assert detail["urgency"] == "critical"
    # The model would have let this one through.
    assert detail["llm_urgency"] == "normal"
    assert detail["urgency_source"] == INJURY_OVERRIDE
    assert detail["injury_signals"] == ["yarali"]


def test_a_question_is_not_extracted(db, monkeypatch):
    """Design doc §4's early exit. A question about a policy has no plate or
    incident date to pull out, and asking anyway spends a call to be told
    nothing - or worse, to be told something."""
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    extract_mock = MagicMock()
    monkeypatch.setattr(pipeline_module, "extract", extract_mock)
    _stub_classify(monkeypatch, _classification(content_type=ContentType.INFO_REQUEST))

    msg = _make_raw_message(db, "Policemin kapsami nedir?")
    pipeline_module.process_message(db, msg.id)

    extract_mock.assert_not_called()
    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert claim.content_type == "info_request"

    audit = db.execute(
        select(AuditTrail).where(
            AuditTrail.claim_id == claim.id, AuditTrail.step == "extraction_skipped"
        )
    ).scalar_one()
    assert audit.detail["reason"] == "not_a_claim"
    assert audit.detail["content_type"] == "info_request"


def test_an_irrelevant_message_still_reaches_a_human(db, monkeypatch):
    """Auto-archiving is the auto-approve decision, which does not exist yet.
    Until it does, a wrong `irrelevant` verdict must not silently drop a claim."""
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    monkeypatch.setattr(pipeline_module, "extract", MagicMock())
    _stub_classify(monkeypatch, _classification(content_type=ContentType.IRRELEVANT))

    msg = _make_raw_message(db, "Merhaba, calisma saatleriniz nedir?")
    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert claim.content_type == "irrelevant"
    assert claim.status == "in_human_review"


def test_a_failed_classification_falls_back_instead_of_dead_lettering(db, monkeypatch):
    """Dropping the message would lose an injury report, which is the one error
    CLAUDE.md §7 will not accept. Degraded triage beats no triage."""
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: FAKE_EXTRACTION)

    def _classify_boom(*args, **kwargs):
        raise RuntimeError("openai down")

    monkeypatch.setattr(pipeline_module, "classify", _classify_boom)

    msg = _make_raw_message(db, "Kaza yaptım, yaralı var, ambulans çağırdık.")
    pipeline_module.process_message(db, msg.id)

    db.refresh(msg)
    assert msg.status != "dead_letter"

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    # The injury terms run with no model involved, so the claim still goes red.
    assert claim.urgency == "critical"
    assert claim.content_type == "claim"

    audit = _audit(db, "classification_error", msg.id)
    assert "openai down" in audit.detail["error"]


def test_the_fallback_leaves_a_message_without_injury_at_normal(db, monkeypatch):
    """The high tier is unavailable while the model is down - a loss of
    resolution, not of safety. Asserted so nobody 'fixes' it by guessing."""
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: FAKE_EXTRACTION)

    def _classify_boom(*args, **kwargs):
        raise RuntimeError("openai down")

    monkeypatch.setattr(pipeline_module, "classify", _classify_boom)

    msg = _make_raw_message(db, "Aracimin cami catladi.")
    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert claim.urgency == "normal"
    assert _audit(db, "classification_error", msg.id).detail["fallback_urgency"] == "normal"


def test_the_routing_row_records_the_verdict_it_routed_on(db, monkeypatch):
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: FAKE_EXTRACTION)
    _stub_classify(monkeypatch, _classification(urgency=Urgency.HIGH, llm_urgency=Urgency.HIGH))

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    detail = _audit(db, "routing", msg.id).detail
    assert detail["content_type"] == "claim"
    assert detail["urgency"] == "high"
    assert detail["status"] == "in_human_review"


def test_the_test_stub_still_applies_the_injury_rule(db, monkeypatch):
    """conftest's autouse stub is the classifier's own fallback, not a constant.

    A stub that always answered `normal` would let an injury-override regression
    pass every pipeline test in this file.
    """
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: FAKE_EXTRACTION)

    msg = _make_raw_message(db, "Kaza oldu, yaralı var.")
    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert claim.urgency == "critical"
    assert _audit(db, "classification", msg.id).detail["urgency_source"] == INJURY_OVERRIDE


# An extraction that survives every validation rule. FAKE_EXTRACTION does not:
# with plate and incident_date both null it trips claim_missing_core_fields,
# which is the right behaviour and the wrong fixture for testing approval.
VALID_EXTRACTION = ExtractionResult(
    extraction={
        "policy_no": "POL-2026-00001",
        "plate": "34 ABC 123",
        "incident_date": "2026-07-15",
        "damage_type": "collision",
        "injury": False,
        "counterparty_exists": True,
        "estimated_amount": 12500.0,
    },
    reasoning="test",
    model="gpt-4o-mini",
    duration_ms=1,
    unverified_fields=[],
)


def _clean_extraction(db, monkeypatch) -> None:
    """A message that reaches auto-approval with nothing against it."""
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: VALID_EXTRACTION)
    _stub_classify(monkeypatch, _classification())


def test_auto_approval_is_off_unless_switched_on(db, monkeypatch):
    """It ships closed: §7 asks for >= 95% precision and no run has measured
    it yet."""
    monkeypatch.delenv("AUTO_APPROVE_ENABLED", raising=False)
    _clean_extraction(db, monkeypatch)

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert claim.status == "in_human_review"
    assert _audit(db, "auto_approve", msg.id).detail["reasons"] == ["auto_approve_disabled"]


def test_a_clean_claim_is_approved_when_the_gate_is_open(db, monkeypatch):
    monkeypatch.setenv("AUTO_APPROVE_ENABLED", "true")
    _clean_extraction(db, monkeypatch)

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert claim.status == "approved"

    detail = _audit(db, "auto_approve", msg.id).detail
    assert detail["approved"] is True
    assert detail["reasons"] == []


def test_a_critical_claim_is_never_auto_approved(db, monkeypatch):
    monkeypatch.setenv("AUTO_APPROVE_ENABLED", "true")
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: FAKE_EXTRACTION)
    _stub_classify(monkeypatch, _classification(urgency=Urgency.CRITICAL))

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert claim.status == "in_human_review"
    assert "critical_urgency" in _audit(db, "auto_approve", msg.id).detail["reasons"]


def test_an_unverified_field_keeps_the_claim_in_the_queue(db, monkeypatch):
    """The gate reads unverified_fields off the claim, which is why
    step_extract stores them there and not only in its audit row."""
    monkeypatch.setenv("AUTO_APPROVE_ENABLED", "true")
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    monkeypatch.setattr(
        pipeline_module,
        "extract",
        lambda *a, **k: ExtractionResult(
            extraction={"policy_no": None},
            reasoning="test",
            model="gpt-4o-mini",
            duration_ms=1,
            unverified_fields=["estimated_amount"],
        ),
    )
    _stub_classify(monkeypatch, _classification())

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert claim.data["unverified_fields"] == ["estimated_amount"]
    assert claim.status == "in_human_review"
    assert "unverified_fields" in _audit(db, "auto_approve", msg.id).detail["reasons"]


def test_a_claim_whose_extraction_failed_is_never_approved(db, monkeypatch):
    monkeypatch.setenv("AUTO_APPROVE_ENABLED", "true")
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")

    def _extraction_boom(*args, **kwargs):
        raise RuntimeError("openai down")

    monkeypatch.setattr(pipeline_module, "extract", _extraction_boom)
    _stub_classify(monkeypatch, _classification())

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert claim.status == "in_human_review"
    assert "no_extraction" in _audit(db, "auto_approve", msg.id).detail["reasons"]


def test_the_audit_row_is_written_for_held_claims_too(db, monkeypatch):
    """'Why did this need a human' is what the error centre and the precision
    measurement both ask; recording only the approvals would leave the
    interesting half unrecorded."""
    monkeypatch.setenv("AUTO_APPROVE_ENABLED", "true")
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: FAKE_EXTRACTION)
    _stub_classify(monkeypatch, _classification(content_type=ContentType.IRRELEVANT))

    msg = _make_raw_message(db)
    pipeline_module.process_message(db, msg.id)

    detail = _audit(db, "auto_approve", msg.id).detail
    assert detail["approved"] is False
    assert "not_a_claim" in detail["reasons"]


def test_fallback_source_is_named_when_nothing_fired(db, monkeypatch):
    """FALLBACK and INJURY_OVERRIDE are different stories about one claim, and
    an eval run has to be able to tell them apart."""
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: FAKE_EXTRACTION)

    msg = _make_raw_message(db, "Aracimin cami catladi.")
    pipeline_module.process_message(db, msg.id)

    assert _audit(db, "classification", msg.id).detail["urgency_source"] == FALLBACK


# --- DEMO_OFFLINE end to end (S4-6) ------------------------------------------
#
# These drive the real check_sanity, classify and extract - only the OpenAI
# layer underneath them is replaced, by the recorded answers in demo/fixtures/.
# What is under test is the wiring: that a replayed message reaches its own
# recorded answer, and that a hand-typed one falls back to the wildcard.


def _make_replayed_message(db_session, external_ref: str | None, text: str) -> RawMessage:
    """A message as replay/replay.py posts it: gt_id carried in external_ref."""
    msg = RawMessage(
        channel="email",
        raw_text=text,
        external_ref=external_ref,
        received_at=datetime.now(UTC),
        status="received",
    )
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)
    return msg


@pytest.fixture
def offline(monkeypatch):
    """DEMO_OFFLINE on, and the autouse classification stub taken back off.

    worker/conftest.py replaces pipeline_module.classify for every test so the
    suite never reaches OpenAI. Here the real one has to run - reaching the
    fixtures is the whole point - and the recorded verdict is what keeps it off
    the network.
    """
    monkeypatch.setenv("DEMO_OFFLINE", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(pipeline_module, "classify", real_classify)


def test_offline_replayed_message_gets_its_own_recorded_answers(db, offline):
    """GT-000007's fixtures, end to end: sanity, classification and extraction."""
    msg = _make_replayed_message(db, "GT-000007", "Dolu yagdi, aracin her yeri gocuk oldu.")

    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()

    # Sanity: the recorded verdict is clean, so extraction was not skipped.
    assert claim.data.get("masking_sanity_flags") in (None, [])

    # Classification: content type and urgency come from the ground truth.
    assert claim.content_type == ContentType.CLAIM
    assert claim.urgency == Urgency.NORMAL

    # Extraction: this record's own values, not the wildcard's nulls.
    extraction = claim.data["extraction"]
    assert extraction["plate"] == "52 OKL 1983"
    assert extraction["policy_no"] == "POL-2025-50857"
    assert extraction["damage_type"] == "hail"
    assert extraction["incident_location"]["city"] == "Ankara"


def test_offline_hand_typed_message_falls_back_to_the_wildcard(db, offline):
    """No external_ref: nothing recorded, so nothing is invented either."""
    msg = _make_replayed_message(db, None, "Aracima bir sey oldu, ne yapmaliyim.")

    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    extraction = claim.data["extraction"]

    # The wildcard fills nothing in - a plausible plate here would be the one
    # thing an offline demo must never do.
    assert extraction["plate"] is None
    assert extraction["policy_no"] is None
    assert extraction["estimated_amount"] is None
    assert "plate" in extraction["missing_fields"]

    # And the neutral verdict still routes it to a human.
    assert claim.content_type == ContentType.CLAIM
    assert claim.status == "in_human_review"


def test_offline_audit_trail_records_the_fixture_model_name(db, offline):
    """A recorded answer must not read back as a live gpt-4o call.

    step_extract writes the model name into AuditTrail.provider, not into
    detail - that column is what a later "which model produced this" question
    reads, and offline it has to say so.
    """
    msg = _make_replayed_message(db, "GT-000007", "Dolu yagdi, aracin her yeri gocuk oldu.")

    pipeline_module.process_message(db, msg.id)

    extraction_audit = _audit(db, "extraction", msg.id)
    assert extraction_audit.provider == OFFLINE_CHEAP_MODEL
    assert "gpt" not in extraction_audit.provider


def test_offline_injury_override_still_fires_over_a_recorded_verdict(db, offline):
    """GT-000007 is recorded as normal; an injury in the text still wins.

    The deterministic rule is the backbone of CLAUDE.md §7's critical recall,
    and an offline demo that quietly lost it would be worse than no demo.
    """
    msg = _make_replayed_message(db, "GT-000007", "Kaza oldu, yarali var, ambulans geldi.")

    pipeline_module.process_message(db, msg.id)

    claim = db.execute(select(Claim).where(Claim.raw_message_id == msg.id)).scalar_one()
    assert claim.urgency == Urgency.CRITICAL
