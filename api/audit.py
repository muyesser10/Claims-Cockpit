# api/audit.py
"""Audit-trail writer for the API layer.

The api/ counterpart to worker/pipeline.py's log_audit(): same shape, so
both sides produce audit_trail rows the same way regardless of which
service made the change.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from api.models.db import AuditTrail

logger = logging.getLogger("api.audit")


def write_audit(
    db: Session,
    step: str,
    *,
    claim_id: int | None = None,
    raw_message_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditTrail(
            claim_id=claim_id,
            raw_message_id=raw_message_id,
            step=step,
            detail=detail or {},
        )
    )
    logger.info(f"AUDIT | claim_id={claim_id} | step={step} | detail={detail}")
