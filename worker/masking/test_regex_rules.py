# worker/masking/test_regex_rules.py
"""Tests for PII regex masking."""

from worker.masking.regex_rules import mask_text


def test_tc_masking():
    """An 11-digit TC number is masked."""
    masked, mappings = mask_text("TC kimlik 12345678901 numarasi")
    assert "[TC_1]" in masked
    assert "12345678901" not in masked
    assert mappings[0]["pii_type"] == "TC"


def test_phone_masking():
    """A Turkish mobile number is masked."""
    masked, mappings = mask_text("Numaram 0532 111 22 33 arayin")
    assert "[PHONE_1]" in masked
    assert "0532" not in masked


def test_plate_masking():
    """A license plate is masked."""
    masked, mappings = mask_text("Aracim 06ABC34 hasar gordu")
    assert "[PLATE_1]" in masked
    assert "06ABC34" not in masked


def test_iban_masking():
    """A Turkish IBAN is masked."""
    masked, mappings = mask_text("Hesabim TR330006100519786457841326 numarali")
    assert "[IBAN_1]" in masked
    assert "TR33" not in masked


def test_same_value_same_placeholder():
    """The same value gets the same placeholder both times."""
    masked, mappings = mask_text("Plaka 06ABC34 ve yine 06ABC34 arac")
    assert masked.count("[PLATE_1]") == 2
    assert len(mappings) == 1


def test_multiple_pii_types():
    """TC, phone and plate in one text are all masked."""
    text = "TC 12345678901, plaka 06ABC34, tel 0532 111 22 33"
    masked, mappings = mask_text(text)
    types = {m["pii_type"] for m in mappings}
    assert types == {"TC", "PLATE", "PHONE"}
