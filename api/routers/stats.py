# api/routers/stats.py
"""Aggregate statistics for the Pano dashboard (S2-8)."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.database import get_db
from api.models.db import Claim
from api.models.schemas import StatsOut

router = APIRouter(prefix="/istatistik", tags=["istatistik"])


@router.get("/ozet", response_model=StatsOut)
def get_ozet(db: Session = Depends(get_db)):
    """Counts for sayaç kartları, aciliyet donut, and il barı."""
    urgency_rows = db.execute(select(Claim.urgency, func.count()).group_by(Claim.urgency)).all()
    status_rows = db.execute(select(Claim.status, func.count()).group_by(Claim.status)).all()

    city_expr = Claim.data["extraction"]["incident_location"]["city"].as_string()
    city_rows = db.execute(
        select(city_expr, func.count()).where(city_expr.is_not(None)).group_by(city_expr)
    ).all()

    return StatsOut(
        urgency_counts={(row[0] or "unknown"): row[1] for row in urgency_rows},
        status_counts={(row[0] or "unknown"): row[1] for row in status_rows},
        city_counts={row[0]: row[1] for row in city_rows},
    )
