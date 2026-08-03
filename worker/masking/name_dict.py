# worker/masking/name_dict.py
"""Name-based PII masking using a Turkish first-name dictionary."""

from worker.shared.text_norm import fold_tr_ascii

# v0 starter set, ASCII-only. Matching folds the source text to ASCII first
# (fold_tr_ascii) so "Hüseyin"/"Ömer" in the raw text still hit "huseyin"/
# "omer" here — see fold_tr_ascii's docstring for why the dictionary itself
# stays ASCII instead of also carrying accented forms. Expansion to ~5K names
# is a separate, not-yet-started piece of S2-5 (pending a standup decision on
# the source dataset).
COMMON_NAMES = {
    "ahmet",
    "mehmet",
    "mustafa",
    "ali",
    "huseyin",
    "hasan",
    "ibrahim",
    "ismail",
    "osman",
    "yusuf",
    "murat",
    "omer",
    "ramazan",
    "kadir",
    "suleyman",
    "abdullah",
    "yasar",
    "riza",
    "salih",
    "kemal",
    "sinan",
    "ayse",
    "fatma",
    "emine",
    "hatice",
    "zeynep",
    "elif",
    "meryem",
    "sultan",
    "hanife",
    "havva",
    "zehra",
    "esra",
    "busra",
    "seda",
    "merve",
    "ozlem",
    "derya",
    "aysel",
    "sevim",
    "nur",
    "gul",
    # A handful of Turkish-charactered test names (S2-5) — exercises
    # fold_tr_ascii end to end. Full 5K expansion is separate future work.
    "seyma",
    "cagri",
    "gokhan",
}


def mask_names(text: str, start_counter: int = 0) -> tuple[str, list[dict]]:
    """Mask dictionary names in text.

    Matching is accent-insensitive: each word is folded to ASCII
    (fold_tr_ascii) before comparing against COMMON_NAMES, so "Hüseyin"
    matches the dictionary's "huseyin". Only the comparison is folded — the
    placeholder replaces the word exactly as it appeared in the source
    (Turkish characters, casing and all), never the folded form.

    start_counter continues numbering from a previous masking pass so
    placeholders stay unique across layers (e.g. [NAME_3] after regex).
    """
    mappings = []
    counter = start_counter
    words = text.split()
    result_words = []

    for word in words:
        stripped = word.strip(".,!?;:\"'()")
        if fold_tr_ascii(stripped) in COMMON_NAMES:
            counter += 1
            placeholder = f"[NAME_{counter}]"
            mappings.append(
                {
                    "placeholder": placeholder,
                    "real_value": stripped,
                    "pii_type": "NAME",
                }
            )
            result_words.append(word.replace(stripped, placeholder))
        else:
            result_words.append(word)

    return " ".join(result_words), mappings
