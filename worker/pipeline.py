import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from api.models.db import AuditTrail, Claim, MaskMapping, RawMessage
from worker.classification.classifier import (
    INJURY_OVERRIDE,
    ClassificationResult,
    classify,
    fallback_classification,
)
from worker.classification.schema import ContentType
from worker.embedding.store import store_embedding
from worker.extraction.extractor import extract
from worker.masking.pipeline import mask_all
from worker.masking.sanity import SanityCheckResult, check_sanity, is_sanity_enabled
from worker.masking.unmask import unmask_data
from worker.routing.auto_approve import evaluate
from worker.validation.validator import validate

logger = logging.getLogger("worker.pipeline")


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
        result = check_sanity(masked_text, message_id=str(msg.id), external_ref=msg.external_ref)
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


def step_classify(db: Session, msg: RawMessage, masked_text: str) -> ClassificationResult:
    """Decide content type and urgency, and record how the decision was reached.

    The deterministic injury override is inside classify(), not here, so that
    eval measures the same rule the pipeline runs (see the classifier's module
    docstring). What is left here is persistence, the audit trail, and what to do
    when the call does not come back.

    A failed call falls back rather than dead-lettering the message. Losing the
    high/normal split and the content type degrades triage; dropping the message
    loses an injury report, and CLAUDE.md §7 asks for >= 97% critical recall
    precisely because that is the one error this system must not make. The
    fallback still runs the injury terms, so a critical claim stays critical with
    no model involved. Same principle as step_extract, which also refuses to send
    a claim to the dead letter queue over a failure of its own.
    """
    try:
        result = classify(
            masked_text,
            msg.channel,
            message_id=str(msg.id),
            external_ref=msg.external_ref,
        )
    except Exception as e:
        logger.error(f"raw_message_id={msg.id} classification failed: {e}", exc_info=True)
        result = fallback_classification(masked_text)
        log_audit(
            db,
            "classification_error",
            raw_message_id=msg.id,
            detail={
                "error": str(e),
                "fallback_urgency": str(result.urgency),
                "injury_signals": result.injury_signals,
            },
        )
    else:
        log_audit(
            db,
            "classification",
            raw_message_id=msg.id,
            detail={
                "content_type": str(result.content_type),
                "urgency": str(result.urgency),
                # The model's own answer, kept beside the final one. When the
                # override fires this is the only evidence of whether the model
                # would have missed the case, and a critical-recall number has to
                # be able to explain that split.
                "llm_urgency": str(result.llm_urgency),
                "urgency_source": result.urgency_source,
                "injury_signals": result.injury_signals,
                # The sentence the model says proves an injury. "Why is this
                # critical" is the error centre's question and an auditor's, and
                # the quote answers it in a way a boolean cannot. Safe to store:
                # it is a span of the masked text the model was shown.
                "injury_evidence": result.injury_evidence,
                "reasoning": result.reasoning,
            },
            provider="openai",
            duration_ms=result.duration_ms,
        )

    if result.urgency_source == INJURY_OVERRIDE:
        logger.warning(f"raw_message_id={msg.id} | Deterministic rule triggered: CRITICAL INJURY")

    msg.status = "classified"
    return result


def step_route(
    db: Session,
    msg: RawMessage,
    masked_text: str,
    classification: ClassificationResult,
    sanity_result: SanityCheckResult,
) -> Claim:
    claim = Claim(
        raw_message_id=msg.id,
        channel=msg.channel,
        content_type=str(classification.content_type),
        urgency=str(classification.urgency),
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
        detail={
            "status": claim.status,
            "content_type": claim.content_type,
            "urgency": claim.urgency,
        },
    )
    return claim


def step_extract(db: Session, msg: RawMessage, claim: Claim, masked_text: str) -> None:
    # A masking sanity flag does not stop extraction, though it used to.
    #
    # prompts/masking_sanity_v1.txt rule 4 tells the model to flag on suspicion
    # ("yanlış pozitif vermek, kaçırmaktan daha güvenlidir"). A layer built to
    # over-report cannot also be a hard gate, and as one it blocked all 7 of the
    # 7 messages in the 2026-08-08 rehearsal - every one of them a false
    # positive, on text where the placeholders were plainly there. Extraction
    # was dead for the whole run, which is why MASKING_SANITY_ENABLED had to be
    # switched off to demo at all.
    #
    # Nor did the gate contain anything. By the time a flag exists the sanity
    # pass has already sent this exact text to the model, and step_route has
    # already written it to the claim, where the Kuyruk detail panel shows it to
    # any operator. Skipping extraction removed the claim's fields; it did not
    # remove the leak.
    #
    # The flag still has teeth in the one place a suspicion belongs: it blocks
    # auto-approval (worker/routing/auto_approve.py, REASON_SANITY_FLAG), so a
    # flagged claim reaches a human with its fields filled in - which is what
    # someone judging whether the text really leaked needs to see.

    # Design doc §4's early exit: only claims go on to extraction. A question
    # about a policy has no plate or incident date to pull out, and asking for
    # them anyway spends a call to be told nothing - or worse, to be told
    # something. Checked off the claim rather than the classification result so
    # a message reprocessed later reads the verdict that was stored.
    if claim.content_type != ContentType.CLAIM:
        log_audit(
            db,
            "extraction_skipped",
            claim_id=claim.id,
            detail={"reason": "not_a_claim", "content_type": claim.content_type},
        )
        return

    try:
        result = extract(
            masked_text,
            received_at=msg.received_at,
            channel=msg.channel,
            message_id=str(msg.id),
            external_ref=msg.external_ref,
        )

        mappings = db.query(MaskMapping).filter(MaskMapping.raw_message_id == msg.id).all()
        mapping_dicts = [
            {"placeholder": m.placeholder, "real_value": m.real_value} for m in mappings
        ]
        unmasked_extraction = unmask_data(result.extraction, mapping_dicts)

        claim.data = {
            **(claim.data or {}),
            "extraction": unmasked_extraction,
            # Stored on the claim, not only in the audit row below. This is the
            # hallucination check's output - the fields whose quote could not be
            # found in the source text - and the auto-approval gate reads it,
            # which means it has to travel with the claim rather than sit in a
            # row someone would have to go looking for.
            "unverified_fields": result.unverified_fields,
        }

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


def step_auto_approve(db: Session, msg: RawMessage, claim: Claim) -> None:
    """The state machine's last transition: approve, or leave it for a human.

    Runs last, after extraction, validation and embedding, because it is the
    only step whose input is everything the others produced.

    An audit row is written either way, the same arrangement masking sanity uses.
    "Why did this need a human" is the question the error centre and the
    precision measurement both ask, and answering it only for the claims that
    passed would leave the interesting half unrecorded.
    """
    data = claim.data or {}
    decision = evaluate(
        content_type=claim.content_type,
        urgency=claim.urgency,
        validation_flags=data.get("validation_flags") or [],
        unverified_fields=data.get("unverified_fields") or [],
        has_sanity_flags=bool(data.get("masking_sanity_flags")),
        extraction_present=bool(data.get("extraction")),
    )

    if decision.approved:
        # claim.status only. RawMessage.status is the pipeline's own progress
        # ('received' | 'masked' | 'classified' | 'dead_letter', as
        # worker/rag/schema_context.py documents it to the SQL model), and
        # approval is a fact about the claim, not about how far the message got.
        # It is also the same transition /queue/{id}/approve performs, so both
        # routes into `approved` mean one thing.
        claim.status = "approved"

    log_audit(
        db,
        "auto_approve",
        raw_message_id=msg.id,
        claim_id=claim.id,
        detail={
            "approved": decision.approved,
            "reasons": decision.reasons,
            "blocking_flags": decision.blocking_flags,
            # Recorded even though they changed nothing: a rule sitting in the
            # advisory set is a judgement that has to stay visible, and the
            # measurement that moves rules between the two sets reads this.
            "advisory_flags": decision.advisory_flags,
        },
    )


def step_embed(db: Session, msg: RawMessage, claim: Claim, masked_text: str) -> None:
    """Embed the claim text so RAG retrieval can reach it (ADR-003).

    Runs off masked_text rather than the extraction output. A claim whose
    extraction failed is still a claim an operator may ask about, and tying the
    two together would make every extraction failure a silent hole in search.

    A masking sanity flag no longer skips this, matching step_extract: one
    decision, applied the same way in both places. The reasoning is there in
    full; the part specific to embedding is that store_embedding writes a vector
    and nothing else - the text is not persisted here, and the encoder is local
    (ADR-002), so no flagged text leaves the machine. What skipping did buy was
    a claim missing from every search, including the searches an operator would
    run precisely because it was flagged.
    """
    try:
        result = store_embedding(db, claim.id, masked_text)
        log_audit(
            db,
            "embedding",
            raw_message_id=msg.id,
            claim_id=claim.id,
            detail={"dimensions": result.dimensions, "text_length": result.text_length},
            provider=result.model,
            duration_ms=result.duration_ms,
        )
    except Exception as e:
        logger.error(f"raw_message_id={msg.id} embedding failed: {e}", exc_info=True)
        log_audit(
            db,
            "embedding_error",
            raw_message_id=msg.id,
            claim_id=claim.id,
            detail={"error": str(e)},
        )
        # Same rule as extraction (see step_extract): claim.status is left alone.
        # A claim that cannot be embedded is still triaged and still queued - it
        # is only invisible to RAG until a backfill picks it up.


def process_message(db: Session, raw_message_id: int) -> None:
    msg = db.get(RawMessage, raw_message_id)
    if msg is None:
        logger.error(f"raw_message_id={raw_message_id} not found in DB, skipping")
        return

    try:
        masked_text = step_mask(db, msg)
        sanity_result = step_mask_sanity(db, msg, masked_text)
        classification = step_classify(db, msg, masked_text)
        claim = step_route(db, msg, masked_text, classification, sanity_result)
        step_extract(db, msg, claim, masked_text)
        step_embed(db, msg, claim, masked_text)
        step_auto_approve(db, msg, claim)
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
