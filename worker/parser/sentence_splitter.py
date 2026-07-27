"""
sentence_splitter.py — Turkish sentence boundary splitter.

Splits raw Turkish text into sentences. Naive "split on period" fails on
Turkish abbreviations (Sn., Dr., vb.), decimals (3.5), and ordinals (2.),
where a period does NOT end a sentence. This module protects those cases
before splitting, then restores them.

Used by the worker pipeline as a pre-processing step before masking.
"""

import re

# Turkish abbreviations where a period does NOT end a sentence.
ABBREVIATIONS = {
    "Sn",
    "Dr",
    "Prof",
    "Doç",
    "Av",
    "Sok",
    "Cad",
    "Mah",
    "Apt",
    "No",
    "Tel",
    "vb",
    "vs",
    "bkz",
    "örn",
    "yy",
    "TL",
    "km",
    "cm",
    "kg",
}

# Matches decimal numbers like 3.5 or 12.500 (period is not a sentence end).
DECIMAL_PATTERN = re.compile(r"\d+\.\d+")

# Matches sentence boundaries: . ! or ? followed by whitespace.
SENTENCE_END_PATTERN = re.compile(r"(?<=[.!?])\s+")


def split(text: str) -> list[str]:
    """Split Turkish text into a list of sentences.

    Protects decimals and abbreviations from being treated as sentence
    ends, splits on real boundaries, then restores the protected parts.
    """
    # 1. Protect decimals: replace "3.5" with a placeholder so the period
    #    inside it is not seen as a sentence boundary.
    decimals = DECIMAL_PATTERN.findall(text)
    for i, value in enumerate(decimals):
        text = text.replace(value, f"__DECIMAL_{i}__")

    # 2. Protect abbreviations: replace "Sn." with "Sn<DOT> " so the period
    #    after the abbreviation is not seen as a sentence boundary.
    for abbr in ABBREVIATIONS:
        text = re.sub(rf"\b{abbr}\.\s", f"{abbr}<DOT> ", text)

    # 3. Split on real sentence boundaries.
    sentences = SENTENCE_END_PATTERN.split(text)

    # 4. Restore the protected parts.
    restored = []
    for sentence in sentences:
        sentence = sentence.replace("<DOT>", ".")
        for i, value in enumerate(decimals):
            sentence = sentence.replace(f"__DECIMAL_{i}__", value)
        restored.append(sentence.strip())

    # 5. Drop empty sentences.
    return [s for s in restored if s]
