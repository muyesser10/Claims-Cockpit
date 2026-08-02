# eval/test_runner.py
"""Tests for the run/re-score split. Nothing here touches the network."""

import json
from datetime import datetime

from eval.loader import EvalRecord
from eval.runner import RunOutcome, read_results, read_results_meta, run_live, write_results
from eval.scoring import score_record
from worker.extraction.schema import ClaimExtraction
from worker.llm.client import LlmSettings, ModelTier

ANSWER = ClaimExtraction(
    reasoning="11 Temmuz açık tarih.",
    policy_no="POL-2020-57052",
    plate="45 GAK 2046",
    damage_type="animal",
    source_references={"plate": "45 GAK 2046 plakalı"},
)

EXPECTED = {
    "channel": "email",
    "policy_no": "POL-2020-57052",
    "plate": "45 GAK 2046",
    "incident_date": None,
    "incident_location": {"city": None, "district": None},
    "damage_type": "animal",
    "injury": False,
    "counterparty_exists": False,
    "estimated_amount": None,
}


class StubClient:
    """Stands in for LlmClient, and can be told to fail for a given record."""

    def __init__(self, failing: set[str] | None = None) -> None:
        self.settings = LlmSettings(api_key="not-used")
        self.failing = failing or set()
        self.calls: list[dict] = []

    def structured(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["message_id"] in self.failing:
            raise RuntimeError("upstream said no")
        return ANSWER


def records(count=3):
    return [
        EvalRecord(
            gt_id=f"GT-{index:06d}",
            channel="email",
            text="45 GAK 2046 plakalı aracımla bir ineğe çarptım.",
            received_at=datetime(2026, 7, 25, 14, 0),
            expected=EXPECTED,
        )
        for index in range(count)
    ]


def test_every_record_is_scored_with_a_single_shared_client():
    """One client for the whole run; a fresh one per record would be waste."""
    client = StubClient()
    outcome = run_live(records(3), client=client)
    assert len(outcome.scores) == 3
    assert len(client.calls) == 3
    assert outcome.failures == []
    assert outcome.model == "gpt-4o-mini"


def test_a_failing_record_is_recorded_and_the_run_continues():
    """A run that quietly scored 2 of 3 and reported an average would lie."""
    outcome = run_live(records(3), client=StubClient(failing={"GT-000001"}))
    assert [score.gt_id for score in outcome.scores] == ["GT-000000", "GT-000002"]
    assert len(outcome.failures) == 1
    gt_id, error = outcome.failures[0]
    assert gt_id == "GT-000001"
    assert "upstream said no" in error


def test_seed_tier_and_prompt_reach_the_client():
    client = StubClient()
    run_live(records(1), seed=42, tier=ModelTier.STRONG, system_prompt="özel", client=client)
    (call,) = client.calls
    assert call["seed"] == 42
    assert call["tier"] is ModelTier.STRONG
    assert call["system_prompt"] == "özel"


def test_progress_callback_sees_every_record():
    seen = []
    run_live(records(2), client=StubClient(), on_progress=lambda i, t, gt: seen.append((i, t, gt)))
    assert seen == [(1, 2, "GT-000000"), (2, 2, "GT-000001")]


def test_results_round_trip_through_a_file(tmp_path):
    outcome = run_live(records(2), client=StubClient())
    path = write_results(outcome, tmp_path / "run.json", meta={"seed": 42})
    assert read_results(path) == outcome.scores


def test_written_results_carry_the_settings_that_produced_them(tmp_path):
    outcome = run_live(records(1), client=StubClient())
    meta = read_results_meta(write_results(outcome, tmp_path / "run.json", meta={"seed": 42}))
    assert meta["model"] == "gpt-4o-mini"
    assert meta["seed"] == 42
    assert meta["records"] == 1
    assert "run_at" in meta


def test_failures_are_written_into_the_results_file(tmp_path):
    outcome = run_live(records(2), client=StubClient(failing={"GT-000000"}))
    meta = read_results_meta(write_results(outcome, tmp_path / "run.json"))
    assert meta["failures"][0][0] == "GT-000000"


def test_a_bare_archive_list_is_still_readable(tmp_path):
    """The 2026-08-02 runs are a plain list; they remain the baseline."""
    score = score_record("GT-000001", "email", EXPECTED, {"policy_no": "POL-2020-57052"})
    path = tmp_path / "archive.json"
    path.write_text(
        json.dumps(
            [
                {
                    "gt_id": "GT-000001",
                    "channel": "email",
                    "fields": {
                        name: {"gt": value.gt, "llm": value.llm, "hit": value.hit}
                        for name, value in score.fields.items()
                    },
                    "hits": score.hits,
                    "filled_fields": 6,
                    "unverified_fields": [],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (restored,) = read_results(path)
    assert restored.gt_id == "GT-000001"
    assert restored.filled_fields == 6
    assert read_results_meta(path) == {}


def test_an_empty_run_writes_a_valid_file(tmp_path):
    path = write_results(RunOutcome(model="gpt-4o-mini"), tmp_path / "empty.json")
    assert read_results(path) == []
