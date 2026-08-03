# eval/test_regression.py
"""Pins the scoring pipeline against a slice of the 2026-08-02 baseline run.

eval/fixtures/baseline_20.json holds 20 records trimmed out of
olcum-arsivi/baseline_100_results_v3.json — the model's real answers, in the
shape that run wrote them. Re-scoring them here is what keeps a change to
normalize.py, scoring.py or metrics.py from moving the numbers by accident:
design doc 6.3 wants a run that drops accuracy to turn CI red.

Two things this file is NOT:

  - a baseline claim. The slice deliberately contains all five misses from the
    hundred, so it scores 96.88% where the full run scored 99.38%. The number
    here is a fingerprint, not a result.
  - a test of normalize.py. The archived run stored values that had already been
    normalized (injury and counterparty_exists arrive as bool, never null), so
    the normalization rules never fire on this data. They have their own tests
    in test_normalize.py.
"""

import json
from pathlib import Path

from eval.metrics import build_report
from eval.runner import read_results

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "baseline_20.json"


def report():
    return build_report(read_results(FIXTURE))


def test_the_fixture_is_still_archive_shaped():
    """A bare JSON list, the way the measurement scripts wrote it."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    assert len(raw) == 20
    assert set(raw[0]) == {
        "gt_id",
        "channel",
        "fields",
        "hits",
        "filled_fields",
        "unverified_fields",
    }


def test_field_accuracy_is_unchanged():
    assert report().field_accuracy.hits == 155
    assert report().field_accuracy.total == 160


def test_unsupported_value_rate_is_unchanged():
    """27/684 over the full run; 4/139 over this slice."""
    result = report().unsupported
    assert (result.hits, result.total) == (4, 139)


def test_channel_breakdown_is_unchanged():
    per_channel = report().per_channel
    assert (per_channel["email"].hits, per_channel["email"].total) == (61, 64)
    assert (per_channel["call_transcript"].hits, per_channel["call_transcript"].total) == (47, 48)
    assert (per_channel["web_form"].hits, per_channel["web_form"].total) == (47, 48)


def test_the_known_misses_are_exactly_the_data_caused_ones():
    """All five trace back to the corpus, not to the model.

    Three collision records carry counterparty_exists=False (53 of 139 in the
    corpus do), and two never say how the accident happened. Reported to
    @muyesser10; recorded here so a future change to these numbers is read as a
    change in scoring, not as the model improving.
    """
    misses = {(miss.gt_id, miss.field) for miss in report().misses}
    assert misses == {
        ("GT-000201", "counterparty_exists"),
        ("GT-000268", "counterparty_exists"),
        ("GT-000384", "counterparty_exists"),
        ("GT-000774", "damage_type"),
        ("GT-000965", "damage_type"),
    }


def test_missing_field_detection_is_reported_as_absent():
    """The archived run predates the field. Absent must not read as 0%."""
    assert not report().missing_detection.available
