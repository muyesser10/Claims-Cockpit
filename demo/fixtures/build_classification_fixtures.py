# demo/fixtures/build_classification_fixtures.py
"""Recorded classification verdicts for DEMO_OFFLINE.

The ground truth carries content_type and urgency for every record, which is
exactly what ClaimClassification asks the model for. `injury_mentioned` is not
in the ground truth, so it is derived: `injury` is the field that decides it,
and urgency=critical without an injury flag is treated as an injury signal too.

The deterministic override in classify() runs over whatever comes back from
here (worker/classification/classifier.py). That is the point of recording a
verdict rather than short-circuiting the step: offline still exercises the rule
CLAUDE.md §7's critical-recall target rests on.

Note this is ClaimClassification (worker/classification/schema.py), not
ClaimExtraction - two different models, two different files, one fixture set.

    python demo/fixtures/build_classification_fixtures.py
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from worker.classification.schema import ClaimClassification  # noqa: E402

GROUND_TRUTH = REPO_ROOT / "data" / "ground_truth_enriched.jsonl"
OUTPUT = Path(__file__).resolve().parent / "demo_classification.jsonl"

RESPONSE_MODEL = "ClaimClassification"
TIER = "cheap"
WILDCARD_GT_ID = "*"

DEFAULT_CONTENT_TYPE = "claim"
DEFAULT_URGENCY = "normal"

REASONING = "Çevrimdışı demo: bu sınıflandırma kayıtlı ground truth'tan geldi, modele sorulmadı."
WILDCARD_REASONING = (
    "Çevrimdışı demo: bu mesaj için kayıtlı bir sınıflandırma yok, nötr varsayılan kullanıldı."
)


def build_payload(expected: dict) -> dict:
    """One recorded ClaimClassification from a ground-truth `expected` block."""
    urgency = expected.get("urgency") or DEFAULT_URGENCY
    # injury_mentioned is the model's own read of the text, and the ground truth
    # states the fact instead. Either the injury flag or a critical urgency is
    # taken as "the text mentions it" - the safe direction, since classify()
    # only ever uses this field to raise urgency, never to lower it.
    injury_mentioned = bool(expected.get("injury")) or urgency == "critical"

    return {
        "reasoning": REASONING,
        "content_type": expected.get("content_type") or DEFAULT_CONTENT_TYPE,
        "urgency": urgency,
        "injury_mentioned": injury_mentioned,
    }


def build_wildcard_payload() -> dict:
    """The verdict for a message with no recorded one: neutral and safe.

    content_type=claim rather than info_request for the same reason
    fallback_classification() picks it: treating a question as a claim costs one
    wasted extraction, while the reverse drops a real claim out of the queue.
    Urgency stays normal, and injury_mentioned false - the injury terms in
    classify() still run over the real text and can still raise it to critical.
    """
    return {
        "reasoning": WILDCARD_REASONING,
        "content_type": DEFAULT_CONTENT_TYPE,
        "urgency": DEFAULT_URGENCY,
        "injury_mentioned": False,
    }


def record(gt_id: str, payload: dict) -> dict:
    """Validate against the real schema, then shape the fixture line."""
    ClaimClassification(**payload)
    return {
        "gt_id": gt_id,
        "response_model": RESPONSE_MODEL,
        "tier": TIER,
        "payload": payload,
    }


def main() -> None:
    if not GROUND_TRUTH.exists():
        raise SystemExit(f"ground truth not found: {GROUND_TRUTH}")

    lines: list[str] = []
    count = 0

    for number, line in enumerate(GROUND_TRUTH.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            source = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{GROUND_TRUTH.name}:{number}: not valid JSON ({exc})") from exc

        entry = record(str(source["gt_id"]), build_payload(source.get("expected") or {}))
        lines.append(json.dumps(entry, ensure_ascii=False))
        count += 1

    lines.append(json.dumps(record(WILDCARD_GT_ID, build_wildcard_payload()), ensure_ascii=False))

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{OUTPUT.name}: {count} ground-truth records + 1 wildcard")


if __name__ == "__main__":
    main()
