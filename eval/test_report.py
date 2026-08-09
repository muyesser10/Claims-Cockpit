# eval/test_report.py
"""Tests for the §7 quality table.

Everything here builds its own inputs under tmp_path. eval/results/ is
gitignored, so a test that read the real runs would pass on the laptop that
produced them and fail everywhere else - including CI.
"""

import json
from pathlib import Path

from eval.report import (
    Metric,
    Sample,
    binomial_lower_bound,
    build,
    critical_recall_metric,
    format_report,
    manual_metrics,
    masking_recall_metric,
)

SAMPLE = Sample(n=1, unit="ihbar", description="test")


def metric(**kwargs) -> Metric:
    defaults = {
        "key": "k",
        "label": "L",
        "value": 0.5,
        "unit": "ratio",
        "target": 0.5,
        "target_operator": "gte",
        "sample": SAMPLE,
    }
    return Metric(**{**defaults, **kwargs})


# --- status ---------------------------------------------------------------


def test_a_value_on_the_target_passes_rather_than_failing_by_a_rounding_error():
    assert metric(value=0.95, target=0.95, target_operator="gte").status == "pass"
    assert metric(value=0.07, target=0.07, target_operator="lte").status == "pass"


def test_a_value_the_wrong_side_of_the_target_fails():
    assert metric(value=0.822, target=0.97, target_operator="gte").status == "fail"
    assert metric(value=0.09, target=0.07, target_operator="lte").status == "fail"


def test_an_unmeasured_metric_is_not_a_failure():
    """A metric nobody has measured says nothing, and must not read as a miss."""
    assert metric(value=None).status == "unmeasured"


# --- confidence bound -----------------------------------------------------


def test_the_bound_matches_the_published_clopper_pearson_value():
    # 68/70 is the post-#62 gate run. The one-sided 95% lower bound is 91.3%,
    # which is the number that says the >= 95% target is measured but not shown.
    assert round(binomial_lower_bound(68, 70), 3) == 0.913


def test_a_perfect_run_still_does_not_reach_certainty():
    """41 approvals with nothing wrong is not evidence of a 100% gate."""
    bound = binomial_lower_bound(41, 41)
    assert 0.9 < bound < 1.0


def test_the_bound_never_exceeds_the_point_estimate():
    for hits, total in ((1, 2), (9, 10), (68, 70), (250, 260)):
        assert binomial_lower_bound(hits, total) <= hits / total


def test_a_bound_over_nothing_is_none_rather_than_zero():
    assert binomial_lower_bound(0, 0) is None
    assert binomial_lower_bound(5, 3) is None


# --- critical recall ------------------------------------------------------


def _injury_rows() -> list[dict]:
    return [
        {"id": "A", "group": "non_canonical", "injury": True, "signals": [], "critical": True},
        {"id": "B", "group": "non_canonical", "injury": True, "signals": [], "critical": False},
        {"id": "C", "group": "ascii_fold", "injury": True, "signals": ["yarali"], "critical": True},
        {
            "id": "D",
            "group": "false_positive_control",
            "injury": False,
            "signals": [],
            "critical": True,
        },
    ]


def test_the_headline_is_the_hard_fixture_not_the_corpus_hundred(tmp_path: Path):
    """The corpus number is a template score; putting it up front would mislead."""
    path = tmp_path / "injury.json"
    path.write_text(json.dumps(_injury_rows()), encoding="utf-8")

    result = critical_recall_metric(path)

    assert result.numerator == 2
    assert result.denominator == 3
    assert result.status == "fail"
    # The corpus 100% is still reported, but as one row among several.
    assert any(item.value == 1.0 for item in result.breakdown)


def test_the_control_group_is_kept_out_of_recall_but_named_in_the_notes(tmp_path: Path):
    path = tmp_path / "injury.json"
    path.write_text(json.dumps(_injury_rows()), encoding="utf-8")

    result = critical_recall_metric(path)

    assert result.denominator == 3, "the injury=False control is not a recall case"
    assert any("kontrol" in note for note in result.notes)


def test_an_outcomes_file_is_read_whether_or_not_it_carries_meta(tmp_path: Path):
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps(_injury_rows()), encoding="utf-8")
    wrapped = tmp_path / "wrapped.json"
    wrapped.write_text(
        json.dumps({"meta": {"run_at": "2026-08-07T10:00:00+00:00"}, "outcomes": _injury_rows()}),
        encoding="utf-8",
    )

    assert critical_recall_metric(bare).value == critical_recall_metric(wrapped).value
    assert critical_recall_metric(wrapped).source.measured_at == "2026-08-07"


# --- masking --------------------------------------------------------------


def _masking_summary() -> dict:
    return {
        "pinned": False,
        "records_scanned": 1000,
        "groups": {
            "regex": {"label": "regex", "masked": 1846, "present": 1847, "recall": 0.9995},
            "names_faker": {"label": "faker", "masked": 1272, "present": 1274, "recall": 0.9984},
            "names_holdout": {"label": "holdout", "masked": 27, "present": 704, "recall": 0.0384},
            "deterministic": {"label": "all", "masked": 3145, "present": 3825, "recall": 0.8222},
        },
    }


def test_masking_reports_the_deterministic_layer_as_seven_scopes_it(tmp_path: Path):
    path = tmp_path / "masking.json"
    path.write_text(json.dumps(_masking_summary()), encoding="utf-8")

    result = masking_recall_metric(path)

    assert result.numerator == 3145
    assert result.status == "fail"


def test_the_holdout_number_survives_into_the_breakdown(tmp_path: Path):
    """The 99.9% regex layer would otherwise hide the layer that scores 3.8%."""
    path = tmp_path / "masking.json"
    path.write_text(json.dumps(_masking_summary()), encoding="utf-8")

    values = [item.value for item in masking_recall_metric(path).breakdown]

    assert 0.0384 in values


# --- manual inputs --------------------------------------------------------


def test_a_missing_manual_file_leaves_p95_unmeasured_rather_than_zero():
    """An absent measurement must never render as a latency of zero seconds."""
    (result,) = manual_metrics({})

    assert result.value is None
    assert result.status == "unmeasured"


def test_p95_carries_the_note_that_it_did_not_come_from_an_eval_run():
    (result,) = manual_metrics(
        {"p95_latency": {"value_seconds": 10.95, "sample_n": 43, "measured_at": "2026-08-09"}}
    )

    assert result.status == "pass"
    assert any("denetim izinden" in note for note in result.notes)


# --- the whole table ------------------------------------------------------


def _write_inputs(tmp_path: Path) -> dict[str, Path]:
    extraction = tmp_path / "extraction.json"
    extraction.write_text(
        json.dumps(
            {
                "meta": {"run_at": "2026-08-08T13:50:40+00:00", "model": "test-model"},
                "records": [
                    {
                        "gt_id": "GT-1",
                        "channel": "email",
                        "fields": {"plate": {"gt": "34 A 1", "llm": "34 A 1", "hit": True}},
                        "hits": 1,
                        "filled_fields": 1,
                        "unverified_fields": [],
                        "missing_fields": [],
                        "expected_missing": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    gate_run = tmp_path / "gate.json"
    gate_run.write_text(
        json.dumps(
            {
                "meta": {"run_at": "2026-08-09T06:43:04+00:00", "model": "test-model"},
                "records": [
                    {
                        "gt_id": "GT-1",
                        "channel": "email",
                        "content_type": "claim",
                        "urgency": "normal",
                        "validation_flags": [],
                        "unverified_fields": [],
                        "extraction_present": True,
                        "correct": True,
                        "expected_content_type": "claim",
                        "expected_urgency": "normal",
                        "hits": 1,
                        "scored_fields": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    injury = tmp_path / "injury.json"
    injury.write_text(json.dumps(_injury_rows()), encoding="utf-8")

    masking = tmp_path / "masking.json"
    masking.write_text(json.dumps(_masking_summary()), encoding="utf-8")

    manual = tmp_path / "manual.json"
    manual.write_text(
        json.dumps({"p95_latency": {"value_seconds": 10.95, "sample_n": 43}}), encoding="utf-8"
    )

    return {
        "extraction": extraction,
        "gate_run": gate_run,
        "injury": injury,
        "masking": masking,
        "manual": manual,
    }


def test_the_table_has_a_row_for_every_one_of_the_eight_targets(tmp_path: Path):
    payload = build(**_write_inputs(tmp_path))

    assert [row["key"] for row in payload["metrics"]] == [
        "field_accuracy",
        "hallucination_rate",
        "classification_f1",
        "auto_approve_precision",
        "critical_recall",
        "masking_recall",
        "p95_latency",
        "rag_accuracy",
    ]


def test_the_summary_counts_add_up_to_the_rows_it_summarises(tmp_path: Path):
    payload = build(**_write_inputs(tmp_path))
    summary = payload["summary"]

    assert summary["pass"] + summary["fail"] + summary["unmeasured"] == summary["total"]
    assert summary["total"] == len(payload["metrics"])


def test_rag_stays_in_the_table_while_it_is_unmeasured(tmp_path: Path):
    """Dropping the row would turn an unmeasured target into an invisible one."""
    payload = build(**_write_inputs(tmp_path))

    (rag,) = [row for row in payload["metrics"] if row["key"] == "rag_accuracy"]
    assert rag["value"] is None
    assert rag["status"] == "unmeasured"


def test_every_measured_row_says_where_and_when_it_came_from(tmp_path: Path):
    """A number on the screen that nobody can trace is not a measurement."""
    payload = build(**_write_inputs(tmp_path))

    for row in payload["metrics"]:
        if row["status"] == "unmeasured":
            continue
        assert row["source"] is not None, row["key"]
        assert row["source"]["run"], row["key"]
        assert row["sample"]["n"] is not None, row["key"]


def test_the_text_rendering_survives_a_console_that_cannot_encode_maths_signs(tmp_path: Path):
    """cp1254 is the Windows default here and cannot encode the >= sign."""
    text = format_report(build(**_write_inputs(tmp_path)))

    text.encode("cp1254")
