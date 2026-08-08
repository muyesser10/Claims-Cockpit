# api/routers/test_queue.py
"""Tests for the queue router: GET /queue, approve, reject.

Fixtures (client, db_session, auth_headers, ...) come from api/conftest.py —
this file no longer sets up its own engine/TestClient/dependency override.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import get_args

from sqlalchemy import select

from api.models.db import AuditTrail, Claim, User
from api.routers.queue import EDITABLE_FIELDS, DamageTypeName
from api.security import create_access_token, hash_password

CLAIM_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "claim.json"


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


# --- POST /queue/{id}/approve: edit value types -------------------------------
#
# The field-name whitelist was the only check here for a while: any value at all
# went into claim.data as long as the key was allowed. These pin the types down.


def _reload(db_session, claim_id: int) -> Claim:
    """Re-read a claim through a session that did not serve the request."""
    db_session.expire_all()
    return db_session.execute(select(Claim).where(Claim.id == claim_id)).scalar_one()


def test_editable_fields_covers_every_extraction_field():
    """EDITABLE_FIELDS is derived from ClaimEdits — a typo'd alias would shrink it."""
    assert EDITABLE_FIELDS == {
        "policy_no",
        "plate",
        "incident_date",
        "damage_type",
        "injury",
        "counterparty_exists",
        "estimated_amount",
        "damage_description",
        "incident_location.city",
        "incident_location.district",
    }


def test_damage_type_choices_match_claim_json():
    """The api copy of the eight values stays in step with the team schema.

    Mirrors worker/extraction/test_schema.py: api/ cannot import worker's enum
    (api/Dockerfile does not copy worker/), so a [SCHEMA] PR has to go red here.
    """
    raw = json.loads(CLAIM_SCHEMA_PATH.read_text(encoding="utf-8"))["damage_type"]
    expected = {value.strip() for value in raw.split("|")} - {"null"}
    assert set(get_args(DamageTypeName)) == expected


def test_approve_with_turkish_formatted_amount_returns_400(client, db_session, auth_headers):
    """'1.250,50 TL' is text, not a number — the same rule extraction is held to."""
    claim = _make_claim_with_extraction(db_session, {"estimated_amount": 1000.0})

    response = client.post(
        f"/queue/{claim.id}/approve",
        json={"edits": {"estimated_amount": "1.250,50 TL"}},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "estimated_amount" in response.json()["detail"]
    assert _reload(db_session, claim.id).data["extraction"]["estimated_amount"] == 1000.0


def test_approve_with_numeric_amount_is_stored_as_a_number(client, db_session, auth_headers):
    claim = _make_claim_with_extraction(db_session, {"estimated_amount": None})

    response = client.post(
        f"/queue/{claim.id}/approve",
        json={"edits": {"estimated_amount": 1250.5}},
        headers=auth_headers,
    )

    assert response.status_code == 200
    stored = _reload(db_session, claim.id).data["extraction"]["estimated_amount"]
    assert stored == 1250.5
    assert isinstance(stored, float)


def test_approve_with_relative_date_returns_400(client, db_session, auth_headers):
    """'yarın' is what the extraction prompt forbids; an operator may not send it either."""
    claim = _make_claim_with_extraction(db_session, {"incident_date": "2026-07-08"})

    response = client.post(
        f"/queue/{claim.id}/approve",
        json={"edits": {"incident_date": "yarın"}},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "incident_date" in response.json()["detail"]
    assert _reload(db_session, claim.id).data["extraction"]["incident_date"] == "2026-07-08"


def test_approve_with_iso_date_stores_a_string_not_a_date(client, db_session, auth_headers):
    """Regression guard for model_dump(mode="json").

    incident_date validates into a datetime.date. claim.data is a JSON column
    holding ISO strings (that is what the pipeline writes), so a python-mode
    dump would put a date object into the column and into the audit diff.
    """
    claim = _make_claim_with_extraction(db_session, {"incident_date": None})

    response = client.post(
        f"/queue/{claim.id}/approve",
        json={"edits": {"incident_date": "2026-07-14"}},
        headers=auth_headers,
    )

    assert response.status_code == 200
    stored = _reload(db_session, claim.id).data["extraction"]["incident_date"]
    assert stored == "2026-07-14"
    assert isinstance(stored, str)

    audit = db_session.execute(
        select(AuditTrail).where(AuditTrail.claim_id == claim.id, AuditTrail.step == "approve")
    ).scalar_one()
    assert audit.detail["edits"] == [
        {"field": "incident_date", "before": None, "after": "2026-07-14"}
    ]


def test_approve_with_non_boolean_injury_returns_400(client, db_session, auth_headers):
    """injury is bool | None — 'belki' is neither, and null≠false is a kept distinction."""
    claim = _make_claim_with_extraction(db_session, {"injury": None})

    response = client.post(
        f"/queue/{claim.id}/approve",
        json={"edits": {"injury": "belki"}},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "injury" in response.json()["detail"]


def test_approve_with_damage_type_outside_the_enum_returns_400(client, db_session, auth_headers):
    claim = _make_claim_with_extraction(db_session, {"damage_type": "collision"})

    response = client.post(
        f"/queue/{claim.id}/approve",
        json={"edits": {"damage_type": "sel"}},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "damage_type" in response.json()["detail"]


def test_approve_with_invalid_nested_edit_returns_400(client, db_session, auth_headers):
    """The dotted alias survives into the error message, not the python name 'city'."""
    claim = _make_claim_with_extraction(
        db_session, {"incident_location": {"city": "Ankara", "district": None}}
    )

    response = client.post(
        f"/queue/{claim.id}/approve",
        json={"edits": {"incident_location.city": 42}},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "incident_location.city" in response.json()["detail"]


def test_rejected_edit_leaves_claim_in_human_review_and_writes_nothing(
    client, db_session, auth_headers
):
    """No partial write: one bad value in the batch rolls the whole approve back.

    The valid plate edit sits alongside an invalid amount — validation runs over
    the whole payload before anything is assigned, so neither lands and the claim
    stays in the queue for the operator to fix.
    """
    claim = _make_claim_with_extraction(
        db_session, {"plate": "34 ABC 123", "estimated_amount": 100.0}
    )

    response = client.post(
        f"/queue/{claim.id}/approve",
        json={"edits": {"plate": "06 XYZ 789", "estimated_amount": "1.250,50 TL"}},
        headers=auth_headers,
    )

    assert response.status_code == 400

    reloaded = _reload(db_session, claim.id)
    assert reloaded.status == "in_human_review"
    assert reloaded.data["extraction"] == {"plate": "34 ABC 123", "estimated_amount": 100.0}

    audit = (
        db_session.execute(
            select(AuditTrail).where(AuditTrail.claim_id == claim.id, AuditTrail.step == "approve")
        )
        .scalars()
        .all()
    )
    assert audit == []


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
