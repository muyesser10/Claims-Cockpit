# demo/test_seed_demo_db.py
"""The one part of the seeding script worth a test: the DEMO_OFFLINE guard.

The rest of seed_demo_db.py is HTTP and polling against a running stack, which
a unit test can only re-implement. This is the piece that protects something -
running it with DEMO_OFFLINE off spends three live OpenAI calls per message.
"""

import json

import pytest
import typer

from demo.seed_demo_db import load_first, seed


def test_seeding_refuses_to_run_online(monkeypatch, tmp_path):
    monkeypatch.delenv("DEMO_OFFLINE", raising=False)

    with pytest.raises(typer.BadParameter) as exc:
        seed(texts=tmp_path / "unused.jsonl", enriched=tmp_path / "unused.jsonl")

    message = str(exc.value)
    assert "DEMO_OFFLINE" in message
    # The number has to be in the message: "costs money" is ignorable, "180
    # calls" is not.
    assert "180" in message


def test_the_guard_runs_before_anything_is_read(monkeypatch, tmp_path):
    """No files are touched and no request goes out before the check."""
    monkeypatch.setenv("DEMO_OFFLINE", "false")

    with pytest.raises(typer.BadParameter):
        seed(texts=tmp_path / "does-not-exist.jsonl", enriched=tmp_path / "neither.jsonl")


def test_load_first_stops_at_the_limit_and_pairs_received_at(tmp_path):
    texts = tmp_path / "texts.jsonl"
    enriched = tmp_path / "enriched.jsonl"
    texts.write_text(
        "\n".join(
            json.dumps({"gt_id": f"GT-{i:06d}", "channel": "email", "text": f"metin {i}"})
            for i in range(5)
        ),
        encoding="utf-8",
    )
    enriched.write_text(
        "\n".join(
            json.dumps({"gt_id": f"GT-{i:06d}", "received_at": f"2026-07-0{i + 1}T12:00:00"})
            for i in range(5)
        ),
        encoding="utf-8",
    )

    records = load_first(texts, enriched, limit=3)

    assert len(records) == 3
    assert records[0]["external_ref"] == "GT-000000"
    # Without received_at the pipeline cannot resolve "dün" - a missing one
    # silently changes what gets extracted.
    assert records[0]["received_at"] == "2026-07-01T12:00:00"
    assert records[0]["raw_text"] == "metin 0"
