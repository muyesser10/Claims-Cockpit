"""Tests for the ground truth generator."""

import json
import random

from data.gt_generator import build_one, fake


def _seed_all(value: int) -> None:
    """Seed both Python's random and Faker's RNG for reproducibility."""
    random.seed(value)
    fake.seed_instance(value)


def test_reproducible_with_seed():
    """Same seed produces identical records."""
    _seed_all(42)
    first = [build_one(i) for i in range(5)]
    _seed_all(42)
    second = [build_one(i) for i in range(5)]
    assert first == second


def test_no_personal_leak_into_expected():
    """Personal data (name, phone, tc) must never appear in 'expected'."""
    _seed_all(42)
    for i in range(50):
        record = build_one(i)
        expected_str = json.dumps(record["expected"], ensure_ascii=False)
        for key, value in record["_personal"].items():
            assert str(value) not in expected_str, f"Leak in {record['gt_id']}: {key}={value}"


def test_expected_has_all_schema_fields():
    """Every record's 'expected' block matches claim.json fields."""
    _seed_all(42)
    required = {
        "channel",
        "content_type",
        "urgency",
        "policy_no",
        "plate",
        "incident_date",
        "incident_location",
        "damage_description",
        "damage_type",
        "injury",
        "counterparty_exists",
        "estimated_amount",
    }
    record = build_one(0)
    assert set(record["expected"].keys()) == required


def test_injury_forces_critical():
    """If injury is true, urgency must be critical."""
    _seed_all(42)
    for i in range(100):
        record = build_one(i)
        if record["expected"]["injury"]:
            assert record["expected"]["urgency"] == "critical"
