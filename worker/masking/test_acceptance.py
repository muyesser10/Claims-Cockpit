# worker/masking/test_acceptance.py
"""Acceptance test for S1-4: PII is caught across realistic sample texts."""

from worker.masking.pipeline import mask_all

SAMPLES = [
    ("Ben Ahmet, TC 12345678901, aracim 06ABC34 hasar gordu", ["TC", "PLATE", "NAME"]),
    ("Numaram 0532 111 22 33, plaka 34XY123", ["PHONE", "PLATE"]),
    ("Mehmet aradi, IBAN TR330006100519786457841326", ["NAME", "IBAN"]),
    ("Kaza yaptim, poliçe POL-999, tel 05001234567", ["PHONE"]),
    ("Ayse hanim 35 ABC 45 plakali araci gordu", ["NAME", "PLATE"]),
    ("TC 98765432109 ile basvurdum", ["TC"]),
    ("Ali ve Veli 06 A 1234 aracindaydi", ["NAME", "PLATE"]),
    ("Hasar 3500 TL, numaram 0555 987 65 43", ["PHONE"]),
    ("Fatma teyze IBAN TR120001000000000000000001", ["NAME", "IBAN"]),
    ("Plaka 81 XYZ 99, TC 11122233344", ["PLATE", "TC"]),
]


def test_all_samples_have_no_leaked_pii():
    """No raw TC/phone/plate/IBAN digits survive masking in any sample."""
    for text, _ in SAMPLES:
        masked, mappings = mask_all(text)
        # Every mapping's real value must be gone from the masked text.
        for m in mappings:
            assert m["real_value"] not in masked


def test_expected_types_caught():
    """Each sample catches at least the expected PII types."""
    for text, expected_types in SAMPLES:
        masked, mappings = mask_all(text)
        found_types = {m["pii_type"] for m in mappings}
        for expected in expected_types:
            assert expected in found_types, f"{expected} missing in: {text}"
