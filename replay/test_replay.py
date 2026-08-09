"""Tests for the replay script."""

import json

from replay.replay import (
    load_received_map,
    load_scenario,
    match_filter,
)


def test_load_received_map(tmp_path):
    """Builds a correct gt_id -> received_at map from enriched JSONL."""
    # Create a small enriched file in a temporary directory.
    enriched = tmp_path / "enriched.jsonl"
    records = [
        {"gt_id": "GT-000001", "received_at": "2026-07-20T10:00:00", "expected": {}},
        {"gt_id": "GT-000002", "received_at": "2026-07-21T14:00:00", "expected": {}},
    ]
    enriched.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    result = load_received_map(enriched)

    assert result == {
        "GT-000001": "2026-07-20T10:00:00",
        "GT-000002": "2026-07-21T14:00:00",
    }


def test_load_received_map_skips_blank_lines(tmp_path):
    """Blank lines in the file are ignored."""
    enriched = tmp_path / "enriched.jsonl"
    enriched.write_text(
        '{"gt_id": "GT-000001", "received_at": "2026-07-20T10:00:00"}\n\n',
        encoding="utf-8",
    )

    result = load_received_map(enriched)

    assert result == {"GT-000001": "2026-07-20T10:00:00"}


def test_match_filter_damage_type():
    """damage_type filter keeps only matching records."""
    hail = {"damage_type": "hail", "city": "İzmir"}
    collision = {"damage_type": "collision", "city": "İzmir"}
    assert match_filter(hail, {"damage_type": "hail"}) is True
    assert match_filter(collision, {"damage_type": "hail"}) is False


def test_match_filter_exclude_damage_type():
    """exclude_damage_type filter drops matching records."""
    hail = {"damage_type": "hail", "city": "İzmir"}
    collision = {"damage_type": "collision", "city": "İzmir"}
    assert match_filter(hail, {"exclude_damage_type": "hail"}) is False
    assert match_filter(collision, {"exclude_damage_type": "hail"}) is True


def test_match_filter_city_and_combined():
    """city filter and combined criteria both apply (AND logic)."""
    izmir_hail = {"damage_type": "hail", "city": "İzmir"}
    ankara_hail = {"damage_type": "hail", "city": "Ankara"}
    # City alone
    assert match_filter(izmir_hail, {"city": "İzmir"}) is True
    assert match_filter(ankara_hail, {"city": "İzmir"}) is False
    # Combined: both must match
    combined = {"damage_type": "hail", "city": "İzmir"}
    assert match_filter(izmir_hail, combined) is True
    assert match_filter(ankara_hail, combined) is False


def test_match_filter_empty_filter_matches_all():
    """An empty filter matches any record."""
    record = {"damage_type": "fire", "city": "Bursa"}
    assert match_filter(record, {}) is True


def test_load_scenario(tmp_path):
    """Loads a scenario YAML into a dict with phases."""
    scenario_file = tmp_path / "demo.yaml"
    scenario_file.write_text(
        "name: Test Senaryo\n"
        "phases:\n"
        "  - name: faz1\n"
        "    filter:\n"
        "      damage_type: hail\n"
        "    count: 5\n"
        "    interval_seconds: 2\n",
        encoding="utf-8",
    )
    scenario = load_scenario(scenario_file)
    assert scenario["name"] == "Test Senaryo"
    assert len(scenario["phases"]) == 1
    assert scenario["phases"][0]["filter"]["damage_type"] == "hail"
