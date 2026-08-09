# eval/test_classification.py
"""Tests for the classification report.

Pure arithmetic over GateRecords - no model, no network. What is under test is
that the numbers are the ones §7 asks for, and that they stay honest about the
records they could not score.
"""

from eval.classification import build_report, build_reports, format_report
from eval.gate import GateRecord


def _record(expected: str, predicted: str, *, field_name: str = "content_type") -> GateRecord:
    values = {
        "content_type": "claim",
        "urgency": "normal",
        "expected_content_type": "claim",
        "expected_urgency": "normal",
    }
    if field_name == "content_type":
        values["expected_content_type"] = expected
        values["content_type"] = predicted
    else:
        values["expected_urgency"] = expected
        values["urgency"] = predicted

    return GateRecord(
        gt_id="GT-000001",
        channel="email",
        validation_flags=[],
        unverified_fields=[],
        extraction_present=True,
        correct=True,
        **values,
    )


def _urgency(expected: str, predicted: str) -> GateRecord:
    return _record(expected, predicted, field_name="urgency")


def test_a_perfect_run_scores_one():
    report = build_report(
        [_record("claim", "claim"), _record("irrelevant", "irrelevant")], "content_type"
    )

    assert report.macro_f1 == 1.0
    assert report.accuracy == 1.0


def test_support_and_prediction_counts_are_kept_apart():
    records = [_record("claim", "claim"), _record("info_request", "claim")]

    report = build_report(records, "content_type")
    by_label = {item.label: item for item in report.classes}

    assert by_label["claim"].support == 1
    assert by_label["claim"].predicted == 2
    assert by_label["info_request"].support == 1
    assert by_label["info_request"].predicted == 0


def test_a_class_the_model_never_produces_scores_zero_with_its_support_visible():
    """An F1 of zero over a support of 1 and the same over a support of 40 are
    different findings; the support column is what tells them apart."""
    records = [_record("claim", "claim"), _record("irrelevant", "claim")]

    report = build_report(records, "content_type")
    by_label = {item.label: item for item in report.classes}

    assert by_label["irrelevant"].f1 == 0.0
    assert by_label["irrelevant"].support == 1


def test_macro_weights_a_rare_class_as_heavily_as_a_common_one():
    """The reason §7 asks for macro. A system answering 'claim' to everything
    scores well on accuracy and badly here, which is the correct verdict."""
    records = [_record("claim", "claim") for _ in range(9)] + [_record("irrelevant", "claim")]

    report = build_report(records, "content_type")

    assert report.accuracy == 0.9
    assert report.macro_f1 < 0.5


def test_urgency_is_scored_from_its_own_pair_of_fields():
    records = [_urgency("critical", "critical"), _urgency("high", "normal")]

    report = build_report(records, "urgency")
    by_label = {item.label: item for item in report.classes}

    assert by_label["critical"].f1 == 1.0
    assert by_label["high"].recall == 0.0


def test_records_without_an_answer_key_are_reported_not_dropped():
    """A macro-F1 over 40 of 100 records is a different number from one over
    100, and nothing in the average says which it was."""
    records = [
        _record("claim", "claim"),
        GateRecord(
            gt_id="GT-2",
            channel="email",
            content_type="claim",
            urgency="normal",
            validation_flags=[],
            unverified_fields=[],
            extraction_present=True,
            correct=True,
        ),
    ]

    report = build_report(records, "content_type")

    assert report.scored == 1
    assert report.unscorable == 1


def test_disagreements_are_listed_so_the_number_is_actionable():
    records = [
        _record("info_request", "claim"),
        _record("info_request", "claim"),
        _record("irrelevant", "claim"),
    ]

    report = build_report(records, "content_type")

    assert list(report.confusions) == ["info_request -> claim", "irrelevant -> claim"]
    assert report.confusions["info_request -> claim"] == 2


def test_both_fields_are_reported():
    reports = build_reports([_record("claim", "claim")])

    assert [item.field_name for item in reports] == ["content_type", "urgency"]


def test_an_empty_run_does_not_divide_by_zero():
    report = build_report([], "content_type")

    assert report.macro_f1 == 0.0
    assert report.accuracy == 0.0


def test_the_table_carries_support_beside_every_score():
    text = format_report(build_report([_record("claim", "claim")], "content_type"))

    assert "support" in text
    assert "macro-F1" in text


def test_the_table_names_the_confusions():
    text = format_report(build_report([_record("info_request", "claim")], "content_type"))

    assert "info_request -> claim" in text
