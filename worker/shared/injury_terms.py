# worker/shared/injury_terms.py
"""Single source of truth for injury-term matching.

Two independent consumers need the same word list and the same Turkish-safe
comparison, so both live here instead of being duplicated per module:
  - worker/pipeline.py                step_classify's deterministic
                                       injury -> critical trigger (CLAUDE.md S1)
  - worker/validation/validator.py    validate()'s cross-check between
                                       extraction's `injury` field and the raw text
"""

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


def _normalize_tr(text: str) -> str:
    """Turkish-safe lowercase.

    str.lower() applies the ASCII I -> i rule, so "YARALI".lower() ==
    "yarali" (dotless ı lost) and never matches "yaralı". Turkish has two
    I/i pairs (İ/i and I/ı); fix both by hand before lowercasing the rest.
    """
    return text.replace("I", "ı").replace("İ", "i").lower()
