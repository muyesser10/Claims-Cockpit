# api/routers/test_claims.py
"""Auth-gating tests for GET /claims and GET /claims/{id} (S3-8).

No endpoint-behavior tests existed for this router before S3-8; this file
only covers what S3-8 added — everything else is unchanged.
"""

from datetime import UTC, datetime

from api.models.db import Claim


def _make_claim(db_session) -> Claim:
    claim = Claim(
        raw_message_id=1,
        channel="email",
        content_type="claim",
        urgency="normal",
        data={},
        status="in_human_review",
        created_at=datetime.now(UTC),
    )
    db_session.add(claim)
    db_session.commit()
    db_session.refresh(claim)
    return claim


def test_list_claims_without_auth_returns_401(client):
    response = client.get("/claims")
    assert response.status_code == 401


def test_list_claims_with_auth_succeeds(client, auth_headers):
    response = client.get("/claims", headers=auth_headers)
    assert response.status_code == 200


def test_get_claim_without_auth_returns_401(client, db_session):
    claim = _make_claim(db_session)
    response = client.get(f"/claims/{claim.id}")
    assert response.status_code == 401


def test_get_claim_with_auth_succeeds(client, db_session, auth_headers):
    claim = _make_claim(db_session)
    response = client.get(f"/claims/{claim.id}", headers=auth_headers)
    assert response.status_code == 200
