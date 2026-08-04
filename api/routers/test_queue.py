# api/routers/test_queue.py
"""Tests for the queue router: GET /queue, approve, reject.

Fixtures (client, db_session, auth_headers, ...) come from api/conftest.py —
this file no longer sets up its own engine/TestClient/dependency override.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from api.models.db import AuditTrail, Claim, User
from api.security import create_access_token, hash_password


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


def test_list_queue_only_returns_in_human_review(client, db_session, auth_headers):
    in_review = _make_claim(db_session, status="in_human_review")
    _make_claim(db_session, status="approved")
    _make_claim(db_session, status="archived")

    response = client.get("/queue", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    ids = [item["id"] for item in body["items"]]
    assert ids == [in_review.id]
    assert body["total"] == 1


def test_list_queue_orders_critical_first(client, db_session, auth_headers):
    now = datetime.now(UTC)
    normal = _make_claim(db_session, urgency="normal", created_at=now - timedelta(minutes=5))
    critical = _make_claim(db_session, urgency="critical", created_at=now - timedelta(minutes=1))
    high = _make_claim(db_session, urgency="high", created_at=now - timedelta(minutes=3))

    response = client.get("/queue", headers=auth_headers)

    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [critical.id, high.id, normal.id]


def test_list_queue_fifo_within_same_urgency(client, db_session, auth_headers):
    now = datetime.now(UTC)
    older = _make_claim(db_session, urgency="normal", created_at=now - timedelta(minutes=10))
    newer = _make_claim(db_session, urgency="normal", created_at=now - timedelta(minutes=1))

    response = client.get("/queue", headers=auth_headers)

    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [older.id, newer.id]


def test_list_queue_without_auth_returns_401(client, db_session):
    _make_claim(db_session, status="in_human_review")

    response = client.get("/queue")

    assert response.status_code == 401


# --- POST /queue/{id}/approve -------------------------------------------------


def test_approve_in_human_review_claim_succeeds(client, db_session, auth_headers):
    claim = _make_claim(db_session, status="in_human_review")

    response = client.post(f"/queue/{claim.id}/approve", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "approved"


def test_approve_writes_audit_row(client, db_session, auth_headers):
    claim = _make_claim(db_session, status="in_human_review")

    client.post(f"/queue/{claim.id}/approve", headers=auth_headers)

    audit = db_session.execute(
        select(AuditTrail).where(AuditTrail.claim_id == claim.id, AuditTrail.step == "approve")
    ).scalar_one()
    assert audit.detail == {"from": "in_human_review", "to": "approved"}


def test_approve_nonexistent_claim_returns_404(client, auth_headers):
    response = client.post("/queue/999999/approve", headers=auth_headers)
    assert response.status_code == 404


def test_approve_already_approved_claim_returns_409(client, db_session, auth_headers):
    claim = _make_claim(db_session, status="approved")

    response = client.post(f"/queue/{claim.id}/approve", headers=auth_headers)

    assert response.status_code == 409
    assert "approved" in response.json()["detail"]


def test_approve_without_auth_returns_401(client, db_session):
    claim = _make_claim(db_session, status="in_human_review")

    response = client.post(f"/queue/{claim.id}/approve")

    assert response.status_code == 401


def test_approve_with_non_operator_role_returns_403(client, db_session):
    claim = _make_claim(db_session, status="in_human_review")
    viewer = User(email="viewer@test.com", password_hash=hash_password("x"), role="viewer")
    db_session.add(viewer)
    db_session.commit()
    db_session.refresh(viewer)
    headers = {"Authorization": f"Bearer {create_access_token(viewer)}"}

    response = client.post(f"/queue/{claim.id}/approve", headers=headers)

    assert response.status_code == 403


# --- POST /queue/{id}/approve with edits --------------------------------------


def _make_claim_with_extraction(db_session, extraction: dict, **kwargs):
    claim = _make_claim(db_session, **kwargs)
    claim.data = {"masked_text": "...", "extraction": extraction}
    db_session.commit()
    db_session.refresh(claim)
    return claim


def test_approve_without_edits_still_works_backward_compatible(client, db_session, auth_headers):
    claim = _make_claim_with_extraction(db_session, {"plate": "34 ABC 123"})

    response = client.post(f"/queue/{claim.id}/approve", json={}, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["data"]["extraction"]["plate"] == "34 ABC 123"

    audit = db_session.execute(
        select(AuditTrail).where(AuditTrail.claim_id == claim.id, AuditTrail.step == "approve")
    ).scalar_one()
    assert audit.detail == {"from": "in_human_review", "to": "approved"}
    assert "edits" not in audit.detail


def test_approve_with_edits_updates_extraction_and_writes_diff(client, db_session, auth_headers):
    claim = _make_claim_with_extraction(
        db_session, {"plate": "34ABC123", "damage_type": "collision"}
    )

    response = client.post(
        f"/queue/{claim.id}/approve",
        json={"edits": {"plate": "34 ABC 123"}},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["extraction"]["plate"] == "34 ABC 123"
    assert body["data"]["extraction"]["damage_type"] == "collision"

    audit = db_session.execute(
        select(AuditTrail).where(AuditTrail.claim_id == claim.id, AuditTrail.step == "approve")
    ).scalar_one()
    assert audit.detail["edits"] == [
        {"field": "plate", "before": "34ABC123", "after": "34 ABC 123"}
    ]


def test_approve_with_nested_edit_updates_incident_location(client, db_session, auth_headers):
    claim = _make_claim_with_extraction(
        db_session, {"incident_location": {"city": "Ankara", "district": None}}
    )

    response = client.post(
        f"/queue/{claim.id}/approve",
        json={"edits": {"incident_location.city": "İstanbul"}},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["extraction"]["incident_location"] == {
        "city": "İstanbul",
        "district": None,
    }

    audit = db_session.execute(
        select(AuditTrail).where(AuditTrail.claim_id == claim.id, AuditTrail.step == "approve")
    ).scalar_one()
    assert audit.detail["edits"] == [
        {"field": "incident_location.city", "before": "Ankara", "after": "İstanbul"}
    ]


def test_approve_with_non_editable_field_returns_400(client, db_session, auth_headers):
    claim = _make_claim_with_extraction(db_session, {"plate": "34 ABC 123"})

    response = client.post(
        f"/queue/{claim.id}/approve",
        json={"edits": {"masked_text": "değiştirilmiş metin"}},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "masked_text" in response.json()["detail"]


def test_approve_with_same_value_produces_no_diff(client, db_session, auth_headers):
    claim = _make_claim_with_extraction(db_session, {"plate": "34 ABC 123"})

    response = client.post(
        f"/queue/{claim.id}/approve",
        json={"edits": {"plate": "34 ABC 123"}},
        headers=auth_headers,
    )

    assert response.status_code == 200
    audit = db_session.execute(
        select(AuditTrail).where(AuditTrail.claim_id == claim.id, AuditTrail.step == "approve")
    ).scalar_one()
    assert "edits" not in audit.detail


def test_approve_with_edits_and_no_extraction_returns_409(client, db_session, auth_headers):
    claim = _make_claim(db_session, status="in_human_review")  # data={}, no extraction

    response = client.post(
        f"/queue/{claim.id}/approve",
        json={"edits": {"plate": "34 ABC 123"}},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert "extraction" in response.json()["detail"].lower()


def test_approve_edit_is_actually_persisted_to_db(client, db_session, auth_headers):
    claim = _make_claim_with_extraction(db_session, {"plate": "34ABC123"})

    client.post(
        f"/queue/{claim.id}/approve",
        json={"edits": {"plate": "34 ABC 123"}},
        headers=auth_headers,
    )

    # db_session is a separate session from the one the request used; without
    # expiring it, SQLAlchemy's identity map would hand back the stale object
    # it already loaded in _make_claim_with_extraction instead of re-querying.
    db_session.expire_all()
    reloaded = db_session.execute(select(Claim).where(Claim.id == claim.id)).scalar_one()
    assert reloaded.data["extraction"]["plate"] == "34 ABC 123"


# --- POST /queue/{id}/reject -------------------------------------------------


def test_reject_in_human_review_claim_succeeds(client, db_session, auth_headers):
    claim = _make_claim(db_session, status="in_human_review")

    response = client.post(f"/queue/{claim.id}/reject", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "archived"


def test_reject_writes_audit_row(client, db_session, auth_headers):
    claim = _make_claim(db_session, status="in_human_review")

    client.post(f"/queue/{claim.id}/reject", headers=auth_headers)

    audit = db_session.execute(
        select(AuditTrail).where(AuditTrail.claim_id == claim.id, AuditTrail.step == "reject")
    ).scalar_one()
    assert audit.detail == {"from": "in_human_review", "to": "archived"}


def test_reject_already_archived_claim_returns_409(client, db_session, auth_headers):
    claim = _make_claim(db_session, status="archived")

    response = client.post(f"/queue/{claim.id}/reject", headers=auth_headers)

    assert response.status_code == 409
    assert "archived" in response.json()["detail"]


def test_reject_without_auth_returns_401(client, db_session):
    claim = _make_claim(db_session, status="in_human_review")

    response = client.post(f"/queue/{claim.id}/reject")

    assert response.status_code == 401
