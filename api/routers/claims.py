# api/routers/claims.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.database import get_db
from api.models.db import Claim
from api.models.schemas import ClaimListOut, ClaimOut

router = APIRouter(prefix="/claims", tags=["claims"])


@router.get("", response_model=ClaimListOut)
def list_claims(
    db: Session = Depends(get_db),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    urgency: str | None = None,
):
    """List claims, newest first. Filterable by status and urgency."""
    stmt = select(Claim).order_by(Claim.created_at.desc())
    count_stmt = select(func.count()).select_from(Claim)

    if status:
        stmt = stmt.where(Claim.status == status)
        count_stmt = count_stmt.where(Claim.status == status)
    if urgency:
        stmt = stmt.where(Claim.urgency == urgency)
        count_stmt = count_stmt.where(Claim.urgency == urgency)

    total = db.execute(count_stmt).scalar_one()
    items = db.execute(stmt.limit(limit).offset(offset)).scalars().all()
    return ClaimListOut(total=total, items=items)


@router.get("/{claim_id}", response_model=ClaimOut)
def get_claim(claim_id: int, db: Session = Depends(get_db)):
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim
