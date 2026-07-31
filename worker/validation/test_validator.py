# worker/validation/test_validator.py
"""Tests for the deterministic post-extraction validator."""

from worker.validation.validator import _normalize_tr, validate

CLEAN_EXTRACTION = {
    "policy_no": "POL-2025-12345",
    "plate": "34 ABC 123",
    "incident_date": "2026-07-01",
    "damage_description": "on tampon hasarli",
    "damage_type": "collision",
    "injury": False,
    "counterparty_exists": True,
    "estimated_amount": 5000,
    "content_type": "claim",
    "urgency": "normal",
    "incident_location": {"city": "İstanbul", "district": None},
}
CLEAN_TEXT = "Aracim 34 ABC 123 ile carpisti, hasar var."


def _with(**overrides):
    return {**CLEAN_EXTRACTION, **overrides}


def test_completely_clean_extraction_returns_empty_list():
    assert validate(CLEAN_EXTRACTION, CLEAN_TEXT) == []


# --- Rule 1: plate format ------------------------------------------------


def test_invalid_plate_format_flags():
    flags = validate(_with(plate="ABC123"), CLEAN_TEXT)
    assert any(f["rule"] == "invalid_plate_format" for f in flags)


def test_valid_plate_format_passes():
    flags = validate(_with(plate="06 FGB 3815"), CLEAN_TEXT)
    assert not any(f["rule"] == "invalid_plate_format" for f in flags)


# --- Rule 2: policy_no format ---------------------------------------------


def test_invalid_policy_no_format_flags():
    flags = validate(_with(policy_no="POL-25-123"), CLEAN_TEXT)
    assert any(f["rule"] == "invalid_policy_no_format" for f in flags)


def test_valid_policy_no_format_passes():
    flags = validate(_with(policy_no="POL-2020-99999"), CLEAN_TEXT)
    assert not any(f["rule"] == "invalid_policy_no_format" for f in flags)


# --- Rule 3: incident_date parse + not in the future -----------------------


def test_unparseable_incident_date_flags():
    flags = validate(_with(incident_date="01/07/2026"), CLEAN_TEXT)
    assert any(f["rule"] == "invalid_date_format" for f in flags)


def test_future_incident_date_flags():
    flags = validate(_with(incident_date="2099-01-01"), CLEAN_TEXT)
    assert any(f["rule"] == "future_incident_date" for f in flags)


def test_past_incident_date_passes():
    flags = validate(_with(incident_date="2020-01-01"), CLEAN_TEXT)
    assert not any(f["field"] == "incident_date" for f in flags)


# --- Rule 4: estimated_amount ----------------------------------------------


def test_negative_estimated_amount_flags():
    flags = validate(_with(estimated_amount=-100), CLEAN_TEXT)
    assert any(f["rule"] == "invalid_estimated_amount" for f in flags)


def test_positive_estimated_amount_passes():
    flags = validate(_with(estimated_amount=88841.50), CLEAN_TEXT)
    assert not any(f["rule"] == "invalid_estimated_amount" for f in flags)


# --- Rule 5: urgency enum ----------------------------------------------


def test_invalid_urgency_flags():
    flags = validate(_with(urgency="urgent"), CLEAN_TEXT)
    assert any(f["rule"] == "invalid_urgency" for f in flags)


def test_valid_urgency_passes():
    flags = validate(_with(urgency="high"), CLEAN_TEXT)
    assert not any(f["rule"] == "invalid_urgency" for f in flags)


# --- Rule 6: damage_type enum ----------------------------------------------


def test_invalid_damage_type_flags():
    flags = validate(_with(damage_type="explosion"), CLEAN_TEXT)
    assert any(f["rule"] == "invalid_damage_type" for f in flags)


def test_valid_damage_type_passes():
    flags = validate(_with(damage_type="theft"), CLEAN_TEXT)
    assert not any(f["rule"] == "invalid_damage_type" for f in flags)


# --- Rule 7: content_type enum ----------------------------------------------


def test_invalid_content_type_flags():
    flags = validate(_with(content_type="spam"), CLEAN_TEXT)
    assert any(f["rule"] == "invalid_content_type" for f in flags)


def test_valid_content_type_passes():
    flags = validate(_with(content_type="info_request", plate=None), CLEAN_TEXT)
    assert not any(f["rule"] == "invalid_content_type" for f in flags)


# --- Rule 8: injury keyword cross-check ----------------------------------


def test_injury_keyword_in_text_but_injury_false_flags():
    text = "Kazada bir kisi yaralandi, ambulans cagirdik."
    flags = validate(_with(injury=False), text)
    assert any(f["rule"] == "injury_keyword_mismatch" for f in flags)


def test_no_injury_keyword_and_injury_false_passes():
    flags = validate(_with(injury=False), CLEAN_TEXT)
    assert not any(f["rule"] == "injury_keyword_mismatch" for f in flags)


def test_uppercase_injury_keyword_flags():
    """ "YARALI" must match "yaralı" — str.lower() alone breaks this in Turkish."""
    text = "ARACTA YARALI VAR."
    flags = validate(_with(injury=False), text)
    assert any(f["rule"] == "injury_keyword_mismatch" for f in flags)


def test_uppercase_hastane_keyword_flags():
    text = "HASTANEYE KALDIRILDI."
    flags = validate(_with(injury=False), text)
    assert any(f["rule"] == "injury_keyword_mismatch" for f in flags)


def test_mixed_case_injury_keyword_flags():
    flags_title = validate(_with(injury=False), "Aracta Yaralı var.")
    flags_random = validate(_with(injury=False), "aracta yArAlI var.")
    assert any(f["rule"] == "injury_keyword_mismatch" for f in flags_title)
    assert any(f["rule"] == "injury_keyword_mismatch" for f in flags_random)


# --- _normalize_tr -----------------------------------------------------------


def test_normalize_tr_uppercase_dotless_i():
    assert _normalize_tr("YARALI") == "yaralı"


def test_normalize_tr_uppercase_dotted_i():
    assert _normalize_tr("İSTANBUL") == "istanbul"


def test_normalize_tr_matches_injury_term():
    assert "yaralı" in _normalize_tr("ARACTA YARALI VAR")


# --- Rule 9: injury requires critical urgency ------------------------------


def test_injury_true_but_urgency_not_critical_flags():
    flags = validate(_with(injury=True, urgency="normal"), CLEAN_TEXT)
    assert any(f["rule"] == "injury_not_critical" for f in flags)


def test_injury_true_with_critical_urgency_passes():
    flags = validate(_with(injury=True, urgency="critical"), CLEAN_TEXT)
    assert not any(f["rule"] == "injury_not_critical" for f in flags)


# --- Rule 10: counterparty vs single_vehicle consistency -------------------


def test_single_vehicle_with_counterparty_flags():
    flags = validate(
        _with(damage_type="single_vehicle", counterparty_exists=True),
        CLEAN_TEXT,
    )
    assert any(f["rule"] == "counterparty_single_vehicle_conflict" for f in flags)


def test_single_vehicle_without_counterparty_passes():
    flags = validate(
        _with(damage_type="single_vehicle", counterparty_exists=False),
        CLEAN_TEXT,
    )
    assert not any(f["rule"] == "counterparty_single_vehicle_conflict" for f in flags)


# --- Rule 11: claim needs at least plate or incident_date ------------------


def test_claim_with_no_plate_and_no_date_flags():
    flags = validate(_with(plate=None, incident_date=None), CLEAN_TEXT)
    assert any(f["rule"] == "claim_missing_core_fields" for f in flags)


def test_claim_with_plate_only_passes():
    flags = validate(_with(incident_date=None), CLEAN_TEXT)
    assert not any(f["rule"] == "claim_missing_core_fields" for f in flags)


# --- Null-safety ------------------------------------------------------------


def test_null_optional_fields_skip_their_format_rules():
    """None on a nullable field skips that field's format check entirely."""
    flags = validate(
        _with(
            plate=None,
            policy_no=None,
            incident_date=None,
            damage_type=None,
            content_type="info_request",
        ),
        CLEAN_TEXT,
    )
    assert flags == []


# --- Flag shape --------------------------------------------------------------


def test_flag_shape_has_field_rule_message():
    flags = validate(_with(plate="ABC123"), CLEAN_TEXT)
    assert len(flags) == 1
    flag = flags[0]
    assert set(flag.keys()) == {"field", "rule", "message"}
    assert flag["field"] == "plate"
    assert isinstance(flag["rule"], str)
    assert isinstance(flag["message"], str)
