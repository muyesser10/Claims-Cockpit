# eval/loader.py
"""Reads the evaluation corpus and picks reproducible samples.

Two files, joined on `gt_id`:
  - data/texts.jsonl                  what the system sees (gt_id, channel, text)
  - data/ground_truth_enriched.jsonl  the answer key (gt_id, received_at, expected)

`received_at` lives in the answer-key file, not in texts.jsonl where
IhbarKokpiti-Veri-Kontrati.md 2.1 puts it. extract() needs it to resolve
relative dates, so the loader reads it from there. Recorded rather than worked
around: moving the field is @muyesser10's call.
"""

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEXTS_PATH = REPO_ROOT / "data" / "texts.jsonl"
GROUND_TRUTH_PATH = REPO_ROOT / "data" / "ground_truth_enriched.jsonl"
BASELINE_IDS_PATH = Path(__file__).resolve().parent / "fixtures" / "baseline_100_ids.json"

# The channel mix of the baseline run. Holding it fixed is what makes a later
# number comparable with that one; a run with a different mix is a different
# measurement, not a better or worse one.
BASELINE_CHANNEL_MIX = {"email": 50, "call_transcript": 30, "web_form": 20}


@dataclass(frozen=True)
class EvalRecord:
    """One message together with its answer key."""

    gt_id: str
    channel: str
    text: str
    received_at: datetime
    expected: dict


def _read_jsonl(path: Path) -> list[dict]:
    """Parse a JSONL file, naming the line number when one is malformed."""
    records: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{number} is not valid JSON: {exc}") from exc
    return records


def load_records(
    texts_path: Path = TEXTS_PATH,
    ground_truth_path: Path = GROUND_TRUTH_PATH,
) -> list[EvalRecord]:
    """Join the two corpus files on `gt_id`, preserving texts.jsonl order.

    A gt_id present in one file and absent from the other is an error, not a
    record to skip quietly. A corpus that shrinks on its own makes two runs look
    comparable when they are not, which is the one thing eval must never do.
    """
    texts = _read_jsonl(texts_path)
    answers = {record["gt_id"]: record for record in _read_jsonl(ground_truth_path)}

    missing = [record["gt_id"] for record in texts if record["gt_id"] not in answers]
    if missing:
        raise ValueError(
            f"{len(missing)} gt_id in {texts_path.name} have no ground truth (first: {missing[0]})"
        )

    orphans = sorted(set(answers) - {record["gt_id"] for record in texts})
    if orphans:
        raise ValueError(
            f"{len(orphans)} gt_id in {ground_truth_path.name} have no text (first: {orphans[0]})"
        )

    records = []
    for text in texts:
        answer = answers[text["gt_id"]]
        # The channel is stated twice, once per file. If they ever disagree, the
        # corpus was rebuilt in halves and every channel breakdown below is junk.
        if answer["expected"]["channel"] != text["channel"]:
            raise ValueError(
                f"{text['gt_id']}: channel is '{text['channel']}' in {texts_path.name} "
                f"but '{answer['expected']['channel']}' in {ground_truth_path.name}"
            )
        records.append(
            EvalRecord(
                gt_id=text["gt_id"],
                channel=text["channel"],
                text=text["text"],
                received_at=datetime.fromisoformat(answer["received_at"]),
                expected=answer["expected"],
            )
        )
    return records


def _sha256(path: Path) -> str:
    """The file's digest, read in blocks so a large corpus never sits in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def corpus_fingerprint(
    texts_path: Path = TEXTS_PATH,
    ground_truth_path: Path = GROUND_TRUTH_PATH,
) -> dict[str, str]:
    """A digest of both corpus files, pinned alongside the baseline sample.

    The point is to catch a regenerated corpus by name rather than by inference.
    The 2026-08-04 rebuild (PR #44) kept every gt_id and replaced the text behind
    them; the channel-mix check noticed only because the mix happened to move as
    well. A rebuild that preserved the mix would have gone through in silence,
    and every number measured afterwards would have been compared against a
    baseline that no longer described the same records.
    """
    return {
        "texts_sha256": _sha256(texts_path),
        "ground_truth_sha256": _sha256(ground_truth_path),
    }


def baseline_fixture(path: Path = BASELINE_IDS_PATH) -> dict:
    """The whole pinned-sample file: ids, channel mix and corpus fingerprint."""
    return json.loads(path.read_text(encoding="utf-8"))


def baseline_ids(path: Path = BASELINE_IDS_PATH) -> list[str]:
    """The 100 records the current extraction baseline measured.

    Pinned rather than resampled. `sample()` draws a different hundred each time
    the pool changes, and comparing two runs across two samples buries a real
    change under sampling luck. Every later run reuses these, for as long as
    `corpus_fingerprint()` still matches what is pinned beside them.
    """
    return baseline_fixture(path)["gt_ids"]


def select(records: list[EvalRecord], gt_ids: list[str]) -> list[EvalRecord]:
    """Pick exactly these records, in the order given.

    A pinned id the corpus no longer carries is an error, not a record to skip.
    Failing here is the point: the alternative is a quietly shorter run that
    still reports a rate as though nothing had changed.
    """
    by_id = {record.gt_id: record for record in records}
    absent = [gt_id for gt_id in gt_ids if gt_id not in by_id]
    if absent:
        raise ValueError(
            f"{len(absent)} pinned gt_id are not in the corpus (first: {absent[0]}); "
            "the corpus was regenerated and the baseline pairing is broken"
        )
    return [by_id[gt_id] for gt_id in gt_ids]


def sample(
    records: list[EvalRecord],
    *,
    seed: int,
    mix: dict[str, int] | None = None,
) -> list[EvalRecord]:
    """Pick a channel-stratified sample, reproducibly.

    The same seed over the same corpus returns the same records. That is the
    whole point: a week-to-week comparison means nothing if the sample moved
    underneath it. Sorting the pool first keeps the draw independent of the
    order the corpus happened to be written in.
    """
    mix = mix or BASELINE_CHANNEL_MIX
    rng = random.Random(seed)
    picked: list[EvalRecord] = []

    for channel, count in mix.items():
        pool = sorted(
            (record for record in records if record.channel == channel),
            key=lambda record: record.gt_id,
        )
        if len(pool) < count:
            raise ValueError(f"channel '{channel}': asked for {count}, corpus has {len(pool)}")
        picked.extend(sorted(rng.sample(pool, count), key=lambda record: record.gt_id))

    return picked
