# worker/shared/text_norm.py
"""Turkish-to-ASCII folding for accent-insensitive comparison.

Distinct from worker/shared/injury_terms.py's _normalize_tr: that one only
fixes the I/İ casing bug and KEEPS accents, because injury terms are matched
against accented Turkish text ("yaralı" is in the dictionary as written).
fold_tr_ascii goes further and drops every diacritic, for matching against
worker/masking/name_dict.py's COMMON_NAMES, which is ASCII-only — there is no
accented form to compare against, so the incoming text is folded down to
ASCII instead (S2-5).

For comparison only. Never use this on text you intend to keep or display —
it is lossy (ü/ö/ş/ç/ğ/ı all collapse into their ASCII letter) and there is
no way back.
"""

_TR_TO_ASCII = str.maketrans(
    {
        "ç": "c",
        "Ç": "c",
        "ğ": "g",
        "Ğ": "g",
        "ı": "i",
        "I": "i",
        "İ": "i",
        "ö": "o",
        "Ö": "o",
        "ş": "s",
        "Ş": "s",
        "ü": "u",
        "Ü": "u",
    }
)


def fold_tr_ascii(text: str) -> str:
    """Fold Turkish characters to ASCII for accent-insensitive matching.

    ü->u, ö->o, ş->s, ç->c, ğ->g, ı->i (and their uppercase forms), then
    lowercased. The translate pass runs first and handles İ/I by hand:
    "İ".lower() produces "i̇" (i + a combining dot, two characters) in
    Python, not plain "i", so leaving it to .lower() alone would silently
    break the comparison.
    """
    return text.translate(_TR_TO_ASCII).lower()
