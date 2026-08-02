# eval/test_normalize.py
"""Tests for the comparison conventions. These are the rules the numbers mean."""

from datetime import date

import pytest

from eval.normalize import COMPARED_FIELDS, compare, normalize_amount, normalize_field


def test_the_field_set_is_the_baseline_denominator():
    """800 = 100 records x 8 fields. A ninth field silently changes every number."""
    assert len(COMPARED_FIELDS) == 8
    assert "damage_description" not in COMPARED_FIELDS


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        ("POL-2020-57052", " pol-2020-57052 "),
        ("POL-2020-57052", "POL-2020-57052"),
    ],
)
def test_policy_no_ignores_case_and_padding(expected, actual):
    assert compare("policy_no", expected, actual)


def test_policy_no_still_catches_a_wrong_number():
    assert not compare("policy_no", "POL-2020-57052", "POL-2020-57053")


def test_plate_ignores_spacing():
    assert compare("plate", "45 GAK 2046", "45GAK2046")


def test_plate_keeps_a_mask_placeholder_intact():
    assert compare("plate", "[PLATE_1]", "[PLATE_1]")
    assert not compare("plate", "[PLATE_1]", "[PLATE_2]")


def test_date_accepts_both_a_date_object_and_an_iso_string():
    assert compare("incident_date", "2026-07-11", date(2026, 7, 11))


def test_unparseable_date_misses_instead_of_raising():
    assert not compare("incident_date", "2026-07-11", "11 Temmuz")


def test_amount_compares_int_and_float_equal():
    assert compare("estimated_amount", 83397, 83397.0)


@pytest.mark.parametrize(
    ("written", "value"),
    [("12.500,75 TL", 12500.75), ("1.250", 1250.0), ("83397 TL civarında", 83397.0)],
)
def test_amount_reads_the_turkish_written_form(written, value):
    assert normalize_amount(written) == value


def test_location_compares_both_halves():
    izmir = {"city": "İzmir", "district": "Bornova"}
    assert compare("incident_location", izmir, {"city": "İzmir", "district": "Bornova"})
    assert not compare("incident_location", izmir, {"city": "İzmir", "district": "Konak"})
    assert not compare("incident_location", izmir, {"city": "İzmir", "district": None})


def test_location_strips_a_turkish_case_suffix():
    assert compare("incident_location", {"city": "İzmir"}, {"city": "İzmir'de"})


def test_turkish_uppercase_i_folds_correctly():
    """str.lower() would turn 'İZMİR' into 'i̇zmi̇r' and miss."""
    assert compare("incident_location", {"city": "İzmir"}, {"city": "İZMİR"})


def test_empty_string_counts_as_null():
    assert compare("policy_no", None, "")


@pytest.mark.parametrize("field", ["injury", "counterparty_exists"])
def test_silence_counts_as_false(field):
    """GT writes False where the text says nothing and the model answers null."""
    assert compare(field, False, None)
    assert normalize_field(field, None) is False


@pytest.mark.parametrize("field", ["injury", "counterparty_exists"])
def test_a_real_disagreement_still_misses(field):
    assert not compare(field, False, True)
    assert compare(field, True, True)
