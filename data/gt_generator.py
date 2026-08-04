import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from faker import Faker

_DICT_DIR = Path("data/dictionaries")
HOLDOUT_FIRST = [
    n.strip()
    for n in (_DICT_DIR / "holdout_first_names.txt").read_text(encoding="utf-8").splitlines()
    if n.strip()
]
HOLDOUT_LAST = [
    n.strip()
    for n in (_DICT_DIR / "holdout_last_names.txt").read_text(encoding="utf-8").splitlines()
    if n.strip()
]



# --- Enum values (must match schemas/claim.json) ---
CHANNELS = ["email", "call_transcript", "web_form"]
CONTENT_TYPES = ["claim", "info_request", "irrelevant"]
URGENCIES = ["critical", "high", "normal"]
DAMAGE_TYPES = [
    "collision",
    "single_vehicle",
    "glass",
    "hail",
    "fire",
    "theft",
    "animal",
    "other",
]

# --- Distributions (realistic, not uniform) ---
CHANNEL_WEIGHTS = [0.50, 0.30, 0.20]  # email most common
CONTENT_TYPE_WEIGHTS = [0.90, 0.08, 0.02]  # mostly real claims
URGENCY_WEIGHTS = [0.08, 0.30, 0.62]  # most are normal

# --- Turkish cities and a few districts each (for incident_location) ---
CITY_DISTRICTS = {
    "İstanbul": ["Kadıköy", "Beşiktaş", "Üsküdar", "Bakırköy"],
    "Ankara": ["Çankaya", "Keçiören", "Mamak", "Yenimahalle"],
    "İzmir": ["Bornova", "Karşıyaka", "Konak", "Buca"],
    "Bursa": ["Nilüfer", "Osmangazi", "Yıldırım"],
    "Antalya": ["Muratpaşa", "Kepez", "Konyaaltı"],
}

# --- Plate letters (Turkish plates use a subset of the alphabet) ---
PLATE_LETTERS = "ABCDEFGHIJKLMNOPRSTUVYZ"

# --- Turkish mobile operator prefixes (05XX) ---
PHONE_PREFIXES = [
    "530",
    "531",
    "532",
    "533",
    "534",
    "535",
    "536",
    "537",
    "538",
    "539",
    "540",
    "541",
    "542",
    "543",
    "544",
    "545",
    "505",
    "506",
    "507",
    "551",
    "552",
    "553",
    "554",
    "555",
]


fake = Faker("tr_TR")


def make_plate() -> str:
    """Generate a Turkish plate like '34 AB 1234'."""
    city_code = random.randint(1, 81)
    letters = "".join(random.choices(PLATE_LETTERS, k=random.choice([1, 2, 3])))
    number = random.randint(1, 9999)
    return f"{city_code:02d} {letters} {number}"


def make_policy_no() -> str:
    """Generate a policy number like 'POL-2024-12345'."""
    year = random.randint(2020, 2025)
    serial = random.randint(10000, 99999)
    return f"POL-{year}-{serial}"


def make_received_at() -> datetime:
    """Generate a fixed 'message received' timestamp.

    Reproducible: depends only on the seeded random state, so relative
    dates in the text ('yesterday') resolve consistently across runs.
    """
    days_ago = random.randint(0, 30)
    base = datetime(2026, 7, 1, 9, 0, 0)
    return base + timedelta(days=days_ago, hours=random.randint(0, 8))


def make_incident_date(received: datetime) -> str:
    """Generate an incident date at or before the received date (ISO string)."""
    days_before = random.randint(0, 14)
    incident = received.date() - timedelta(days=days_before)
    return incident.isoformat()


def make_location() -> dict:
    """Pick a city and (usually) a district. District can be null."""
    city = random.choice(list(CITY_DISTRICTS))
    district = None
    if random.random() > 0.2:  # 80% have a district, 20% null
        district = random.choice(CITY_DISTRICTS[city])
    return {"city": city, "district": district}


def make_personal() -> dict:
    """Generate personal data written INTO the text, never into 'expected'."""
    prefix = random.choice(PHONE_PREFIXES)
    number = random.randint(1000000, 9999999)
    phone = f"0{prefix} {str(number)[:3]} {str(number)[3:]}"
    if random.random() < 0.3:
        name = f"{random.choice(HOLDOUT_FIRST)} {random.choice(HOLDOUT_LAST)}"
        name_source = "holdout"
    else:
        name = f"{fake.first_name()} {fake.last_name()}"
        name_source = "faker"

    return {
        "name": name,
        "name_source": name_source,
        "phone": phone,
        "tc": str(random.randint(10000000000, 99999999999)),
    }


def build_one(index: int) -> dict:
    """Build a single synthetic ground truth record.

    Structure:
      - gt_id, received_at: for identification and relative-date resolution
      - expected: the fields the LLM should extract (matches claim.json)
      - _personal: PII written into the text, never into 'expected'

    Note: source_references is NOT produced here — the LLM/pipeline creates it.
    """
    channel = random.choices(CHANNELS, weights=CHANNEL_WEIGHTS)[0]
    content_type = random.choices(CONTENT_TYPES, weights=CONTENT_TYPE_WEIGHTS)[0]

    received = make_received_at()

    # Injury is decided first; injury forces critical (CLAUDE.md rule).
    # Injury rate equals the locked critical rate (8%) so the frozen
    # urgency distribution is preserved: every critical has an injury.
    injury = random.random() < 0.08
    if injury:
        urgency = "critical"
    else:
        urgency = random.choices(["high", "normal"], weights=[0.30, 0.62])[0]

    damage_type = random.choice(DAMAGE_TYPES)

    expected = {
        "channel": channel,
        "content_type": content_type,
        "urgency": urgency,
        "policy_no": make_policy_no(),
        "plate": make_plate(),
        "incident_date": make_incident_date(received),
        "incident_location": make_location(),
        "damage_description": None,  # filled by text_generator later
        "damage_type": damage_type,
        "injury": injury,
        "counterparty_exists": (random.random() < 0.6 if damage_type == "collision" else False),
        "estimated_amount": (random.randint(1000, 100000) if random.random() > 0.15 else None),
    }

    # Content type shapes which fields are present.
    if content_type == "info_request":
        # A question about coverage/process — no incident to report.
        expected["plate"] = None
        expected["incident_date"] = None
        expected["incident_location"] = {"city": None, "district": None}
        expected["damage_type"] = None
        expected["injury"] = None
        expected["counterparty_exists"] = None
        expected["estimated_amount"] = None
        expected["urgency"] = "normal"
        # policy_no stays — they may reference their own policy.
    elif content_type == "irrelevant":
        # Off-topic — nothing insurance-related at all.
        expected["policy_no"] = None
        expected["plate"] = None
        expected["incident_date"] = None
        expected["incident_location"] = {"city": None, "district": None}
        expected["damage_type"] = None
        expected["injury"] = None
        expected["counterparty_exists"] = None
        expected["estimated_amount"] = None
        expected["urgency"] = "normal"

    return {
        "gt_id": f"GT-{index:06d}",
        "received_at": received.isoformat(),
        "expected": expected,
        "_personal": make_personal(),
    }


def write_jsonl(records: list[dict], output: Path) -> None:
    """Write records to a JSONL file, one JSON object per line."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for record in records:
            line = json.dumps(record, ensure_ascii=False)
            f.write(line + "\n")


app = typer.Typer()


@app.command()
def generate(
    count: Annotated[int, typer.Option(help="Number of records to generate")] = 100,
    seed: Annotated[int, typer.Option(help="Random seed for reproducibility")] = 42,
    output: Annotated[Path, typer.Option(help="Output JSONL file path")] = Path(
        "data/ground_truth.jsonl"
    ),
):
    """Generate `count` synthetic ground truth records into `output`."""
    random.seed(seed)
    fake.seed_instance(seed)

    records = []
    for i in range(count):
        record = build_one(i)
        records.append(record)

    write_jsonl(records, output)
    typer.echo(f"Wrote {len(records)} records to {output}")


if __name__ == "__main__":
    app()
