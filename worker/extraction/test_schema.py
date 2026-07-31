# worker/extraction/test_schema.py
"""Tests for the extraction schema.

The one that earns its keep is test_damage_type_matches_claim_json: if anyone
edits schemas/claim.json in a [SCHEMA] PR, CI goes red here instead of the
prompt quietly drifting out of sync with the team schema.
"""

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from worker.extraction.schema import ClaimExtraction, DamageType

CLAIM_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "claim.json"


def _claim_json() -> dict:
    """Load the frozen team schema."""
    return json.loads(CLAIM_SCHEMA_PATH.read_text(encoding="utf-8"))


def test_damage_type_matches_claim_json():
    """Our enum carries exactly the values claim.json declares."""
    raw = _claim_json()["damage_type"]  # "collision | single_vehicle | ... | null"
    expected = {value.strip() for value in raw.split("|")} - {"null"}
    ours = {member.value for member in DamageType}
    assert ours == expected


def test_classification_fields_stay_out():
    """content_type/urgency belong to classification, channel to the system."""
    for name in ("channel", "content_type", "urgency", "status"):
        assert name not in ClaimExtraction.model_fields


def test_reasoning_comes_first():
    """Design doc §3.3: the model reasons before it commits to values."""
    assert next(iter(ClaimExtraction.model_fields)) == "reasoning"


def test_message_with_nothing_extractable():
    """A message with no claim data: everything null, nothing invented."""
    claim = ClaimExtraction(reasoning="Metinde hasar bilgisi yok.")
    assert claim.policy_no is None
    assert claim.plate is None
    assert claim.incident_date is None
    assert claim.incident_location.city is None
    assert claim.missing_fields == []


def test_realistic_record_parses():
    """A filled-in record, shaped after data/emails.jsonl GT-000002."""
    claim = ClaimExtraction(
        reasoning="'8 Temmuz' mutlak tarih, mesaj 2026'da geldi. İlçe belirtilmemiş.",
        policy_no="POL-2025-19116",
        plate="06 FGB 3815",
        incident_date="2026-07-08",
        incident_location={"city": "İstanbul", "district": None},
        damage_description="otoparktan çalındı",
        damage_type="theft",
        injury=False,
        counterparty_exists=True,
        estimated_amount=88841,
        missing_fields=["district"],
        source_references={"plate": "06 FGB 3815 plakalı"},
        field_confidence={"plate": 0.99, "incident_date": 0.85},
        low_confidence_fields=[],
    )
    assert claim.incident_date == date(2026, 7, 8)
    assert claim.damage_type is DamageType.THEFT
    assert claim.estimated_amount == 88841.0
    assert claim.source_references["plate"] == "06 FGB 3815 plakalı"


def test_plain_string_quote_is_the_contract():
    """What gpt-4o produces unprompted, and what the schema now asks for."""
    claim = ClaimExtraction(
        reasoning="x",
        source_references={"plate": "34 ABC 123 plakalı"},
    )
    assert claim.source_references["plate"] == "34 ABC 123 plakalı"


def test_wrapped_quote_is_flattened_instead_of_retried():
    """Measured 2026-07-30: a nested single-key object cost two extra calls.

    gpt-4o answered with a bare string first, then guessed the key `text`, and
    only reached `quote` once the validation error spelled the name out. All
    three shapes carry the same information, so all three are accepted.
    """
    claim = ClaimExtraction(
        reasoning="x",
        source_references={
            "plate": {"quote": "34 ABC 123 plakalı"},
            "policy_no": {"text": "Poliçe numaram POL-1"},
        },
    )
    assert claim.source_references == {
        "plate": "34 ABC 123 plakalı",
        "policy_no": "Poliçe numaram POL-1",
    }


def test_damage_type_outside_the_enum_is_rejected():
    """'hırsızlık' is not one of the eight values, so the model gets corrected."""
    with pytest.raises(ValidationError):
        ClaimExtraction(reasoning="x", damage_type="hırsızlık")


def test_relative_date_is_rejected():
    """The model may not hand back 'dün' — instructor retries on this error."""
    with pytest.raises(ValidationError):
        ClaimExtraction(reasoning="x", incident_date="dün")


def test_amount_with_currency_is_rejected():
    """'88841 TL' is text, not a number — data contract §3.1."""
    with pytest.raises(ValidationError):
        ClaimExtraction(reasoning="x", estimated_amount="88841 TL")
