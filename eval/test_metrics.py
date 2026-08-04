# eval/test_metrics.py
"""Tests for metric aggregation."""

from eval.metrics import REPEAT_DRIFT_FIELDS, Ratio, build_report, format_report
from eval.scoring import FieldScore, RecordScore


def make_score(gt_id="GT-1", channel="email", *, hits=8, **kwargs):
    """A record with `hits` of eight compared fields correct."""
    names = (
        "policy_no",
        "plate",
        "incident_date",
        "incident_location",
        "damage_type",
        "injury",
        "counterparty_exists",
        "estimated_amount",
    )
    fields = {
        name: FieldScore(gt="dogru", llm="dogru" if index < hits else "yanlis", hit=index < hits)
        for index, name in enumerate(names)
    }
    return RecordScore(
        gt_id=gt_id,
        channel=channel,
        fields=fields,
        hits=hits,
        filled_fields=kwargs.pop("filled_fields", 7),
        **kwargs,
    )


def test_ratio_reports_rate_and_counts():
    assert Ratio(795, 800).rate == 0.99375
    assert str(Ratio(795, 800)) == "99.38% (795/800)"


def test_ratio_of_nothing_is_zero_not_a_crash():
    assert Ratio(0, 0).rate == 0.0


def test_field_accuracy_totals_every_compared_field():
    report = build_report([make_score(hits=8), make_score(gt_id="GT-2", hits=7)])
    assert report.records == 2
    assert report.field_accuracy == Ratio(15, 16)


def test_noise_floor_is_the_measured_repeat_drift():
    report = build_report([make_score() for _ in range(100)])
    assert report.field_accuracy.total == 800
    assert report.noise_floor == REPEAT_DRIFT_FIELDS / 800


def test_per_channel_breakdown_splits_the_total():
    report = build_report(
        [
            make_score(gt_id="GT-1", channel="email", hits=8),
            make_score(gt_id="GT-2", channel="call_transcript", hits=6),
        ]
    )
    assert report.per_channel["email"] == Ratio(8, 8)
    assert report.per_channel["call_transcript"] == Ratio(6, 8)


def test_per_field_breakdown_finds_the_weak_field():
    """hits=7 leaves the last field wrong, which is what error analysis needs."""
    report = build_report([make_score(hits=7) for _ in range(4)])
    assert report.per_field["estimated_amount"] == Ratio(0, 4)
    assert report.per_field["policy_no"] == Ratio(4, 4)


def test_unsupported_rate_is_unverified_over_filled():
    scores = [
        make_score(gt_id="GT-1", unverified_fields=["plate"], filled_fields=7),
        make_score(gt_id="GT-2", unverified_fields=[], filled_fields=7),
    ]
    assert build_report(scores).unsupported == Ratio(1, 14)


def test_misses_carry_enough_to_analyse_them():
    (miss,) = build_report([make_score(hits=7)]).misses
    assert miss.gt_id == "GT-1"
    assert miss.field == "estimated_amount"
    assert miss.gt == "dogru"
    assert miss.llm == "yanlis"


def test_missing_field_detection_scores_precision_and_recall():
    scores = [
        make_score(
            gt_id="GT-1",
            missing_fields=["policy_no", "plate"],
            expected_missing=["policy_no"],
        ),
        make_score(
            gt_id="GT-2",
            missing_fields=[],
            expected_missing=["estimated_amount"],
        ),
    ]
    detection = build_report(scores).missing_detection
    assert detection.available
    assert (detection.true_positives, detection.false_positives) == (1, 1)
    assert detection.false_negatives == 1
    assert detection.precision == 0.5
    assert detection.recall == 0.5


def test_missing_field_detection_ignores_the_fields_it_cannot_judge():
    """A correct null on injury/counterparty must not count against precision."""
    scores = [
        make_score(
            gt_id="GT-1",
            missing_fields=["injury", "counterparty_exists", "policy_no"],
            expected_missing=["policy_no"],
        )
    ]
    detection = build_report(scores).missing_detection
    assert (detection.true_positives, detection.false_positives) == (1, 0)
    assert detection.precision == 1.0


def test_missing_field_detection_is_absent_not_zero_without_data():
    """The archived runs predate the field; reporting 0% would be a lie."""
    detection = build_report([make_score()]).missing_detection
    assert not detection.available
    assert "not available" in format_report(build_report([make_score()]))


def test_format_report_prints_the_numbers_and_their_targets():
    text = format_report(build_report([make_score(hits=7)]))
    assert "field accuracy     87.50% (7/8)   target >= 82%" in text
    assert "unsupported values" in text
    assert "noise floor" in text
    assert "per channel" in text
    assert "estimated_amount" in text


def test_format_report_truncates_a_long_miss_list():
    scores = [make_score(gt_id=f"GT-{index}", hits=0) for index in range(10)]
    text = format_report(build_report(scores), max_misses=5)
    assert "misses (80)" in text
    assert "... 75 more" in text
