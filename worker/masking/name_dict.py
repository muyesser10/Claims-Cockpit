# worker/masking/name_dict.py
"""Name-based PII masking using a Turkish first-name dictionary."""

# v0 starter set. Expanded to ~5K names and normalized (u->ü) in Sprint 2.
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
}


def mask_names(text: str, start_counter: int = 0) -> tuple[str, list[dict]]:
    """Mask dictionary names in text.

    start_counter continues numbering from a previous masking pass so
    placeholders stay unique across layers (e.g. [NAME_3] after regex).
    """
    mappings = []
    counter = start_counter
    words = text.split()
    result_words = []

    for word in words:
        stripped = word.strip(".,!?;:\"'()")
        if stripped.lower() in COMMON_NAMES:
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
