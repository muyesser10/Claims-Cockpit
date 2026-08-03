# worker/masking/name_dict.py
"""Name-based PII masking using a Turkish first-name dictionary."""

from pathlib import Path

from worker.shared.text_norm import fold_tr_ascii

# data/dictionaries/turkish_names.txt is the masking-dictionary source of
# truth (Müyesser, PR #34, Faker tr_TR-derived, 1554 names). ANY future
# 'holdout'/eval-only name file must NEVER be folded into this one — Cagri's
# zero-overlap requirement for eval depends on the two staying disjoint;
# mixing them in would make eval circular (measuring masking recall against
# the very names the dictionary was built from).
_NAMES_FILE = Path(__file__).resolve().parents[2] / "data" / "dictionaries" / "turkish_names.txt"

# v0 starter set (Sprint 1), ASCII-only. Kept alongside the file above (not
# replaced by it) in case its vocabulary ever misses one of these.
_V0_NAMES = {
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
    # fold_tr_ascii end to end.
    "seyma",
    "cagri",
    "gokhan",
}

# Folded to ASCII on load, same as the comparison in mask_names() — so a line
# with Turkish characters (the file's actual format) still lands in the same
# ASCII vocabulary as _V0_NAMES.
_DICTIONARY_NAMES = {
    fold_tr_ascii(line.strip())
    for line in _NAMES_FILE.read_text(encoding="utf-8").splitlines()
    if line.strip()
}

COMMON_NAMES: set[str] = _V0_NAMES | _DICTIONARY_NAMES

# Names that collide with ordinary Turkish words (fold_tr_ascii'd form).
# mask_names() only masks these when a neighboring word is a known surname
# or a context marker appears nearby — see _looks_like_a_name(). Not
# exhaustive; ileride ekip tarafından genişletilecek, kapsamlı değil.
AMBIGUOUS_NAMES = {
    "deniz",
    "yagmur",
    "bahar",
    "gunes",
    "umut",
    "nur",
    "gul",
    "doga",
    "ozgur",
    "ece",
    "ipek",
    "baris",
    "deren",
    "ada",
    "ekin",
    "ceylin",
    "sema",
}

# GEÇİCİ/STUB — Müyesser'in araştırdığı resmi kaynak (TÜİK vb.) gelince
# genişletilecek, S2-5 fast-follow. Bu liste boş/küçük olsa bile ambiguous-
# isim kuralı bozulmaz, sadece soyisim-bitişikliği daha az tetiklenir.
SURNAMES = {
    "yilmaz",
    "kaya",
    "demir",
    "sahin",
    "celik",
    "yildiz",
    "yildirim",
    "ozturk",
    "aydin",
    "ozdemir",
    "arslan",
    "dogan",
    "kilic",
    "aslan",
    "cetin",
    "kara",
    "koc",
    "kurt",
    "polat",
    "korkmaz",
}


# How far back to look for a context marker before an ambiguous name, in words.
_CONTEXT_LOOKBACK = 4

# Checked as a substring of the folded, space-joined lookback window, so a
# two-word marker ("ad soyad") matches across word boundaries and a trailing
# punctuation mark on the last word (e.g. "Soyad:") never breaks the match.
_CONTEXT_MARKERS = ("sayin", "ad soyad", "adi soyadi", "imza", "saygilarimla")


def _strip_and_fold(word: str) -> str:
    return fold_tr_ascii(word.strip(".,!?;:\"'()"))


def _has_surname_neighbor(words: list[str], index: int) -> bool:
    """True if the word right before or right after `index` is a known surname."""
    for neighbor_index in (index - 1, index + 1):
        if 0 <= neighbor_index < len(words) and _strip_and_fold(words[neighbor_index]) in SURNAMES:
            return True
    return False


def _has_context_marker(words: list[str], index: int) -> bool:
    """True if a context marker (Sayın, İmza, Ad Soyad: ...) appears in the
    up-to-`_CONTEXT_LOOKBACK` words preceding `index`."""
    start = max(0, index - _CONTEXT_LOOKBACK)
    window = fold_tr_ascii(" ".join(words[start:index]))
    return any(marker in window for marker in _CONTEXT_MARKERS)


def _looks_like_a_name(words: list[str], index: int) -> bool:
    """Gate for AMBIGUOUS_NAMES: only mask when there's real evidence this
    occurrence is a name and not the everyday word it collides with."""
    return _has_surname_neighbor(words, index) or _has_context_marker(words, index)


def mask_names(text: str, start_counter: int = 0) -> tuple[str, list[dict]]:
    """Mask dictionary names in text.

    Matching is accent-insensitive: each word is folded to ASCII
    (fold_tr_ascii) before comparing against COMMON_NAMES, so "Hüseyin"
    matches the dictionary's "huseyin". Only the comparison is folded — the
    placeholder replaces the word exactly as it appeared in the source
    (Turkish characters, casing and all), never the folded form.

    A word in AMBIGUOUS_NAMES (collides with an everyday Turkish word, e.g.
    "Deniz"/deniz) is masked only when a neighboring word is a known surname
    or a context marker (Sayın, İmza, ...) appears nearby — see
    _looks_like_a_name(). Every other COMMON_NAMES entry is masked
    unconditionally, same as before.

    start_counter continues numbering from a previous masking pass so
    placeholders stay unique across layers (e.g. [NAME_3] after regex).
    """
    mappings = []
    counter = start_counter
    words = text.split()
    result_words = []

    for index, word in enumerate(words):
        stripped = word.strip(".,!?;:\"'()")
        folded = fold_tr_ascii(stripped)

        should_mask = folded in COMMON_NAMES and (
            folded not in AMBIGUOUS_NAMES or _looks_like_a_name(words, index)
        )

        if should_mask:
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
