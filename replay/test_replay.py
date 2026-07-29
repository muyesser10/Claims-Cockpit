"""Tests for the replay script."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from replay import load_received_map  # noqa: E402


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
