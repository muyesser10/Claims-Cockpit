# worker/classification/test_schema.py
"""Tests for the classification schema.

The two that earn their keep are the claim.json sync checks: if anyone edits
schemas/claim.json in a [SCHEMA] PR, CI goes red here instead of the prompt
quietly drifting out of sync with the team schema.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from worker.classification.schema import ClaimClassification, ContentType, Urgency

CLAIM_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "claim.json"


def _claim_json() -> dict:
    """Load the frozen team schema."""
    return json.loads(CLAIM_SCHEMA_PATH.read_text(encoding="utf-8"))


def _values(field: str) -> set[str]:
    """The enum values claim.json declares for a field, minus 'null'."""
    return {value.strip() for value in _claim_json()[field].split("|")} - {"null"}


def test_content_type_matches_claim_json():
    assert {member.value for member in ContentType} == _values("content_type")


def test_urgency_matches_claim_json():
    """Includes 'high', which the pipeline's keyword rule never produced."""
    assert {member.value for member in Urgency} == _values("urgency")


def test_extraction_fields_stay_out():
    """Classification decides two things; the rest belongs to extraction."""
    for name in ("plate", "policy_no", "incident_date", "damage_type", "estimated_amount"):
        assert name not in ClaimClassification.model_fields


def test_reasoning_comes_first():
    """Field order is load-bearing: the model reasons before it labels."""
    assert next(iter(ClaimClassification.model_fields)) == "reasoning"


def test_an_invented_label_is_refused():
    with pytest.raises(ValidationError):
        ClaimClassification(
            reasoning="x",
            content_type="complaint",
            urgency="normal",
            injury_mentioned=False,
        )


def test_an_invented_urgency_is_refused():
    with pytest.raises(ValidationError):
        ClaimClassification(
            reasoning="x",
            content_type="claim",
            urgency="acil",
            injury_mentioned=False,
        )
