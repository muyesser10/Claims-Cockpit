# api/test_metrics.py
"""Tests for GET /metrics (S3-9): the auto HTTP metrics from
prometheus-fastapi-instrumentator plus the custom queue gauges from
api/metrics.py.

Own TestClient/engine setup, matching api/routers/test_queue.py's pattern —
api/conftest.py doesn't provide a shared client fixture on this branch.

Unlike test_queue.py, the get_db override here is installed/removed inside
a fixture instead of at module import time. `app` is a single process-wide
object every test module imports; pytest imports (collects) every test
module before running any test, so a module-level
`app.dependency_overrides[get_db] = ...` assignment is a global side effect
whose *last writer wins* for the rest of the session regardless of test
run order — it silently pointed test_queue.py's tests at this file's empty
in-memory DB ("no such table: claims") until this was scoped to a fixture.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import get_db
from api.main import app
from api.metrics import refresh_queue_metrics
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


client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_db():
    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        Base.metadata.drop_all(bind=engine)
        if previous_override is not None:
            app.dependency_overrides[get_db] = previous_override
        else:
            app.dependency_overrides.pop(get_db, None)


def test_metrics_endpoint_returns_200():
    response = client.get("/metrics")
    assert response.status_code == 200


def test_metrics_endpoint_exposes_custom_queue_gauges():
    """The gauges must show up even before refresh_queue_metrics() has ever
    run — Gauge() registers with the default value (0) at import time."""
    body = client.get("/metrics").text
    assert "claims_in_human_review_total" in body
    assert "claims_approved_total" in body
    assert "claims_rejected_total" in body
    assert "claims_avg_wait_seconds" in body


def test_metrics_endpoint_exposes_instrumentator_http_metrics():
    """prometheus-fastapi-instrumentator's default metric set."""
    client.get("/health")  # generate at least one instrumented request
    body = client.get("/metrics").text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body


def test_refresh_queue_metrics_reflects_current_db_state():
    db = TestingSessionLocal()
    try:
        db.add(Claim(raw_message_id=1, channel="email", status="in_human_review", data={}))
        db.add(Claim(raw_message_id=2, channel="email", status="in_human_review", data={}))
        db.add(Claim(raw_message_id=3, channel="email", status="approved", data={}))
        db.flush()
        db.add(AuditTrail(claim_id=3, step="approve", detail={}))
        db.commit()

        refresh_queue_metrics(db)
    finally:
        db.close()

    body = client.get("/metrics").text
    assert "claims_in_human_review_total 2.0" in body
    assert "claims_approved_total 1.0" in body
    assert "claims_rejected_total 0.0" in body
