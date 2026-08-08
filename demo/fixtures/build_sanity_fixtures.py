# demo/fixtures/build_sanity_fixtures.py
"""Recorded masking-sanity verdicts for DEMO_OFFLINE.

Every record - including the wildcard - comes back clean: leak_found=false,
no flags. Three reasons that is the safe answer offline rather than a shortcut:

  - The masking that matters still runs for real. Regex (TC/phone/plate/IBAN)
    and the ~1550-name dictionary are deterministic local code; only the LLM
    second opinion is recorded here.
  - The demo corpus is synthetic and already masked by that layer.
  - check_sanity() fails *closed*, so any other verdict would set
    masking_sanity_flags, and worker/pipeline.py skips both extraction and
    embedding when that is non-empty. An offline demo would show a queue of
    claims with no extracted fields at all.

To demo a leak deliberately, edit one gt_id's line to leak_found=true with a
flag - the pipeline will then skip extraction for that record, which is exactly
what it does in production.

    python demo/fixtures/build_sanity_fixtures.py
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from worker.masking.sanity import SanityCheckResult  # noqa: E402

GROUND_TRUTH = REPO_ROOT / "data" / "ground_truth_enriched.jsonl"
OUTPUT = Path(__file__).resolve().parent / "demo_sanity.jsonl"

RESPONSE_MODEL = "SanityCheckResult"
TIER = "cheap"
WILDCARD_GT_ID = "*"

NOTES = "Çevrimdışı demo: kayıtlı sonuç, LLM'e sorulmadı."

CLEAN_PAYLOAD = {"leak_found": False, "flags": [], "notes": NOTES}


def record(gt_id: str) -> dict:
    """Validate against the real schema, then shape the fixture line."""
    payload = dict(CLEAN_PAYLOAD)
    SanityCheckResult(**payload)
    return {
        "gt_id": gt_id,
        "response_model": RESPONSE_MODEL,
        "tier": TIER,
        "payload": payload,
    }


def gt_ids() -> list[str]:
    if not GROUND_TRUTH.exists():
        raise SystemExit(f"ground truth not found: {GROUND_TRUTH}")

    ids: list[str] = []
    for number, line in enumerate(GROUND_TRUTH.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            ids.append(str(json.loads(line)["gt_id"]))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{GROUND_TRUTH.name}:{number}: not valid JSON ({exc})") from exc
    return ids


def main() -> None:
    ids = gt_ids()
    lines = [json.dumps(record(gt_id), ensure_ascii=False) for gt_id in ids]
    lines.append(json.dumps(record(WILDCARD_GT_ID), ensure_ascii=False))

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{OUTPUT.name}: {len(ids)} ground-truth records + 1 wildcard")


if __name__ == "__main__":
    main()
