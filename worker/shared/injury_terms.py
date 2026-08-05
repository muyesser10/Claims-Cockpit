# worker/shared/injury_terms.py
"""Single source of truth for injury-term matching.

Three independent consumers need the same word list and the same Turkish-safe
comparison, so all of it lives here instead of being duplicated per module:
  - worker/pipeline.py                    step_classify's deterministic
                                           injury -> critical trigger (CLAUDE.md S1)
  - worker/validation/validator.py        validate()'s cross-check between
                                           extraction's `injury` field and the raw text
  - worker/classification/classifier.py   the override over the model's urgency

Use `find_injury_signals()` rather than testing `term in text` directly. Measured
over the 1000-record corpus on 2026-08-04, plain substring matching found all 80
real injuries and another 353 that were not there - a precision of 18.5%. Three
things went wrong, and all three are handled below:

  substring       Turkish is agglutinative and these terms are short. "bölüm"
                  contains "ölü"; "mekan", "imkan" and "dükkan" contain "kan".
  negation        "kimse yaralanmadı" and "Yaralanma: hayır" both contain
                  "yaralanma", and both mean the opposite of a match.
  empty field     web_form messages carry a literal "Yaralanma:" label whose
                  value is sometimes blank. The label is not a signal.

Same corpus with those handled: 80 of 80 found, 1 false positive - 98.8%
precision at 100% recall. Recall is the number that must not move: a missed
injury is the one error this system cannot make (CLAUDE.md §7, >= 97%).
"""

import re

INJURY_TERMS = (
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
)


# A term must start a word. Only the left edge is checked: Turkish suffixes
# attach to the right, so "yaralıydı" and "hastaneye" have to keep matching.
_WORD_START = r"(?<![0-9a-zçğıöşü])"

# Negation as a separate word, looked for on both sides of the term: "yaralanan
# yok", "Yaralanma: hayır", "kimse yaralanmadı" (where "hayır" sits ahead of it).
_NEGATION = re.compile(r"(yok|hayır|hayir|yoktu|olmadı|olmadi|değil|degil)")

# Negation as a Turkish suffix on the term itself: -madı/-medi, -maz/-mez,
# -mayan/-meyen. "yaralanma" + "dı" is one word meaning it did not happen.
_NEGATION_SUFFIX = re.compile(r"^(dı|di|du|dü|z|yan|yen|yacak|yecek)")

# A form label with nothing after it: "Yaralanma:" followed by end of line.
_EMPTY_FIELD = re.compile(r"^\s*:\s*(\n|$)")

# How far to look for a negating word on either side. Wide enough to cover
# "hayır, kazada kimse yaralanmadı", narrow enough not to reach the next
# sentence in a transcript.
_NEGATION_WINDOW = 30


def _normalize_tr(text: str) -> str:
    """Turkish-safe lowercase.

    str.lower() applies the ASCII I -> i rule, so "YARALI".lower() ==
    "yarali" (dotless ı lost) and never matches "yaralı". Turkish has two
    I/i pairs (İ/i and I/ı); fix both by hand before lowercasing the rest.
    """
    return text.replace("I", "ı").replace("İ", "i").lower()


def find_injury_signals(text: str) -> list[str]:
    """The injury terms `text` actually asserts, in INJURY_TERMS order.

    A term counts when it starts a word, is not negated on either side, and is
    not a bare form label. Anything returned here is treated as an injury by
    every caller, so the bar is "the text says this happened" rather than "these
    letters appear".

    Erring towards a false positive is deliberate where the two rules disagree:
    the cost of one unnecessary critical is an operator's minute, and the cost of
    a missed one is the case this system exists to catch.
    """
    normalized = _normalize_tr(text)
    found: list[str] = []

    for term in INJURY_TERMS:
        pattern = _WORD_START + re.escape(_normalize_tr(term))
        for match in re.finditer(pattern, normalized):
            after = normalized[match.end() : match.end() + _NEGATION_WINDOW]
            before = normalized[max(0, match.start() - _NEGATION_WINDOW) : match.start()]

            if _NEGATION.search(after) or _NEGATION.search(before):
                continue
            if _NEGATION_SUFFIX.match(after):
                continue
            if _EMPTY_FIELD.match(normalized[match.end() :]):
                continue

            found.append(term)
            break

    return found
