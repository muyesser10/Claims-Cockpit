# worker/masking/pipeline.py
"""Combined masking: regex PII first, then dictionary names."""

from worker.masking.name_dict import mask_names
from worker.masking.regex_rules import mask_text


def mask_all(text: str) -> tuple[str, list[dict]]:
    """Apply regex masking then name masking.

    Returns (masked_text, all_mappings).
    """
    all_mappings = []

    # 1. Regex PII (TC, phone, plate, IBAN).
    text, regex_mappings = mask_text(text)
    all_mappings.extend(regex_mappings)

    # 2. Dictionary names, numbered after any existing NAME placeholders.
    name_start = sum(1 for m in all_mappings if m["pii_type"] == "NAME")
    text, name_mappings = mask_names(text, start_counter=name_start)
    all_mappings.extend(name_mappings)

    return text, all_mappings
