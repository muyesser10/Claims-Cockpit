# eval/test_scoring.py
"""Tests for per-record scoring, including the archive-compatible shape."""

from eval.normalize import COMPARED_FIELDS
from eval.scoring import (
    FILLABLE_FIELDS,
    MISSING_METRIC_FIELDS,
    filled_names,
    from_dict,
    null_names,
    score_record,
    to_dict,
)

EXPECTED = {
    "channel": "email",
    "policy_no": "POL-2020-57052",
    "plate": "45 GAK 2046",
    "incident_date": "2026-07-11",
    "incident_location": {"city": "Bursa", "district": None},
    "damage_description": "bir ineğe çarpma",
    "damage_type": "animal",
    "injury": False,
    "counterparty_exists": False,
    "estimated_amount": 83397,
}

EXTRACTION = {
    "policy_no": "POL-2020-57052",
    "plate": "45GAK2046",
    "incident_date": "2026-07-11",
    "incident_location": {"city": "Bursa", "district": None},
    "damage_description": "bir ineğe çarptım",
    "damage_type": "animal",
    "injury": None,
    "counterparty_exists": None,
    "estimated_amount": 83397.0,
    "missing_fields": ["injury", "counterparty_exists"],
}


def score(expected=None, extraction=None, **kwargs):
    return score_record(
        "GT-000001",
        "email",
        expected or EXPECTED,
        extraction or EXTRACTION,
        **kwargs,
    )


def test_fillable_field_list_matches_the_extractor():
    """filled_fields is a metric denominator; it must not drift from extract()."""
    assert len(FILLABLE_FIELDS) == 10
    assert "incident_location.city" in FILLABLE_FIELDS
    assert "damage_description" in FILLABLE_FIELDS


def test_missing_metric_excludes_the_fields_it_cannot_judge():
    """The corpus never writes null for these two, so they are unmeasurable."""
    assert "injury" not in MISSING_METRIC_FIELDS
    assert "counterparty_exists" not in MISSING_METRIC_FIELDS
    assert len(MISSING_METRIC_FIELDS) == len(FILLABLE_FIELDS) - 2


def test_a_matching_record_scores_every_compared_field():
    """Loose plate spacing, int/float and null-means-false all resolve to hits."""
    result = score()
    assert result.hits == len(COMPARED_FIELDS) == 8
    assert all(value.hit for value in result.fields.values())


def test_a_wrong_value_is_the_only_miss():
    result = score(extraction={**EXTRACTION, "damage_type": "collision"})
    assert result.hits == 7
    assert not result.fields["damage_type"].hit
    assert result.fields["damage_type"].gt == "animal"
    assert result.fields["damage_type"].llm == "collision"


def test_damage_description_is_not_compared():
    """Free text needs cosine similarity (design doc 6.1), not equality."""
    result = score(extraction={**EXTRACTION, "damage_description": "tamamen alakasız"})
    assert result.hits == 8
    assert "damage_description" not in result.fields


def test_filled_fields_counts_what_the_model_answered():
    # 10 fillable, minus injury, counterparty_exists and district left null.
    assert filled_names(EXTRACTION) == [
        "policy_no",
        "plate",
        "incident_date",
        "damage_description",
        "damage_type",
        "estimated_amount",
        "incident_location.city",
    ]
    assert score().filled_fields == 7


def test_expected_missing_reads_the_answer_key_nulls():
    """Contract 3.1: a null in the ground truth is what 'missing' means."""
    assert null_names(EXPECTED) == ["incident_location.district"]
    assert score().expected_missing == ["incident_location.district"]


def test_model_missing_fields_are_carried_through_sorted():
    assert score().missing_fields == ["counterparty_exists", "injury"]


def test_unverified_fields_are_carried_through_sorted():
    result = score(unverified_fields=["plate", "damage_type"])
    assert result.unverified_fields == ["damage_type", "plate"]


def test_round_trip_through_the_serialised_form():
    original = score(unverified_fields=["plate"], duration_ms=4487, reasoning="kısa not")
    restored = from_dict(to_dict(original))
    assert restored == original


ARCHIVED = {
    "gt_id": "GT-000001",
    "channel": "email",
    "variant": "3-ornek",
    "fields": {
        "policy_no": {"gt": "POL-2020-57052", "llm": "POL-2020-57052", "hit": True},
        "damage_type": {"gt": "animal", "llm": "animal", "hit": True},
    },
    "hits": 8,
    "requests": 1,
    "duration_ms": 4487,
    "prompt_tokens": 3970,
    "completion_tokens": 300,
    "unverified_fields": [],
    "filled_fields": 6,
    "reasoning": "modelin muhakemesi",
}


def test_archived_run_can_be_read_back():
    """The 2026-08-02 runs must stay readable; they are the baseline."""
    restored = from_dict(ARCHIVED)
    assert restored.gt_id == "GT-000001"
    # hits follows from the fields present rather than the stored total: this
    # trimmed sample carries two of the eight.
    assert restored.hits == 2
    assert restored.filled_fields == 6
    assert restored.fields["damage_type"].hit
    # Fields the archive predates come back empty, not wrong.
    assert restored.missing_fields == []
    assert restored.expected_missing == []


def test_hit_is_recomputed_rather_than_trusted():
    """A stored hit that disagrees with its own values is corrected on read."""
    raw = {**ARCHIVED, "fields": {"damage_type": {"gt": "animal", "llm": "collision", "hit": True}}}
    restored = from_dict(raw)
    assert not restored.fields["damage_type"].hit
    assert restored.hits == 0
