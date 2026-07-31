import logging
from typing import Any

from sqlalchemy.orm import Session

from api.models.db import AuditTrail, Claim, MaskMapping, RawMessage
from worker.masking.pipeline import mask_all
from worker.shared.injury_terms import INJURY_TERMS, _normalize_tr

logger = logging.getLogger("worker.pipeline")

# Normalized once at import time — see worker/shared/injury_terms.py for why
# a plain .lower() would miss uppercase Turkish injury terms.
_NORMALIZED_INJURY_TERMS = tuple(_normalize_tr(term) for term in INJURY_TERMS)


def log_audit(
    db: Session,
    step: str,
    *,
    raw_message_id: int | None = None,
    claim_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditTrail(
            raw_message_id=raw_message_id,
            claim_id=claim_id,
            step=step,
            detail=detail or {},
        )
    )
    logger.info(f"AUDIT | raw_message_id={raw_message_id} | step={step} | detail={detail}")


def step_mask(db: Session, msg: RawMessage) -> str:
    try:
        masked_text, mappings = mask_all(msg.raw_text)
    except Exception as e:
        logger.warning(f"mask_all failed, continuing with raw text: {e}")
        log_audit(
            db,
            "masking_error",
            raw_message_id=msg.id,
            detail={"error": str(e), "warning": "unmasked raw text used as fallback"},
        )
        masked_text, mappings = msg.raw_text, []

    for m in mappings:
        db.add(
            MaskMapping(
                raw_message_id=msg.id,
                placeholder=m["placeholder"],
                real_value=m["real_value"],
                pii_type=m["pii_type"],
            )
        )

    msg.status = "masked"
    log_audit(db, "masking", raw_message_id=msg.id, detail={"pii_found": len(mappings)})
    return masked_text


def step_classify(db: Session, msg: RawMessage, masked_text: str) -> str:
    normalized_text = _normalize_tr(masked_text)
    if any(term in normalized_text for term in _NORMALIZED_INJURY_TERMS):
        urgency = "critical"
        logger.warning(f"raw_message_id={msg.id} | Deterministic rule triggered: CRITICAL INJURY")
    else:
        # TODO(S1-15)
        urgency = "normal"

    msg.status = "classified"
    log_audit(db, "classification", raw_message_id=msg.id, detail={"urgency": urgency})
    return urgency


def step_route(db: Session, msg: RawMessage, masked_text: str, urgency: str) -> Claim:
    # Extraction/validation (Post S1-15)
    claim = Claim(
        raw_message_id=msg.id,
        channel=msg.channel,
        content_type="claim",
        urgency=urgency,
        data={"masked_text": masked_text},
        status="in_human_review",
    )
    db.add(claim)
    db.flush()

    log_audit(
        db,
        "routing",
        raw_message_id=msg.id,
        claim_id=claim.id,
        detail={"status": claim.status},
    )
    return claim


def process_message(db: Session, raw_message_id: int) -> None:
    msg = db.get(RawMessage, raw_message_id)
    if msg is None:
        logger.error(f"raw_message_id={raw_message_id} not found in DB, skipping")
        return

    try:
        masked_text = step_mask(db, msg)
        urgency = step_classify(db, msg, masked_text)
        step_route(db, msg, masked_text, urgency)
        db.commit()
        logger.info(f"raw_message_id={raw_message_id} | pipeline completed | status={msg.status}")
    except Exception as e:
        db.rollback()
        failed_msg = db.get(RawMessage, raw_message_id)
        if failed_msg is not None:
            failed_msg.status = "dead_letter"
            db.add(
                AuditTrail(
                    raw_message_id=raw_message_id,
                    step="pipeline_error",
                    detail={"error": str(e)},
                )
            )
            db.commit()
        logger.error(f"raw_message_id={raw_message_id} pipeline failed: {e}", exc_info=True)
