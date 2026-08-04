# api/metrics.py
"""Custom queue/operations gauges for Prometheus (S3-9).

HTTP-level metrics (request rate, latency, error rate) come from
prometheus-fastapi-instrumentator, wired up in api/main.py — this module
only covers what that library can't see: claim counts and how long claims
sit in the human-review queue.

Gauges, not Counters, on purpose even for claims_approved_total /
claims_rejected_total: refresh_queue_metrics() re-derives every value from
the DB on each tick rather than incrementing per event, so a Gauge (which
just overwrites with .set()) is the honest type here — a real Counter
would need to track its own event stream to stay correct across restarts.
"""

import logging

from prometheus_client import Gauge
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models.db import AuditTrail, Claim

logger = logging.getLogger("api.metrics")

# Last N approve/reject decisions considered for the wait-time average — a
# rolling window instead of the whole table, so the number tracks recent
# operator behavior instead of being dragged down by Sprint 1 test data.
_WAIT_SAMPLE_SIZE = 100

claims_in_human_review_total = Gauge(
    "claims_in_human_review_total",
    "Claims currently waiting for human review",
)

claims_approved_total = Gauge(
    "claims_approved_total",
    "Claims ever approved (re-derived from audit_trail on each refresh)",
)

claims_rejected_total = Gauge(
    "claims_rejected_total",
    "Claims ever rejected (re-derived from audit_trail on each refresh)",
)

claims_avg_wait_seconds = Gauge(
    "claims_avg_wait_seconds",
    f"Average seconds between routing and approve/reject, last {_WAIT_SAMPLE_SIZE} decisions",
)


def _average_wait_seconds(db: Session) -> float:
    """Mean seconds between a claim's `routing` audit row and its
    approve/reject row, over the most recent decisions.

    Two simple selects instead of one SQL join: the "last N decisions"
    window is picked first (ORDER BY + LIMIT on step IN (...)), then the
    matching `routing` rows are looked up by claim_id in bulk. Doing the
    pairing in Python avoids a query that has to express "earliest matching
    row per claim" in SQL.
    """
    decisions = db.execute(
        select(AuditTrail.claim_id, AuditTrail.created_at)
        .where(AuditTrail.step.in_(("approve", "reject")))
        .order_by(AuditTrail.created_at.desc())
        .limit(_WAIT_SAMPLE_SIZE)
    ).all()

    claim_ids = [row.claim_id for row in decisions if row.claim_id is not None]
    if not claim_ids:
        return 0.0

    routing_rows = db.execute(
        select(AuditTrail.claim_id, AuditTrail.created_at).where(
            AuditTrail.step == "routing", AuditTrail.claim_id.in_(claim_ids)
        )
    ).all()
    routed_at = {row.claim_id: row.created_at for row in routing_rows}

    waits = [
        (decided_at - routed_at[claim_id]).total_seconds()
        for claim_id, decided_at in decisions
        if claim_id in routed_at
    ]
    return sum(waits) / len(waits) if waits else 0.0


def refresh_queue_metrics(db: Session) -> None:
    """Re-derive every queue gauge from the current DB state.

    Called on a timer (api/main.py's background thread), not per-request —
    these are cheap aggregate queries, but still not something every
    request should pay for.
    """
    in_review = db.execute(
        select(func.count()).select_from(Claim).where(Claim.status == "in_human_review")
    ).scalar_one()
    approved = db.execute(
        select(func.count()).select_from(AuditTrail).where(AuditTrail.step == "approve")
    ).scalar_one()
    rejected = db.execute(
        select(func.count()).select_from(AuditTrail).where(AuditTrail.step == "reject")
    ).scalar_one()

    claims_in_human_review_total.set(in_review)
    claims_approved_total.set(approved)
    claims_rejected_total.set(rejected)
    claims_avg_wait_seconds.set(_average_wait_seconds(db))
