# worker/validation/validator.py
"""Deterministic post-extraction checks.

Pure function, same style as worker/masking/unmask.py: no DB, no session, no
side effects, never raises. A flag routes the claim to human review — it
never blocks or rejects it (CLAUDE.md S1: uncertain cases go to a human,
they are not silently dropped).

Injury cross-check (rule 8) shares its word list and Turkish-safe comparison
with worker/pipeline.py's classification trigger — see
worker/shared/injury_terms.py, the single source of truth for both.
"""

import re
from datetime import date

from worker.shared.injury_terms import INJURY_TERMS, _normalize_tr

PLATE_PATTERN = re.compile(r"^\d{2}\s?[A-ZÇĞİÖŞÜ]{1,3}\s?\d{2,4}$")

# Synthetic pattern from gt_generator; pending @muyesser10 confirmation
POLICY_NO_PATTERN = re.compile(r"^POL-\d{4}-\d{5}$")

URGENCIES = {"critical", "high", "normal"}
DAMAGE_TYPES = {
    "collision",
    "single_vehicle",
    "glass",
    "hail",
    "fire",
    "theft",
    "animal",
    "other",
}
CONTENT_TYPES = {"claim", "info_request", "irrelevant"}

# Normalized once at import time — the terms are compared many times per
# validate() call, the text they're written against never changes.
_NORMALIZED_INJURY_TERMS = tuple(_normalize_tr(term) for term in INJURY_TERMS)


def _flag(field: str, rule: str, message: str) -> dict:
    return {"field": field, "rule": rule, "message": message}


def _parse_iso_date(value: object) -> date | None:
    """Accept both a `date` object and an ISO string; None if unparseable."""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def validate(extraction: dict, raw_text: str) -> list[dict]:
    """Run deterministic validation rules on extraction output.

    Returns a list of flags (empty list = all valid). Never raises, never
    rejects — flags route the claim to human review, they don't block it.
    Each flag: {"field": str, "rule": str, "message": str}
    """
    flags: list[dict] = []

    plate = extraction.get("plate")
    if plate is not None and not PLATE_PATTERN.match(plate):
        flags.append(_flag("plate", "invalid_plate_format", f"'{plate}' plaka desenine uymuyor"))

    policy_no = extraction.get("policy_no")
    if policy_no is not None and not POLICY_NO_PATTERN.match(policy_no):
        flags.append(
            _flag(
                "policy_no",
                "invalid_policy_no_format",
                f"'{policy_no}' POL-YYYY-NNNNN desenine uymuyor",
            )
        )

    incident_date = extraction.get("incident_date")
    if incident_date is not None:
        parsed_date = _parse_iso_date(incident_date)
        if parsed_date is None:
            flags.append(
                _flag(
                    "incident_date",
                    "invalid_date_format",
                    f"'{incident_date}' ISO YYYY-MM-DD olarak parse edilemedi",
                )
            )
        elif parsed_date > date.today():
            flags.append(
                _flag(
                    "incident_date",
                    "future_incident_date",
                    f"'{incident_date}' gelecekte bir tarih, kaza gelecekte olamaz",
                )
            )

    estimated_amount = extraction.get("estimated_amount")
    if estimated_amount is not None:
        if not isinstance(estimated_amount, (int, float)) or estimated_amount < 0:
            flags.append(
                _flag(
                    "estimated_amount",
                    "invalid_estimated_amount",
                    f"'{estimated_amount}' negatif olmayan bir sayı değil",
                )
            )

    urgency = extraction.get("urgency")
    if urgency not in URGENCIES:
        flags.append(
            _flag("urgency", "invalid_urgency", f"'{urgency}' geçerli bir urgency değeri değil")
        )

    damage_type = extraction.get("damage_type")
    if damage_type is not None and damage_type not in DAMAGE_TYPES:
        flags.append(
            _flag(
                "damage_type",
                "invalid_damage_type",
                f"'{damage_type}' geçerli bir damage_type değeri değil",
            )
        )

    content_type = extraction.get("content_type")
    if content_type not in CONTENT_TYPES:
        flags.append(
            _flag(
                "content_type",
                "invalid_content_type",
                f"'{content_type}' geçerli bir content_type değeri değil",
            )
        )

    injury = extraction.get("injury")
    normalized_text = _normalize_tr(raw_text)
    if injury is not True and any(term in normalized_text for term in _NORMALIZED_INJURY_TERMS):
        flags.append(
            _flag(
                "injury",
                "injury_keyword_mismatch",
                "Metinde yaralanma ifadesi geçiyor ama injury=true değil",
            )
        )

    if injury is True and urgency != "critical":
        flags.append(
            _flag(
                "urgency",
                "injury_not_critical",
                "injury=true ama urgency critical değil",
            )
        )

    counterparty_exists = extraction.get("counterparty_exists")
    if counterparty_exists is True and damage_type == "single_vehicle":
        flags.append(
            _flag(
                "counterparty_exists",
                "counterparty_single_vehicle_conflict",
                "damage_type=single_vehicle ama counterparty_exists=true",
            )
        )

    if content_type == "claim" and plate is None and incident_date is None:
        flags.append(
            _flag(
                "content_type",
                "claim_missing_core_fields",
                "content_type=claim ama plate ve incident_date ikisi de null",
            )
        )

    return flags
