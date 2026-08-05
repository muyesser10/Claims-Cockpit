# api/routers/stats.py
"""Aggregate statistics for the Pano dashboard (S2-8, S3-5)."""

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies import get_current_user
from api.models.db import Claim, User
from api.models.schemas import StatsOut, TrendPoint

router = APIRouter(prefix="/istatistik", tags=["istatistik"])


def _format_trend_date(value: date | str) -> str:
    """Postgres returns a date object, SQLite (tests) returns a string — normalize both."""
    if isinstance(value, str):
        return value
    return value.strftime("%Y-%m-%d")


@router.get("/ozet", response_model=StatsOut)
def get_ozet(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    """Counts for sayaç kartları, aciliyet donut, il barı, trend, and nabız."""
    urgency_rows = db.execute(select(Claim.urgency, func.count()).group_by(Claim.urgency)).all()
    status_rows = db.execute(select(Claim.status, func.count()).group_by(Claim.status)).all()

    city_expr = Claim.data["extraction"]["incident_location"]["city"].as_string()
    city_rows = db.execute(
        select(city_expr, func.count()).where(city_expr.is_not(None)).group_by(city_expr)
    ).all()

    # Trend: last 7 days, daily claim counts
    week_ago = datetime.now(UTC) - timedelta(days=7)
    day_expr = func.date(Claim.created_at)
    trend_rows = db.execute(
        select(day_expr, func.count())
        .where(Claim.created_at >= week_ago)
        .group_by(day_expr)
        .order_by(day_expr)
    ).all()

    # Nabız: timestamp of the most recent claim, for a "last seen X ago" indicator
    last_claim_at = db.execute(select(func.max(Claim.created_at))).scalar_one()

    return StatsOut(
        urgency_counts={(row[0] or "unknown"): row[1] for row in urgency_rows},
        status_counts={(row[0] or "unknown"): row[1] for row in status_rows},
        city_counts={row[0]: row[1] for row in city_rows},
        trend=[TrendPoint(date=_format_trend_date(row[0]), count=row[1]) for row in trend_rows],
        last_claim_at=last_claim_at,
    )
