# worker/shared/test_injury_terms.py
"""Sanity tests for the shared injury-term dictionary and its matcher.

The matcher tests below are grouped by the three defects they exist for, each
measured over the 1000-record corpus on 2026-08-04. Plain substring matching
scored 18.5% precision at 100% recall; with all three handled, 98.8% at 100%.
Recall is the number that must not move.
"""

import pytest

from worker.shared.injury_terms import INJURY_TERMS, _normalize_tr, find_injury_signals


def test_injury_terms_contains_expected_words():
    assert set(INJURY_TERMS) == {
        "yaralı",
        "yaralanma",
        "yaralandı",
        "yaralanan",
        "kanama",
        "kanıyor",
        "kan kayb",
        "hastane",
        "ambulans",
        "ölü",
        "ölüm",
        "sedye",
        "kırık",
        "bilinç kayb",
        "bilinci kapalı",
        "bilinçsiz",
        "acil servis",
    }


def test_a_term_that_is_only_the_first_syllable_of_another_word_does_not_signal():
    """The three false positives the 2026-08-09 revision removed.

    A bare "kan" matched "kanal", "kanaat" and "kanatlı"; a bare "bilinç"
    matched "bilinçli olarak", which is about doing something deliberately.
    Both were replaced by forms that assert the thing rather than spelling its
    first syllable.
    """
    assert find_injury_signals("Kanal kenarında park halindeydi.") == []
    assert find_injury_signals("Kanaat getirdim, kanatlı bir şey çarptı.") == []
    assert find_injury_signals("Bilinçli olarak yavaşladım.") == []


def test_a_question_about_injuries_is_not_a_report_of_one():
    """Call transcripts open with the agent asking. The word is there; the
    injury is not - and the customer's answer in the same corpus is a denial."""
    text = "Ajan: Aracınızda yaralanan var mı?\nMüşteri: Çok şükür yaralanan olmadı."

    assert find_injury_signals(text) == []


def test_an_injury_typed_without_turkish_letters_still_signals():
    """People type from keyboards that do not have ı, ğ or ç."""
    assert find_injury_signals("Kolumda kirik var, cok agri yapiyor.")
    assert find_injury_signals("Kazada yarali var, hemen donus yapin.")


def test_death_is_not_matched_through_ascii_folding():
    """The deliberate exception. "ölü" folds to "olu", which starts 321 words in
    the corpus that have nothing to do with death - "oluştu", "olursanız"."""
    assert find_injury_signals("Kaza boyle olustu, hasar buyuk.") == []


# --- context terms: medical involvement is not injury ---------------------
# Measured over eval/fixtures/injury_phrasings.jsonl: these four shapes produced
# four of the five false criticals in the injury-free control group. The rule is
# grammatical - a bare noun modifying another noun names a thing in the world.


@pytest.mark.parametrize(
    "text",
    [
        "Aracı hastane otoparkında çizdiler.",
        "Ambulans yolu kapatmıştı, ona çarptım.",
        "Sedye taşıyan bir araca çarptım.",
        "Acil servis tabelasına çarptım.",
    ],
)
def test_a_medical_word_as_a_collision_target_is_not_an_injury(text):
    assert find_injury_signals(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "Eşim hastanede, poliçe bunu karşılıyor mu?",  # inflected: someone is there
        "hastaneye kaldırıldı",  # inflected: someone was taken there
        "eşim acil servise kaldırıldı",
        "ambulans çağırdık",  # bare subject, but the verb is the evidence
        "Kaza oldu, ambulans geldi",
    ],
)
def test_a_medical_word_about_a_person_still_signals(text):
    assert find_injury_signals(text)


def test_one_disqualified_mention_does_not_bury_a_later_one():
    """The guard runs per occurrence, not per text."""
    assert find_injury_signals("Ambulans yolu kapalıydı, sonra ambulans çağırdık")


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
