# api/routers/queue.py
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from api.audit import write_audit
from api.database import get_db
from api.models.db import Claim
from api.models.schemas import ClaimListOut, ClaimOut

router = APIRouter(prefix="/queue", tags=["queue"])

# critical first, then high, then normal; anything unexpected sorts last
_URGENCY_ORDER = case(
    (Claim.urgency == "critical", 0),
    (Claim.urgency == "high", 1),
    (Claim.urgency == "normal", 2),
    else_=3,
)


@router.get("", response_model=ClaimListOut)
def list_queue(
    db: Session = Depends(get_db),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
):
    """Claims waiting for human review: most urgent first, FIFO within urgency."""
    base_filter = Claim.status == "in_human_review"
    stmt = select(Claim).where(base_filter).order_by(_URGENCY_ORDER, Claim.created_at.asc())
    count_stmt = select(func.count()).select_from(Claim).where(base_filter)

    total = db.execute(count_stmt).scalar_one()
    items = db.execute(stmt.limit(limit).offset(offset)).scalars().all()
    return ClaimListOut(total=total, items=items)


def _transition(db: Session, claim_id: int, *, to_status: str, step: str) -> Claim:
    """Move a claim out of in_human_review, or reject the request.

    Only in_human_review -> {approved, archived} is allowed (CLAUDE.md S2). Any
    other current status is a conflict, not an error to hide: the claim was
    already decided, so the caller needs to know rather than silently retry.
    """
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    if claim.status != "in_human_review":
        raise HTTPException(
            status_code=409,
            detail=f"Claim is not in_human_review (current status: {claim.status})",
        )

    from_status = claim.status
    claim.status = to_status
    claim.updated_at = datetime.now(UTC)
    write_audit(db, step, claim_id=claim.id, detail={"from": from_status, "to": to_status})

    db.commit()
    db.refresh(claim)
    return claim


@router.post("/{claim_id}/approve", response_model=ClaimOut)
def approve_claim(claim_id: int, db: Session = Depends(get_db)):
    return _transition(db, claim_id, to_status="approved", step="approve")


@router.post("/{claim_id}/reject", response_model=ClaimOut)
def reject_claim(claim_id: int, db: Session = Depends(get_db)):
    return _transition(db, claim_id, to_status="archived", step="reject")
