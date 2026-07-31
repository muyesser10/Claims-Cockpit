# worker/masking/unmask.py
"""Reverse masking: replace placeholders back with their real values.

Symmetric counterpart to mask_all() (worker/masking/pipeline.py). Extraction
output is a mix of flat fields, a nested dict (incident_location) and a flat
quote dict (source_references) — see worker/extraction/schema.py — so this
walks any dict shape rather than assuming one.
"""

from typing import Any


def unmask_data(data: dict, mappings: list[dict]) -> dict:
    """Replace placeholders in a dict's string values with their real values.

    Recurses into nested dicts. A string value may contain zero, one or
    several placeholders, embedded anywhere in the text; each one present in
    `mappings` is replaced, and any placeholder-looking text absent from
    `mappings` is left untouched rather than erroring. Does not mutate `data`.
    """
    lookup = {m["placeholder"]: m["real_value"] for m in mappings}
    return _unmask_value(data, lookup)


def _unmask_value(value: Any, lookup: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _unmask_value(val, lookup) for key, val in value.items()}
    if isinstance(value, str):
        for placeholder, real_value in lookup.items():
            value = value.replace(placeholder, real_value)
        return value
    return value
