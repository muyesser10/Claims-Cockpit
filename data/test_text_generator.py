"""Tests  text generator."""

import random

from data.text_generator import (
    build_email,
    build_form,
    build_transcript,
    load_dictionaries,
)


def _sample_gt(overrides: dict | None = None) -> dict:
    """A minimal email-channel ground truth record for testing."""
    gt = {
        "gt_id": "GT-TEST01",
        "received_at": "2026-07-20T10:00:00",
        "expected": {
            "channel": "email",
            "content_type": "claim",
            "urgency": "normal",
            "policy_no": "POL-2024-12345",
            "plate": "34 AB 123",
            "incident_date": "2026-07-19",
            "incident_location": {"city": "İzmir", "district": "Bornova"},
            "damage_description": None,
            "damage_type": "glass",
            "injury": False,
            "counterparty_exists": False,
            "estimated_amount": 15000,
        },
        "_personal": {"name": "Ahmet Yılmaz", "phone": "0532 111 2233", "tc": "12345678901"},
    }
    if overrides:
        gt["expected"].update(overrides)
    return gt


def test_personal_data_in_text():
    """Name and phone must appear in the email (masking material)."""
    random.seed(42)
    dicts = load_dictionaries()
    gt = _sample_gt()
    email, _ = build_email(gt, dicts)
    assert gt["_personal"]["name"] in email
    assert gt["_personal"]["phone"] in email


def test_null_amount_not_in_text():
    """If estimated_amount is null, no amount should appear in the text."""
    random.seed(42)
    dicts = load_dictionaries()
    gt = _sample_gt({"estimated_amount": None})
    email, _ = build_email(gt, dicts)
    assert "TL" not in email


def test_amount_in_text_when_present():
    """If estimated_amount is set, it should appear in the text."""
    random.seed(42)
    dicts = load_dictionaries()
    gt = _sample_gt({"estimated_amount": 25000})
    email, _ = build_email(gt, dicts)
    assert "25000" in email


def test_damage_phrase_matches_type():
    """The returned damage phrase must come from the correct damage_type pool."""
    random.seed(42)
    dicts = load_dictionaries()
    gt = _sample_gt({"damage_type": "theft"})
    _, damage_phrase = build_email(gt, dicts)
    assert damage_phrase in dicts["damage_phrases"]["theft"]


def test_injury_line_only_when_true():
    """Injury sentence appears only if injury is true."""
    random.seed(42)
    dicts = load_dictionaries()
    gt_no = _sample_gt({"injury": False})
    email_no, _ = build_email(gt_no, dicts)
    assert "yaralanan" not in email_no


def test_transcript_has_dialogue_and_pii():
    """Transcript is Agent/Müşteri dialogue and carries PII in text."""
    random.seed(42)
    dicts = load_dictionaries()
    gt = _sample_gt()
    text, _ = build_transcript(gt, dicts)
    assert "Ajan:" in text
    assert "Müşteri:" in text
    assert gt["_personal"]["name"] in text


def test_transcript_null_amount_not_in_text():
    """Transcript omits amount when estimated_amount is null."""
    random.seed(42)
    dicts = load_dictionaries()
    gt = _sample_gt({"estimated_amount": None})
    text, _ = build_transcript(gt, dicts)
    assert "TL" not in text


def test_form_is_labeled_and_telegraphic():
    """Form is labeled plain text with a short damage phrase."""
    random.seed(42)
    dicts = load_dictionaries()
    gt = _sample_gt()
    text, damage_phrase = build_form(gt, dicts)
    assert "Poliçe No:" in text
    assert "Plaka:" in text
    assert gt["_personal"]["name"] in text
    # Form damage phrase comes from the telegraphic dictionary.
    assert damage_phrase in dicts["form_damage_phrases"]["glass"]


def test_form_null_amount_not_in_text():
    """Form omits amount when estimated_amount is null."""
    random.seed(42)
    dicts = load_dictionaries()
    gt = _sample_gt({"estimated_amount": None})
    text, _ = build_form(gt, dicts)
    assert "Tahmini Hasar:" not in text
