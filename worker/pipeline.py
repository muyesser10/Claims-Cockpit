import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from api.models.db import AuditTrail, Claim, MaskMapping, RawMessage
from worker.extraction.extractor import extract
from worker.masking.pipeline import mask_all
from worker.masking.sanity import SanityCheckResult, check_sanity, is_sanity_enabled
from worker.masking.unmask import unmask_data
from worker.shared.injury_terms import INJURY_TERMS, _normalize_tr
from worker.validation.validator import validate

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
    provider: str | None = None,
    duration_ms: int | None = None,
) -> None:
    db.add(
        AuditTrail(
            raw_message_id=raw_message_id,
            claim_id=claim_id,
            step=step,
            detail=detail or {},
            provider=provider,
            duration_ms=duration_ms,
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


def _sanity_result_to_flags(result: SanityCheckResult) -> list[dict]:
    """SanityCheckResult -> the flag shape claim.data.masking_sanity_flags uses.

    Only `kind` and `span` ever land here — never the leaked text itself.
    See worker/masking/sanity.py's module docstring: an earlier version
    put the raw snippet in this list, undoing what masking exists to do.
    """
    if not result.leak_found:
        return []
    return [
        {
            "rule": "possible_pii_leak",
            "kind": str(flag.kind),
            "span": list(flag.span) if flag.span else None,
        }
        for flag in result.flags
    ]


def step_mask_sanity(db: Session, msg: RawMessage, masked_text: str) -> SanityCheckResult:
    """LLM sanity pass over already-masked text (S2-6) — the last line of
    defense for whatever regex + the name dictionary missed.

    Runs (and costs an OpenAI call) only when MASKING_SANITY_ENABLED is not
    turned off; when it is, returns a clean result without ever calling the
    LLM. Either way an audit row is written, so "was this checked" is always
    on record.
    """
    enabled = is_sanity_enabled()
    started = time.perf_counter()

    if enabled:
        result = check_sanity(masked_text, message_id=str(msg.id))
    else:
        result = SanityCheckResult(leak_found=False)

    duration_ms = round((time.perf_counter() - started) * 1000)

    log_audit(
        db,
        "masking_sanity",
        raw_message_id=msg.id,
        detail={
            "leak_found": result.leak_found,
            # kind + span only — never the leaked text itself, see
            # worker/masking/sanity.py's module docstring.
            "flags": _sanity_result_to_flags(result),
            "enabled": enabled,
        },
        provider="openai" if enabled else None,
        duration_ms=duration_ms,
    )
    return result


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


def step_route(
    db: Session,
    msg: RawMessage,
    masked_text: str,
    urgency: str,
    sanity_result: SanityCheckResult,
) -> Claim:
    # Extraction/validation (Post S1-15)
    claim = Claim(
        raw_message_id=msg.id,
        channel=msg.channel,
        content_type="claim",
        urgency=urgency,
        data={
            "masked_text": masked_text,
            "masking_sanity_flags": _sanity_result_to_flags(sanity_result),
        },
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


def step_extract(db: Session, msg: RawMessage, claim: Claim, masked_text: str) -> None:
    if claim.data.get("masking_sanity_flags"):
        log_audit(
            db, "extraction_skipped", claim_id=claim.id, detail={"reason": "masking_sanity_flag"}
        )
        return

    try:
        result = extract(
            masked_text,
            received_at=msg.received_at,
            channel=msg.channel,
            message_id=str(msg.id),
        )

        mappings = db.query(MaskMapping).filter(MaskMapping.raw_message_id == msg.id).all()
        mapping_dicts = [
            {"placeholder": m.placeholder, "real_value": m.real_value} for m in mappings
        ]
        unmasked_extraction = unmask_data(result.extraction, mapping_dicts)

        claim.data = {**(claim.data or {}), "extraction": unmasked_extraction}

        log_audit(
            db,
            "extraction",
            raw_message_id=msg.id,
            claim_id=claim.id,
            detail={
                "reasoning": result.reasoning,
                "unverified_fields": result.unverified_fields,
            },
            provider=result.model,
            duration_ms=result.duration_ms,
        )

        step_validate(db, msg, claim, masked_text, unmasked_extraction)

    except Exception as e:
        logger.error(f"raw_message_id={msg.id} extraction failed: {e}", exc_info=True)
        log_audit(
            db,
            "extraction_error",
            raw_message_id=msg.id,
            claim_id=claim.id,
            detail={"error": str(e)},
        )
        # claim.status is intentionally left as-is (in_human_review) —
        # an extraction failure must not send the claim to dead_letter,
        # see standup decision with Çağrı.


def step_validate(
    db: Session, msg: RawMessage, claim: Claim, masked_text: str, extraction: dict
) -> None:
    merged = {**extraction, "urgency": claim.urgency, "content_type": claim.content_type}
    flags = validate(merged, masked_text)

    claim.data = {**(claim.data or {}), "validation_flags": flags}

    log_audit(
        db,
        "validation",
        raw_message_id=msg.id,
        claim_id=claim.id,
        detail={"flag_count": len(flags), "flags": flags},
    )


def process_message(db: Session, raw_message_id: int) -> None:
    msg = db.get(RawMessage, raw_message_id)
    if msg is None:
        logger.error(f"raw_message_id={raw_message_id} not found in DB, skipping")
        return

    try:
        masked_text = step_mask(db, msg)
        sanity_result = step_mask_sanity(db, msg, masked_text)
        urgency = step_classify(db, msg, masked_text)
        claim = step_route(db, msg, masked_text, urgency, sanity_result)
        step_extract(db, msg, claim, masked_text)
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
