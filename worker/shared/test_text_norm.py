# worker/shared/test_text_norm.py
"""Tests for Turkish-to-ASCII folding."""

from worker.shared.text_norm import fold_tr_ascii


def test_fold_lowercase_turkish_chars():
    assert fold_tr_ascii("hüseyin") == "huseyin"


def test_fold_capitalized_name():
    assert fold_tr_ascii("Hüseyin") == "huseyin"


def test_fold_omer():
    assert fold_tr_ascii("Ömer") == "omer"


def test_fold_all_caps_with_multiple_turkish_chars():
    assert fold_tr_ascii("ÇAĞRI") == "cagri"


def test_fold_dotted_capital_i():
    """İ is the bug fold_tr_ascii exists to sidestep: "İ".lower() alone
    produces "i̇" (i + combining dot), not plain "i"."""
    assert fold_tr_ascii("İSTANBUL") == "istanbul"


def test_fold_plain_ascii_name_unaffected():
    assert fold_tr_ascii("Ahmet") == "ahmet"


def test_fold_ordinary_turkish_word():
    assert fold_tr_ascii("dün") == "dun"
