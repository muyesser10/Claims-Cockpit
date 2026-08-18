# eval/test_gate.py
"""Tests for the auto-approval measurement.

Nothing here reaches the network: build_record's LLM calls go through a stub
client that answers both schemas. The gate's own rules are tested in
worker/routing/test_auto_approve.py; what is under test here is the measurement
built on top of them - that the run mirrors the pipeline, and that the numbers
mean what the report says they mean.
"""

from datetime import datetime

from eval.gate import (
    GateRecord,
    blocking_rule_names,
    build_record,
    candidate_sets,
    format_measurements,
    measure,
    read_run,
    run_live,
    sweep,
    write_run,
)
from eval.loader import EvalRecord
from worker.classification.schema import ClaimClassification
from worker.extraction.schema import ClaimExtraction
from worker.llm.client import LlmSettings
from worker.masking.sanity import SanityCheckResult

EXPECTED = {
    "channel": "email",
    "content_type": "claim",
    "urgency": "normal",
    "policy_no": "POL-2020-57052",
    "plate": "45 GAK 2046",
    "incident_date": None,
    "incident_location": {"city": None, "district": None},
    "damage_type": "animal",
    "injury": False,
    "counterparty_exists": False,
    "estimated_amount": None,
}

CORRECT_EXTRACTION = ClaimExtraction(
    reasoning="test",
    policy_no="POL-2020-57052",
    plate="[PLATE_1]",
    damage_type="animal",
    source_references={"plate": "[PLATE_1] plakalı"},
)

CLAIM_VERDICT = ClaimClassification(
    reasoning="test",
    content_type="claim",
    urgency="normal",
    injury_mentioned=False,
)


class StubClient:
    """Answers whichever schema it is asked for, and records the calls."""

    def __init__(self, *, verdict=None, extraction=None, sanity=None) -> None:
        self.settings = LlmSettings(api_key="not-used")
        self.verdict = verdict or CLAIM_VERDICT
        self.extraction = extraction or CORRECT_EXTRACTION
        # Clean by default. The real pass flags 148 of 150 claims, but a gate
        # test that inherited that would be testing the sanity layer; the one
        # test that cares sets it explicitly.
        self.sanity = sanity or SanityCheckResult(leak_found=False)
        self.calls: list[dict] = []

    def structured(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["response_model"] is SanityCheckResult:
            return self.sanity
        if kwargs["response_model"] is ClaimClassification:
            return self.verdict
        return self.extraction


def _record(gt_id: str = "GT-000001") -> EvalRecord:
    return EvalRecord(
        gt_id=gt_id,
        channel="email",
        text="45 GAK 2046 plakalı aracımla bir ineğe çarptım.",
        received_at=datetime(2026, 7, 25, 14, 0),
        expected=EXPECTED,
    )


def _gate_record(**kwargs) -> GateRecord:
    defaults = {
        "gt_id": "GT-000001",
        "channel": "email",
        "content_type": "claim",
        "urgency": "normal",
        "validation_flags": [],
        "unverified_fields": [],
        "extraction_present": True,
        "correct": True,
    }
    return GateRecord(**{**defaults, **kwargs})


def _flag(rule: str, field: str = "plate") -> dict:
    return {"field": field, "rule": rule, "message": "test"}


# --- the run mirrors the pipeline ----------------------------------------


def test_both_the_classifier_and_extraction_see_masked_text():
    client = StubClient()

    build_record(_record(), client=client)

    for call in client.calls:
        assert "45 GAK 2046" not in call["user_content"]
        assert "[PLATE_1]" in call["user_content"]


def test_the_extraction_is_unmasked_before_it_is_scored():
    """The answer key holds the real plate; the model answered [PLATE_1]."""
    client = StubClient()

    item = build_record(_record(), client=client)

    assert item.correct is True


def test_a_non_claim_skips_extraction_as_the_pipeline_does():
    """step_extract skips non-claims, so running extraction here would measure a
    call production never makes."""
    client = StubClient(
        verdict=ClaimClassification(
            reasoning="test", content_type="info_request", urgency="normal", injury_mentioned=False
        )
    )

    item = build_record(_record(), client=client)

    assert item.extraction_present is False
    assert item.content_type == "info_request"
    # Sanity and classification ran, as the pipeline runs them. Extraction is
    # the one that must not have - asserted by name rather than by counting, so
    # adding a step upstream cannot make this test fail for the wrong reason.
    assert "ClaimExtraction" not in [call["response_model"].__name__ for call in client.calls]


def test_the_answer_key_verdicts_are_carried_for_the_classification_report():
    item = build_record(_record(), client=StubClient())

    assert item.expected_content_type == "claim"
    assert item.expected_urgency == "normal"


def test_a_failing_record_is_recorded_and_the_run_continues():
    class Exploding(StubClient):
        def structured(self, **kwargs):
            if kwargs["message_id"] == "GT-000002":
                raise RuntimeError("upstream said no")
            return super().structured(**kwargs)

    outcome = run_live([_record("GT-000001"), _record("GT-000002")], client=Exploding())

    assert [item.gt_id for item in outcome.records] == ["GT-000001"]
    assert outcome.failures[0][0] == "GT-000002"


# --- what the numbers mean -----------------------------------------------


def test_a_clean_correct_record_is_approved_and_counted_right():
    result = measure([_gate_record()])

    assert result.approved == 1
    assert result.coverage == 1.0
    assert result.precision == 1.0


def test_an_approved_record_that_was_wrong_costs_precision():
    result = measure(
        [_gate_record(gt_id="GT-1", correct=True), _gate_record(gt_id="GT-2", correct=False)]
    )

    assert result.approved == 2
    assert result.precision == 0.5
    assert result.wrong_ids == ["GT-2"]


def test_precision_over_no_approvals_is_none_not_perfect():
    """A gate that approves nothing has not earned a perfect score, and
    reporting one would let a broken candidate win a sweep."""
    result = measure([_gate_record(urgency="critical")])

    assert result.approved == 0
    assert result.precision is None
    assert result.coverage == 0.0


def test_refusal_reasons_are_counted_so_the_bottleneck_is_visible():
    records = [
        _gate_record(gt_id="GT-1", urgency="critical"),
        _gate_record(gt_id="GT-2", urgency="critical"),
        _gate_record(gt_id="GT-3", validation_flags=[_flag("invalid_plate_format")]),
    ]

    result = measure(records)

    assert result.reasons["critical_urgency"] == 2
    assert result.reasons["blocking_validation_flags"] == 1


def test_the_environment_flag_does_not_decide_the_measurement(monkeypatch):
    """AUTO_APPROVE_ENABLED says whether the gate is switched on in production.
    It has nothing to say about what the gate would achieve."""
    monkeypatch.setenv("AUTO_APPROVE_ENABLED", "false")

    assert measure([_gate_record()]).approved == 1


# --- the sweep -----------------------------------------------------------


def test_moving_a_rule_to_advisory_changes_the_numbers():
    records = [_gate_record(validation_flags=[_flag("invalid_plate_format")])]

    results = sweep(
        records,
        {
            "strict": frozenset(),
            "plate-advisory": frozenset({"invalid_plate_format"}),
        },
    )

    assert results[0].approved == 0
    assert results[1].approved == 1


def test_rule_frequencies_say_which_candidates_are_worth_trying():
    """A rule that never fires cannot change coverage; moving it would be a
    decision about nothing."""
    records = [
        _gate_record(validation_flags=[_flag("invalid_policy_no_format", "policy_no")]),
        _gate_record(validation_flags=[_flag("invalid_policy_no_format", "policy_no")]),
        _gate_record(validation_flags=[_flag("future_incident_date", "incident_date")]),
    ]

    counts = blocking_rule_names(records)

    assert list(counts) == ["invalid_policy_no_format", "future_incident_date"]
    assert counts["invalid_policy_no_format"] == 2


def test_candidates_are_drawn_from_what_actually_fired():
    """A hardcoded list would measure someone's imagination rather than the
    corpus."""
    records = [
        _gate_record(validation_flags=[_flag("future_incident_date", "incident_date")]),
        _gate_record(validation_flags=[_flag("future_incident_date", "incident_date")]),
        _gate_record(validation_flags=[_flag("invalid_plate_format")]),
    ]

    candidates = candidate_sets(records)

    assert list(candidates)[:2] == ["strict", "shipped"]
    # Most frequent first, so the row that could buy the most coverage is the
    # one nearest the top.
    assert list(candidates)[2] == "shipped+future_incident_date"
    assert "future_incident_date" in candidates["shipped+future_incident_date"]


def test_a_rule_that_never_fired_is_not_offered_as_a_candidate():
    """Moving it between blocking and advisory cannot change a number."""
    candidates = candidate_sets([_gate_record()])

    assert list(candidates) == ["strict", "shipped"]


def test_one_rule_on_two_fields_counts_once_per_record():
    records = [
        _gate_record(
            validation_flags=[
                _flag("invalid_date_format", "incident_date"),
                _flag("invalid_date_format", "other"),
            ]
        )
    ]

    assert blocking_rule_names(records)["invalid_date_format"] == 1


# --- the artefact --------------------------------------------------------


def test_a_run_round_trips_through_a_file(tmp_path):
    """The sweep is free and the run is not, so the run is written out."""
    outcome = run_live([_record()], client=StubClient())

    path = write_run(outcome, tmp_path / "gate.json")

    assert read_run(path) == outcome.records


def test_the_report_puts_coverage_next_to_precision():
    text = format_measurements(sweep([_gate_record()], {"strict": frozenset()}))

    assert "coverage" in text
    assert "precision" in text
    assert "100.0%" in text


def test_the_report_says_n_a_rather_than_inventing_a_precision():
    text = format_measurements(sweep([_gate_record(urgency="critical")], {"strict": frozenset()}))

    assert "n/a" in text


# --- the masking sanity flag, which the gate treats as a fixed reject -------


def test_the_sanity_flag_is_measured_rather_than_assumed_away():
    """It used to be hardcoded False here while the real pass flags 148 of 150
    claims, so the coverage this module reported described almost no claim."""
    client = StubClient(sanity=SanityCheckResult(leak_found=True))

    outcome = run_live([_record()], client=client)

    assert outcome.records[0].has_sanity_flags is True


def test_a_flagged_record_is_rejected_and_ignore_sanity_shows_what_it_cost():
    """The counterfactual, kept separate and never reported as production.

    The record is otherwise approvable, so the difference between the two
    numbers is the sanity flag and nothing else.
    """
    records = [_gate_record(has_sanity_flags=True)]

    assert measure(records).approved == 0
    assert measure(records, ignore_sanity=True).approved == 1


def test_a_run_that_never_measured_sanity_reads_as_not_measured():
    """Older result files carry no value; None must not silently mean False in
    a way a reader cannot see."""
    records = run_live([_record()], client=StubClient(), measure_sanity=False).records

    assert records[0].has_sanity_flags is None
