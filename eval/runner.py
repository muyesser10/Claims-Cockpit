# eval/runner.py
"""Runs an evaluation, or re-scores one that already ran.

Two modes, kept apart on purpose:

  run_live   calls extract() over a sample. Costs money and takes minutes.
  read_results / rescore   reads a results file. Free, offline, instant.

The split is what makes a scoring change cheap: adjusting a normalization rule
re-scores every past run without paying for the model again. It is also why the
raw per-record answers are written out rather than just the totals.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from eval.loader import EvalRecord
from eval.scoring import RecordScore, from_dict, score_record, to_dict
from worker.extraction.extractor import extract
from worker.llm.client import LlmClient, ModelTier

RESULTS_DIR = Path(__file__).resolve().parent / "results"


@dataclass
class RunOutcome:
    """What a live run produced, including what it could not produce.

    Failures are carried separately rather than dropped. A run that quietly
    scored 97 of 100 records and reported an average is the dishonest version
    of this; the caller has to see the three that never answered.
    """

    scores: list[RecordScore] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    model: str = ""


def run_live(
    records: list[EvalRecord],
    *,
    seed: int | None = None,
    tier: ModelTier = ModelTier.CHEAP,
    system_prompt: str | None = None,
    client: LlmClient | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> RunOutcome:
    """Extract and score every record, keeping going when one fails.

    The client is built once and reused: a fresh OpenAI client per record would
    throw away the connection pool for no reason on a run this long.
    """
    client = client or LlmClient()
    outcome = RunOutcome(model=client.settings.model_for(tier))

    for index, record in enumerate(records, start=1):
        try:
            result = extract(
                record.text,
                record.received_at,
                record.channel,
                message_id=record.gt_id,
                client=client,
                seed=seed,
                tier=tier,
                system_prompt=system_prompt,
            )
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            outcome.failures.append((record.gt_id, f"{type(exc).__name__}: {exc}"))
        else:
            outcome.scores.append(
                score_record(
                    record.gt_id,
                    record.channel,
                    record.expected,
                    result.extraction,
                    unverified_fields=result.unverified_fields,
                    duration_ms=result.duration_ms,
                    reasoning=result.reasoning,
                )
            )
        if on_progress is not None:
            on_progress(index, len(records), record.gt_id)

    return outcome


def write_results(
    outcome: RunOutcome,
    path: Path | None = None,
    *,
    meta: dict | None = None,
) -> Path:
    """Write per-record results plus the settings that produced them.

    The settings travel with the numbers because a metric without its model,
    seed and sample is not comparable with anything.
    """
    path = path or RESULTS_DIR / f"run_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "run_at": datetime.now(UTC).isoformat(),
            "model": outcome.model,
            "records": len(outcome.scores),
            "failures": outcome.failures,
            **(meta or {}),
        },
        "records": [to_dict(score) for score in outcome.scores],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_results(path: Path) -> list[RecordScore]:
    """Read a results file written here, or one of the 2026-08-02 archive runs.

    The archived runs are a bare JSON list; this writer wraps the same records
    in an object with a `meta` block. Both are accepted so the baseline stays
    readable by the code that replaced the script which produced it.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = raw if isinstance(raw, list) else raw["records"]
    return [from_dict(record) for record in records]


def read_results_meta(path: Path) -> dict:
    """Run settings, or an empty dict for an archived run that carries none."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {} if isinstance(raw, list) else raw.get("meta", {})
