# eval/test_loader.py
"""Tests for the corpus loader. Small fixtures on disk, one guard on the real data."""

import json
from datetime import datetime

import pytest

from eval.loader import (
    BASELINE_CHANNEL_MIX,
    EvalRecord,
    baseline_fixture,
    baseline_ids,
    corpus_fingerprint,
    load_records,
    sample,
    select,
)

TEXT = {"gt_id": "GT-000001", "channel": "email", "text": "aracım çizildi"}
ANSWER = {
    "gt_id": "GT-000001",
    "received_at": "2026-07-25T14:00:00",
    "expected": {"channel": "email", "plate": "45 GAK 2046"},
}


def write(directory, name, records):
    """Write records as JSONL and return the path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def load(directory, texts, answers):
    return load_records(write(directory, "t.jsonl", texts), write(directory, "g.jsonl", answers))


def corpus(count_per_channel=40):
    """A synthetic corpus with enough records in every channel to sample from."""
    texts, answers = [], []
    for channel in ("email", "call_transcript", "web_form"):
        for index in range(count_per_channel):
            gt_id = f"GT-{channel[:4]}-{index:03d}"
            texts.append({"gt_id": gt_id, "channel": channel, "text": "x"})
            answers.append(
                {
                    "gt_id": gt_id,
                    "received_at": "2026-07-25T14:00:00",
                    "expected": {"channel": channel},
                }
            )
    return texts, answers


def test_join_maps_every_field(tmp_path):
    (record,) = load(tmp_path, [TEXT], [ANSWER])
    assert record == EvalRecord(
        gt_id="GT-000001",
        channel="email",
        text="aracım çizildi",
        received_at=datetime(2026, 7, 25, 14, 0),
        expected=ANSWER["expected"],
    )


def test_blank_lines_are_skipped(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps(TEXT) + "\n\n\n", encoding="utf-8")
    assert len(load_records(path, write(tmp_path, "g.jsonl", [ANSWER]))) == 1


def test_malformed_line_names_its_line_number(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text('{"gt_id": "GT-1"}\nnot json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="t.jsonl:2"):
        load_records(path, write(tmp_path, "g.jsonl", [ANSWER]))


def test_text_without_ground_truth_is_an_error(tmp_path):
    """A silently shrinking corpus makes two runs look comparable when they aren't."""
    with pytest.raises(ValueError, match="no ground truth"):
        load(tmp_path, [TEXT, {**TEXT, "gt_id": "GT-000002"}], [ANSWER])


def test_ground_truth_without_text_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="no text"):
        load(tmp_path, [TEXT], [ANSWER, {**ANSWER, "gt_id": "GT-000002"}])


def test_channel_disagreement_between_files_is_an_error(tmp_path):
    answer = {**ANSWER, "expected": {**ANSWER["expected"], "channel": "web_form"}}
    with pytest.raises(ValueError, match="channel is 'email'"):
        load(tmp_path, [TEXT], [answer])


def test_sample_is_reproducible_for_one_seed(tmp_path):
    records = load(tmp_path, *corpus())
    mix = {"email": 5, "call_transcript": 3, "web_form": 2}
    first = [record.gt_id for record in sample(records, seed=7, mix=mix)]
    second = [record.gt_id for record in sample(records, seed=7, mix=mix)]
    assert first == second


def test_sample_honours_the_requested_mix(tmp_path):
    records = load(tmp_path, *corpus())
    mix = {"email": 5, "call_transcript": 3, "web_form": 2}
    picked = sample(records, seed=7, mix=mix)
    assert len(picked) == 10
    for channel, count in mix.items():
        assert sum(1 for record in picked if record.channel == channel) == count


def test_sample_ignores_corpus_write_order(tmp_path):
    """The same records in a different file order must give the same draw."""
    texts, answers = corpus()
    forward = load(tmp_path / "a", texts, answers)
    backward = load(tmp_path / "b", texts[::-1], answers[::-1])
    mix = {"email": 5, "call_transcript": 3, "web_form": 2}
    assert {record.gt_id for record in sample(forward, seed=7, mix=mix)} == {
        record.gt_id for record in sample(backward, seed=7, mix=mix)
    }


def test_sample_refuses_to_pad_a_short_channel(tmp_path):
    records = load(tmp_path, *corpus(count_per_channel=2))
    with pytest.raises(ValueError, match="asked for 5, corpus has 2"):
        sample(records, seed=7, mix={"email": 5})


def test_select_returns_exactly_the_requested_records(tmp_path):
    records = load(tmp_path, *corpus())
    picked = select(records, ["GT-emai-002", "GT-web_-000"])
    assert [record.gt_id for record in picked] == ["GT-emai-002", "GT-web_-000"]


def test_select_refuses_an_id_the_corpus_lost(tmp_path):
    records = load(tmp_path, *corpus())
    with pytest.raises(ValueError, match="baseline pairing is broken"):
        select(records, ["GT-emai-000", "GT-gone-999"])


def test_pinned_baseline_is_a_hundred_unique_records():
    assert len(baseline_ids()) == len(set(baseline_ids())) == 100


def test_real_corpus_loads_and_can_feed_the_baseline_mix():
    """Data-integrity guard: catches a regenerated corpus that broke the join."""
    records = load_records()
    assert records
    for channel, count in BASELINE_CHANNEL_MIX.items():
        assert sum(1 for record in records if record.channel == channel) >= count


def test_real_corpus_still_carries_every_pinned_record():
    """Data-integrity guard: a regenerated corpus breaks the baseline pairing."""
    picked = select(load_records(), baseline_ids())
    assert len(picked) == 100
    for channel, count in BASELINE_CHANNEL_MIX.items():
        assert sum(1 for record in picked if record.channel == channel) == count


def test_corpus_still_matches_the_fingerprint_the_baseline_was_pinned_against():
    """The direct form of the data-integrity guard.

    The channel-mix check above catches a rebuild only when the mix moves, which
    is how PR #44 was caught - by luck. A rebuild that preserved the mix and
    replaced the texts would have passed it, and every number measured afterwards
    would have been reported as comparable with a baseline describing different
    records. This check does not depend on that luck.

    When it fails, the corpus changed under the baseline. The fix is to re-pin
    and re-measure, not to update the digests: the old number stops meaning
    anything either way, and only one of the two options admits it.
    """
    pinned = baseline_fixture()["corpus"]
    assert corpus_fingerprint() == pinned, (
        "the corpus no longer matches what the baseline was pinned against - "
        "every measurement taken against that baseline is now incomparable, and "
        "the sample has to be re-pinned and re-measured"
    )


def test_every_pinned_record_is_a_claim():
    """The sample's defining property, asserted rather than assumed.

    Extraction only ever runs on claims: classification exits early for the other
    two content types (design doc §4). A pinned sample that drifted to include
    them would raise the accuracy without the model doing anything - their only
    filled field is policy_no, so a model answering null everywhere scores full
    marks on them.
    """
    picked = select(load_records(), baseline_ids())
    assert {record.expected.get("content_type") for record in picked} == {"claim"}
