# worker/masking/test_unmask.py
"""Tests for unmasking (reverse of mask_all)."""

from worker.masking.pipeline import mask_all
from worker.masking.unmask import unmask_data

MAPPINGS = [
    {"placeholder": "[PLATE_1]", "real_value": "34ABC12", "pii_type": "PLATE"},
    {"placeholder": "[NAME_1]", "real_value": "Ahmet", "pii_type": "NAME"},
    {"placeholder": "[TC_1]", "real_value": "12345678901", "pii_type": "TC"},
]


def test_flat_field_exact_match():
    """A field that is exactly one placeholder is replaced with the real value."""
    result = unmask_data({"plate": "[PLATE_1]"}, MAPPINGS)
    assert result == {"plate": "34ABC12"}


def test_embedded_placeholder():
    """A placeholder embedded inside a longer string is replaced in place."""
    result = unmask_data({"damage_description": "arac [PLATE_1] hasarli"}, MAPPINGS)
    assert result == {"damage_description": "arac 34ABC12 hasarli"}


def test_nested_dict():
    """Nested dicts (e.g. incident_location) are recursed into."""
    result = unmask_data({"incident_location": {"city": "[NAME_1]", "district": None}}, MAPPINGS)
    assert result == {"incident_location": {"city": "Ahmet", "district": None}}


def test_multiple_placeholders_in_one_string():
    """Several distinct placeholders in the same string are all replaced."""
    result = unmask_data(
        {"reasoning": "[NAME_1], TC [TC_1], plaka [PLATE_1]"},
        MAPPINGS,
    )
    assert result == {"reasoning": "Ahmet, TC 12345678901, plaka 34ABC12"}


def test_same_placeholder_in_multiple_fields():
    """The same placeholder is replaced everywhere it occurs, not just once."""
    result = unmask_data(
        {"plate": "[PLATE_1]", "source_references": {"plate": "plakasi [PLATE_1] olan arac"}},
        MAPPINGS,
    )
    assert result == {
        "plate": "34ABC12",
        "source_references": {"plate": "plakasi 34ABC12 olan arac"},
    }


def test_unknown_placeholder_left_untouched():
    """A placeholder-shaped string absent from mappings is not touched or errored."""
    result = unmask_data({"plate": "[PLATE_9]"}, MAPPINGS)
    assert result == {"plate": "[PLATE_9]"}


def test_non_string_values_pass_through():
    """int/bool/float/None values are returned unchanged."""
    data = {
        "injury": True,
        "estimated_amount": 5000.0,
        "counterparty_exists": False,
        "district": None,
    }
    assert unmask_data(data, MAPPINGS) == data


def test_does_not_mutate_input():
    """The input dict (and nested dicts) are not modified in place."""
    data = {"plate": "[PLATE_1]", "incident_location": {"city": "[NAME_1]"}}
    original = {"plate": "[PLATE_1]", "incident_location": {"city": "[NAME_1]"}}
    unmask_data(data, MAPPINGS)
    assert data == original


def test_empty_mappings_returns_data_unchanged():
    """No mappings at all: strings pass through untouched."""
    data = {"plate": "[PLATE_1]", "note": "plain text"}
    assert unmask_data(data, []) == data


def test_round_trip_with_mask_all():
    """mask_all() then unmask_data() reconstructs the original text."""
    text = "Plaka 06ABC34 ile TC 12345678901 kimlikli Ahmet kaza yapti"
    masked, mappings = mask_all(text)

    result = unmask_data({"damage_description": masked}, mappings)

    assert result["damage_description"] == text
