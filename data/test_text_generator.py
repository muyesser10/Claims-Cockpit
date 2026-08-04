"""Tests  text generator."""

import random

from data.text_generator import (
    build_email,
    build_form,
    build_info_request,
    build_irrelevant,
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
    """Form is labeled text with both a short damage label and free-text description."""
    random.seed(42)
    dicts = load_dictionaries()
    gt = _sample_gt()
    text, description = build_form(gt, dicts)
    assert "Poliçe No:" in text
    assert "Plaka:" in text
    assert gt["_personal"]["name"] in text
    # Both the telegraphic "Hasar:" label and the free-text "Açıklama:" appear.
    assert "Hasar:" in text
    assert "Açıklama:" in text
    # The returned value is the free-text description (goes to damage_description).
    assert description in dicts["damage_phrases"]["glass"]


def test_form_null_amount_not_in_text():
    """Form omits amount when estimated_amount is null."""
    random.seed(42)
    dicts = load_dictionaries()
    gt = _sample_gt({"estimated_amount": None})
    text, _ = build_form(gt, dicts)
    assert "Tahmini Hasar:" not in text


def test_info_request_is_a_question_not_a_claim():
    """info_request text carries a name and a question, no incident details."""
    random.seed(42)
    dicts = load_dictionaries()
    gt = _sample_gt({"content_type": "info_request"})
    text = build_info_request(gt, dicts)
    assert gt["_personal"]["name"] in text
    # Question comes from the info_request pool.
    assert any(q in text for q in dicts["info_request_templates"])
    # No claim artifacts like a plate or policy line.
    assert "plakalı" not in text


def test_irrelevant_is_off_topic():
    """irrelevant text is one of the off-topic messages."""
    random.seed(42)
    dicts = load_dictionaries()
    gt = _sample_gt({"content_type": "irrelevant"})
    text = build_irrelevant(gt, dicts)
    assert any(m in text for m in dicts["irrelevant_templates"])


def test_urgency_cue_present_for_high_absent_for_normal():
    """High/critical claims get an urgency cue; normal ones don't."""
    random.seed(42)
    dicts = load_dictionaries()
    high_cues = dicts["urgency_phrases"]["high"] + dicts["urgency_phrases"]["critical"]

    gt_high = _sample_gt({"urgency": "high"})
    text_high, _ = build_email(gt_high, dicts)
    assert any(c in text_high for c in high_cues)

    gt_normal = _sample_gt({"urgency": "normal"})
    text_normal, _ = build_email(gt_normal, dicts)
    assert not any(c in text_normal for c in high_cues)


def test_urgency_phrase_empty_for_normal():
    """The urgency helper returns empty string for normal urgency."""
    from data.text_generator import urgency_phrase

    dicts = load_dictionaries()
    assert urgency_phrase({"urgency": "normal"}, dicts) == ""
