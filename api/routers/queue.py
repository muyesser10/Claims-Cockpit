# api/routers/queue.py
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from api.audit import write_audit
from api.database import get_db
from api.dependencies import get_current_user, require_role
from api.models.db import Claim, User
from api.models.schemas import ApproveRequest, ClaimListOut, ClaimOut

router = APIRouter(prefix="/queue", tags=["queue"])

# critical first, then high, then normal; anything unexpected sorts last
_URGENCY_ORDER = case(
    (Claim.urgency == "critical", 0),
    (Claim.urgency == "high", 1),
    (Claim.urgency == "normal", 2),
    else_=3,
)

# Fields an operator may correct on approve. Top-level extraction fields plus
# dotted nested ones (schemas/claim.json's incident_location). Deliberately
# excludes masked_text, validation_flags, source_references — those are
# system-derived, not operator-editable.
EDITABLE_FIELDS = {
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


def _apply_edits(claim: Claim, edits: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate `edits` against EDITABLE_FIELDS and apply them to claim.data["extraction"].

    Reassigns claim.data wholesale rather than mutating nested dicts in place —
    claim.data is a plain JSON column (no MutableDict tracking), so an in-place
    claim.data["extraction"][...] = ... write is silently lost on commit.

    Returns the diff entries for fields whose value actually changed (fields
    sent with their current value are skipped, not recorded).
    """
    for field in edits:
        if field not in EDITABLE_FIELDS:
            raise HTTPException(status_code=400, detail=f"'{field}' alanı düzenlenemez")

    extraction = (claim.data or {}).get("extraction")
    if extraction is None:
        raise HTTPException(status_code=409, detail="Claim has no extraction to edit")

    new_extraction = {**extraction}
    diffs: list[dict[str, Any]] = []

    for field, after in edits.items():
        if "." in field:
            parent, child = field.split(".", 1)
            parent_dict = dict(new_extraction.get(parent) or {})
            before = parent_dict.get(child)
            if before == after:
                continue
            parent_dict[child] = after
            new_extraction[parent] = parent_dict
        else:
            before = new_extraction.get(field)
            if before == after:
                continue
            new_extraction[field] = after
        diffs.append({"field": field, "before": before, "after": after})

    if diffs:
        claim.data = {**claim.data, "extraction": new_extraction}

    return diffs


@router.get("", response_model=ClaimListOut)
def list_queue(
    db: Session = Depends(get_db),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    _user: User = Depends(get_current_user),
):
    """Claims waiting for human review: most urgent first, FIFO within urgency."""
    base_filter = Claim.status == "in_human_review"
    stmt = select(Claim).where(base_filter).order_by(_URGENCY_ORDER, Claim.created_at.asc())
    count_stmt = select(func.count()).select_from(Claim).where(base_filter)

    total = db.execute(count_stmt).scalar_one()
    items = db.execute(stmt.limit(limit).offset(offset)).scalars().all()
    return ClaimListOut(total=total, items=items)


def _transition(
    db: Session,
    claim_id: int,
    *,
    to_status: str,
    step: str,
    on_claim: Callable[[Claim], list[dict[str, Any]]] | None = None,
) -> Claim:
    """Move a claim out of in_human_review, or reject the request.

    Only in_human_review -> {approved, archived} is allowed (CLAUDE.md S2). Any
    other current status is a conflict, not an error to hide: the claim was
    already decided, so the caller needs to know rather than silently retry.

    `on_claim`, if given, runs after the status check passes and before the
    commit; it may mutate claim.data in place (e.g. operator edits) and
    returns the diff entries to fold into the audit detail. Callers that pass
    nothing (reject) get the exact same behavior as before this existed.
    """
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    if claim.status != "in_human_review":
        raise HTTPException(
            status_code=409,
            detail=f"Claim is not in_human_review (current status: {claim.status})",
        )

    edits = on_claim(claim) if on_claim else []

    from_status = claim.status
    claim.status = to_status
    claim.updated_at = datetime.now(UTC)
    detail: dict[str, Any] = {"from": from_status, "to": to_status}
    if edits:
        detail["edits"] = edits
    write_audit(db, step, claim_id=claim.id, detail=detail)

    db.commit()
    db.refresh(claim)
    return claim


@router.post("/{claim_id}/approve", response_model=ClaimOut)
def approve_claim(
    claim_id: int,
    body: ApproveRequest | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_role("operator", "admin")),
):
    edits = body.edits if body else None
    on_claim = (lambda claim: _apply_edits(claim, edits)) if edits else None
    return _transition(db, claim_id, to_status="approved", step="approve", on_claim=on_claim)


@router.post("/{claim_id}/reject", response_model=ClaimOut)
def reject_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_role("operator", "admin")),
):
    return _transition(db, claim_id, to_status="archived", step="reject")
