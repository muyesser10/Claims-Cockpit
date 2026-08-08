# demo/fixtures/build_extraction_fixtures.py
"""Turn the ground truth into recorded extraction answers for DEMO_OFFLINE.

One line per ground-truth record, plus the wildcard that answers for anything
typed live at the demo. Every payload is validated against ClaimExtraction
before it is written: a fixture that does not fit the schema must fail here,
not in front of an audience.

Only the `expected` block is read. The `_personal` block next to it holds
names, phone numbers and TC numbers - synthetic, but shaped like the real
thing, and these files are committed.

    python demo/fixtures/build_extraction_fixtures.py
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from worker.extraction.schema import ClaimExtraction  # noqa: E402

GROUND_TRUTH = REPO_ROOT / "data" / "ground_truth_enriched.jsonl"
OUTPUT = Path(__file__).resolve().parent / "demo_extraction.jsonl"

# The class name client.structured() is called with (worker/extraction/
# extractor.py:175). NOT ExtractionResult - that is the wrapper extract()
# returns afterwards and it never reaches the LLM client.
RESPONSE_MODEL = "ClaimExtraction"
TIER = "cheap"
WILDCARD_GT_ID = "*"

# What ClaimExtraction owns. The ground truth also carries channel,
# content_type and urgency; those belong to the system and to classification,
# and worker/extraction/schema.py leaves them out on purpose.
EXTRACTION_FIELDS = (
    "policy_no",
    "plate",
    "incident_date",
    "incident_location",
    "damage_description",
    "damage_type",
    "injury",
    "counterparty_exists",
    "estimated_amount",
)

NESTED_LOCATION_KEYS = ("city", "district")

REASONING = "Çevrimdışı demo: bu cevap kayıtlı ground truth'tan geldi, modele sorulmadı."
WILDCARD_REASONING = (
    "Çevrimdışı demo: bu mesaj için kayıtlı bir cevap yok, hiçbir alan doldurulmadı."
)


def _location_payload(value: object) -> dict:
    """incident_location, always as an object with both keys present."""
    location = value if isinstance(value, dict) else {}
    return {key: location.get(key) for key in NESTED_LOCATION_KEYS}


def build_payload(expected: dict) -> dict:
    """One recorded ClaimExtraction, built from a ground-truth `expected` block."""
    payload: dict = {"reasoning": REASONING}
    missing: list[str] = []

    for field in EXTRACTION_FIELDS:
        value = expected.get(field)
        if field == "incident_location":
            location = _location_payload(value)
            payload[field] = location
            missing.extend(
                f"{field}.{key}" for key in NESTED_LOCATION_KEYS if location[key] is None
            )
            continue

        payload[field] = value
        if value is None:
            missing.append(field)

    payload["missing_fields"] = missing
    # Empty on purpose: the ground truth records what the values are, not where
    # in the text they sit. See README - source highlighting stays off offline.
    payload["source_references"] = {}
    payload["field_confidence"] = {}
    payload["low_confidence_fields"] = []
    return payload


def build_wildcard_payload() -> dict:
    """The answer for a message with no recorded one: everything left null.

    Nothing is invented here. A plausible-looking plate or amount attached to a
    message nobody recorded would be the one thing an offline demo must not do.
    """
    payload: dict = {"reasoning": WILDCARD_REASONING}
    missing: list[str] = []

    for field in EXTRACTION_FIELDS:
        if field == "incident_location":
            payload[field] = dict.fromkeys(NESTED_LOCATION_KEYS)
            missing.extend(f"{field}.{key}" for key in NESTED_LOCATION_KEYS)
            continue
        payload[field] = None
        missing.append(field)

    payload["missing_fields"] = missing
    payload["source_references"] = {}
    payload["field_confidence"] = {}
    payload["low_confidence_fields"] = []
    return payload


def record(gt_id: str, payload: dict) -> dict:
    """Validate against the real schema, then shape the fixture line."""
    ClaimExtraction(**payload)
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
