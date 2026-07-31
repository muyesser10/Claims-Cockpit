# api/routers/test_queue.py
"""Tests for the queue router: GET /queue, approve, reject."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import get_db
from api.main import app
from api.models.db import AuditTrail, Base, Claim

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _make_claim(db_session, *, status="in_human_review", urgency="normal", created_at=None):
    claim = Claim(
        raw_message_id=1,
        channel="email",
        content_type="claim",
        urgency=urgency,
        data={},
        status=status,
        created_at=created_at or datetime.now(UTC),
    )
    db_session.add(claim)
    db_session.commit()
    db_session.refresh(claim)
    return claim


# --- GET /queue --------------------------------------------------------------


def test_list_queue_only_returns_in_human_review(db_session):
    in_review = _make_claim(db_session, status="in_human_review")
    _make_claim(db_session, status="approved")
    _make_claim(db_session, status="archived")

    response = client.get("/queue")

    assert response.status_code == 200
    body = response.json()
    ids = [item["id"] for item in body["items"]]
    assert ids == [in_review.id]
    assert body["total"] == 1


def test_list_queue_orders_critical_first(db_session):
    now = datetime.now(UTC)
    normal = _make_claim(db_session, urgency="normal", created_at=now - timedelta(minutes=5))
    critical = _make_claim(db_session, urgency="critical", created_at=now - timedelta(minutes=1))
    high = _make_claim(db_session, urgency="high", created_at=now - timedelta(minutes=3))

    response = client.get("/queue")

    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [critical.id, high.id, normal.id]


def test_list_queue_fifo_within_same_urgency(db_session):
    now = datetime.now(UTC)
    older = _make_claim(db_session, urgency="normal", created_at=now - timedelta(minutes=10))
    newer = _make_claim(db_session, urgency="normal", created_at=now - timedelta(minutes=1))

    response = client.get("/queue")

    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [older.id, newer.id]


# --- POST /queue/{id}/approve -------------------------------------------------


def test_approve_in_human_review_claim_succeeds(db_session):
    claim = _make_claim(db_session, status="in_human_review")

    response = client.post(f"/queue/{claim.id}/approve")

    assert response.status_code == 200
    assert response.json()["status"] == "approved"


def test_approve_writes_audit_row(db_session):
    claim = _make_claim(db_session, status="in_human_review")

    client.post(f"/queue/{claim.id}/approve")

    audit = db_session.execute(
        select(AuditTrail).where(AuditTrail.claim_id == claim.id, AuditTrail.step == "approve")
    ).scalar_one()
    assert audit.detail == {"from": "in_human_review", "to": "approved"}


def test_approve_nonexistent_claim_returns_404():
    response = client.post("/queue/999999/approve")
    assert response.status_code == 404


def test_approve_already_approved_claim_returns_409(db_session):
    claim = _make_claim(db_session, status="approved")

    response = client.post(f"/queue/{claim.id}/approve")

    assert response.status_code == 409
    assert "approved" in response.json()["detail"]


# --- POST /queue/{id}/reject -------------------------------------------------


def test_reject_in_human_review_claim_succeeds(db_session):
    claim = _make_claim(db_session, status="in_human_review")

    response = client.post(f"/queue/{claim.id}/reject")

    assert response.status_code == 200
    assert response.json()["status"] == "archived"


def test_reject_writes_audit_row(db_session):
    claim = _make_claim(db_session, status="in_human_review")

    client.post(f"/queue/{claim.id}/reject")

    audit = db_session.execute(
        select(AuditTrail).where(AuditTrail.claim_id == claim.id, AuditTrail.step == "reject")
    ).scalar_one()
    assert audit.detail == {"from": "in_human_review", "to": "archived"}


def test_reject_already_archived_claim_returns_409(db_session):
    claim = _make_claim(db_session, status="archived")

    response = client.post(f"/queue/{claim.id}/reject")

    assert response.status_code == 409
    assert "archived" in response.json()["detail"]
