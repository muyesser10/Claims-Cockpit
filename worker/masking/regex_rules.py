# worker/masking/regex_rules.py
import re

# Turkey-specific PII patterns.
PATTERNS = {
    "TC": re.compile(r"\b[1-9][0-9]{10}\b"),
    "PHONE": re.compile(r"\b(0?5\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2})\b"),
    # Plate: 2-digit province + 1-3 letters + 2-4 digits (standard TR format)
    "PLATE": re.compile(r"\b(\d{2}\s?[A-ZÇĞİÖŞÜ]{1,3}\s?\d{1,4})\b"),
    "IBAN": re.compile(r"\bTR\d{24}\b"),
}


def mask_text(text: str) -> tuple[str, list[dict]]:
    """Mask PII in text.
    Returns (masked_text, mappings) where mappings is a list of
    {"placeholder": "[TC_1]", "real_value": "...", "pii_type": "TC"}.
    """
    mappings = []
    counters = {pii_type: 0 for pii_type in PATTERNS}
    masked = text

    for pii_type, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            real = match.group(0)
            existing = next((m for m in mappings if m["real_value"] == real), None)
            if existing:
                placeholder = existing["placeholder"]
            else:
                counters[pii_type] += 1
                placeholder = f"[{pii_type}_{counters[pii_type]}]"
                mappings.append(
                    {"placeholder": placeholder, "real_value": real, "pii_type": pii_type}
                )
            masked = masked.replace(real, placeholder)

    return masked, mappings
