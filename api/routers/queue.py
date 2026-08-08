# api/routers/queue.py
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError
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

# The eight damage types, spelled out instead of imported from
# worker/extraction/schema.py's DamageType: api/Dockerfile copies only api/,
# migrations/ and scripts/, so a `from worker...` import here passes under
# pytest and then kills the api container at startup. test_queue.py asserts
# these values against schemas/claim.json, so the copy cannot drift silently.
DamageTypeName = Literal[
    "collision",
    "single_vehicle",
    "glass",
    "hail",
    "fire",
    "theft",
    "animal",
    "other",
]


class ClaimEdits(BaseModel):
    """The corrections an operator may send with an approve, and their types.

    One field per editable extraction field, carrying the same type
    worker/extraction/schema.py's ClaimExtraction gives it. This is what stops
    an "1.250,50 TL" amount or a "yarın" incident date from being written into
    claim.data verbatim — claims_flat's safe casts turn those into NULL further
    downstream, but the wrong value is already stored by then.

    Deliberately left out (system-derived, not operator-editable): masked_text,
    validation_flags, source_references, unverified_fields.

    Every field defaults to None so a request may send any subset. The default
    does NOT mean "the operator cleared this field" — model_dump(exclude_unset=True)
    is what separates "not sent" from "sent as null", and the diff below relies
    on that distinction.
    """

    # extra="forbid" is a second layer under the EDITABLE_FIELDS check below,
    # which stays because it owns the Turkish 400 message for a bad field name.
    model_config = ConfigDict(populate_by_name=False, extra="forbid")

    policy_no: str | None = None
    plate: str | None = None
    incident_date: date | None = None
    damage_type: DamageTypeName | None = None
    injury: bool | None = None
    counterparty_exists: bool | None = None
    estimated_amount: float | None = None
    damage_description: str | None = None
    # schemas/claim.json nests these under incident_location; the wire format is
    # the dotted path, which is not a Python identifier — hence the alias.
    city: str | None = Field(default=None, alias="incident_location.city")
    district: str | None = Field(default=None, alias="incident_location.district")


# Fields an operator may correct on approve, derived from ClaimEdits rather
# than listed again: one place to add a field, and the whitelist can never
# drift away from the types that validate it.
EDITABLE_FIELDS = {field.alias or name for name, field in ClaimEdits.model_fields.items()}


def _apply_edits(claim: Claim, edits: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate `edits` against ClaimEdits and apply them to claim.data["extraction"].

    Field names are checked first so an unknown one keeps its own message, then
    the values are type-checked against ClaimEdits. Both failures are 400s: this
    is the same "the operator sent something we will not store" answer, and the
    frontend already treats the whole approve call as pass/fail.

    Reassigns claim.data wholesale rather than mutating nested dicts in place —
    claim.data is a plain JSON column (no MutableDict tracking), so an in-place
    claim.data["extraction"][...] = ... write is silently lost on commit.

    Returns the diff entries for fields whose value actually changed (fields
    sent with their current value are skipped, not recorded).
    """
    for field in edits:
        if field not in EDITABLE_FIELDS:
            raise HTTPException(status_code=400, detail=f"'{field}' alanı düzenlenemez")

    try:
        validated = ClaimEdits.model_validate(edits)
    except ValidationError as exc:
        error = exc.errors()[0]
        name = ".".join(str(part) for part in error["loc"]) or "edits"
        raise HTTPException(
            status_code=400,
            detail=f"'{name}' için geçersiz değer: {error['msg']}",
        ) from exc

    # mode="json" is load-bearing: incident_date validates into a date object,
    # and claim.data is a plain JSON column holding ISO strings (the pipeline
    # writes it the same way, extractor.py's model_dump(mode="json")). A python-
    # mode dump would push a date into the column and into the audit diff, where
    # neither the JSON serializer nor the /queue response can handle it.
    # exclude_unset keeps the "only what was sent" contract; by_alias gives the
    # dotted keys back so the nested branch below still works off the wire names.
    values = validated.model_dump(exclude_unset=True, by_alias=True, mode="json")

    extraction = (claim.data or {}).get("extraction")
    if extraction is None:
        raise HTTPException(status_code=409, detail="Claim has no extraction to edit")

    new_extraction = {**extraction}
    diffs: list[dict[str, Any]] = []

    for field, after in values.items():
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
