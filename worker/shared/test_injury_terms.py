# worker/shared/test_injury_terms.py
"""Sanity tests for the shared injury-term dictionary."""

from worker.shared.injury_terms import INJURY_TERMS, _normalize_tr


def test_injury_terms_has_twelve_terms():
    assert len(INJURY_TERMS) == 12


def test_injury_terms_contains_expected_words():
    assert set(INJURY_TERMS) == {
        "yaralı",
        "yaralanma",
        "kan",
        "hastane",
        "ambulans",
        "yaralandı",
        "ölü",
        "ölüm",
        "sedye",
        "kırık",
        "bilinç",
        "acil servis",
    }


def test_normalize_tr_uppercase_dotless_i():
    assert _normalize_tr("YARALI") == "yaralı"


def test_normalize_tr_uppercase_dotted_i():
    assert _normalize_tr("İSTANBUL") == "istanbul"
