# worker/shared/test_injury_terms.py
"""Sanity tests for the shared injury-term dictionary and its matcher.

The matcher tests below are grouped by the three defects they exist for, each
measured over the 1000-record corpus on 2026-08-04. Plain substring matching
scored 18.5% precision at 100% recall; with all three handled, 98.8% at 100%.
Recall is the number that must not move.
"""

import pytest

from worker.shared.injury_terms import INJURY_TERMS, _normalize_tr, find_injury_signals


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


# --- what must always be found -------------------------------------------
# Recall is the one number that cannot regress: a missed injury is the error
# this system exists to prevent (CLAUDE.md §7, critical recall >= 97%).


@pytest.mark.parametrize(
    "text",
    [
        "araçta yaralı var",
        "ARAÇTA YARALI VAR",
        "yaralıydı, hastaneye götürdüler",
        "ambulans çağırdık",
        "eşim acil servise kaldırıldı",
        "kolunda kırık var",
        "Yaralanma: evet",
        "yaralanma oldu maalesef",
    ],
)
def test_a_stated_injury_is_always_found(text):
    assert find_injury_signals(text)


def test_suffixed_terms_still_match():
    """Turkish suffixes attach to the right, so only the left edge is bounded."""
    assert find_injury_signals("hastaneye kaldırıldı")
    assert find_injury_signals("yaralıyı aldılar")


# --- substring: the terms are short and Turkish is agglutinative ----------


@pytest.mark.parametrize(
    "text",
    [
        "motor bölümüne giren bir kedi kabloları kemirdi",  # bölüm -> ölü
        "dükkanın önünde park halindeydi",  # dükkan -> kan
        "imkanım yok şu an",  # imkan -> kan
        "mekanik arıza var",  # mekan -> kan
    ],
)
def test_a_term_inside_another_word_is_not_a_signal(text):
    assert find_injury_signals(text) == []


# --- negation ------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "kazada kimse yaralanmadı",
        "hayır, kazada kimse yaralanmadı",
        "Yaralanma: hayır",
        "yaralanan yok",
        "yaralı yoktu",
        "kimse yaralanmaz orada",
    ],
)
def test_a_negated_term_is_not_a_signal(text):
    assert find_injury_signals(text) == []


# --- empty form field ----------------------------------------------------


def test_a_blank_form_label_is_not_a_signal():
    """web_form messages carry the label whether or not it was filled in."""
    text = "Hasar: ön cam çatladı\nYaralanma: \nTahmini Hasar: 22068 TL"
    assert find_injury_signals(text) == []


def test_a_filled_form_label_still_is():
    text = "Hasar: ön cam çatladı\nYaralanma: sürücü yaralandı\nTahmini Hasar: 22068 TL"
    assert find_injury_signals(text)


# --- shape ---------------------------------------------------------------


def test_every_matching_term_is_reported_once():
    signals = find_injury_signals("yaralı vardı, ambulans geldi, hastaneye gittik")
    assert signals == [term for term in INJURY_TERMS if term in signals]
    assert len(signals) == len(set(signals))


def test_clean_text_yields_nothing():
    assert find_injury_signals("aracımın camı çatladı, park halindeydi") == []
