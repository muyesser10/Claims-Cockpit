"""
text_generator.py — Synthetic email generator (email channel only).

Reads ground truth records and turns each email-channel record into a
realistic Turkish claim email. Writes each email to a .txt file and fills
in the damage_description field (left null by gt_generator) into a new
enriched ground truth file.

Sprint 1: email channel only. Transcript and form come in Sprint 2.

Usage:
    python data/text_generator.py --count 100 --seed 42
"""

import json
import random
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

DICT_DIR = Path("data/dictionaries")


def load_dictionaries() -> dict:
    """Load all five dictionary files once into memory."""
    damage_phrases = json.loads((DICT_DIR / "damage_phrases.json").read_text(encoding="utf-8"))
    fillers = _read_lines(DICT_DIR / "filler_words.txt")
    openings = _read_lines(DICT_DIR / "opening_templates.txt")
    closings = _read_lines(DICT_DIR / "closing_templates.txt")

    # relative_dates.txt lines look like "dün|1" -> (text, day_offset)
    relative_dates = []
    for line in _read_lines(DICT_DIR / "relative_dates.txt"):
        text, offset = line.split("|")
        relative_dates.append((text, int(offset)))

    return {
        "damage_phrases": damage_phrases,
        "fillers": fillers,
        "openings": openings,
        "closings": closings,
        "relative_dates": relative_dates,
    }


def _read_lines(path: Path) -> list[str]:
    """Read non-empty, stripped lines from a text file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip()]


# Turkish month names for absolute date phrases.
TURKISH_MONTHS = [
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
]

# Turkish locative suffix per city (vowel harmony).
CITY_SUFFIX = {
    "İstanbul": "'da",
    "Ankara": "'da",
    "İzmir": "'de",
    "Bursa": "'da",
    "Antalya": "'da",
}


def make_date_phrase(incident_date: str, received_at: str, relative_dates: list) -> str:
    """Turn the incident date into a text phrase.

    70% absolute ('20 Temmuz'da'), 30% relative ('dün', 'üç gün önce').
    A relative phrase is only used if its day offset matches the real gap
    between received_at and incident_date, so the text stays consistent
    with the ground truth.
    """
    # Parse the dates (both ISO strings).
    incident = incident_date  # e.g. "2026-07-19"
    received_day = received_at[:10]  # take just the date part "2026-07-26"

    _, month, day = (int(p) for p in incident.split("-"))

    # Compute the gap in days between received and incident.

    gap = (date.fromisoformat(received_day) - date.fromisoformat(incident)).days

    # 30% of the time, try a relative phrase that matches the gap.
    if random.random() < 0.3:
        matching = [text for text, offset in relative_dates if offset == gap]
        if matching:
            return random.choice(matching)

    # Otherwise, absolute phrase: "19 Temmuz".
    return f"{day} {TURKISH_MONTHS[month - 1]}"


def build_body(gt: dict, damage_phrase: str, date_phrase: str) -> str:
    """Build the email body from ground truth, respecting null fields.

    Fields that are null in ground truth must NOT appear in the text,
    otherwise the extraction ground truth would be inconsistent.
    """
    expected = gt["expected"]
    parts = []

    # Opening line: date + plate + location + damage.
    city = expected["incident_location"]["city"]
    suffix = CITY_SUFFIX.get(city, "'de")
    plate = expected["plate"]
    parts.append(f"{date_phrase} {plate} plakalı aracımla {city}{suffix} {damage_phrase}.")

    # Injury (only if true).
    if expected["injury"]:
        parts.append("Kazada yaralanan oldu, durum ciddiydi.")

    # Third party (only if true).
    if expected["counterparty_exists"]:
        parts.append("Olayda karşı tarafta başka bir araç da vardı.")

    # Policy number (only if not null).
    if expected["policy_no"]:
        parts.append(f"Poliçe numaram {expected['policy_no']}.")

    # Estimated amount (only if not null — never invent a number).
    if expected["estimated_amount"] is not None:
        parts.append(f"Tahmini hasar tutarı {expected['estimated_amount']} TL civarında.")

    return " ".join(parts)


def build_email(gt: dict, dicts: dict) -> tuple[str, str]:
    """Build a full email from a ground truth record.

    Returns (email_text, damage_phrase) — the phrase is returned so the
    caller can write it back into the enriched ground truth's
    damage_description field.
    """
    expected = gt["expected"]
    personal = gt["_personal"]

    # Pick a damage phrase matching the damage_type.
    damage_type = expected["damage_type"]
    if damage_type and damage_type in dicts["damage_phrases"]:
        damage_phrase = random.choice(dicts["damage_phrases"][damage_type])
    else:
        damage_phrase = "aracımda hasar oluştu"

    # Date phrase (absolute or relative).
    date_phrase = make_date_phrase(
        expected["incident_date"], gt["received_at"], dicts["relative_dates"]
    )

    # Assemble the parts.
    opening = random.choice(dicts["openings"])
    body = build_body(gt, damage_phrase, date_phrase)
    closing = random.choice(dicts["closings"])
    signature = f"Saygılarımla,\n{personal['name']}\nTel: {personal['phone']}"

    email_text = f"{opening}\n\n{body}\n\n{closing}\n\n{signature}"

    return email_text, damage_phrase


app = typer.Typer()


@app.command()
def generate(
    count: Annotated[int, typer.Option(help="Max emails to generate")] = 100,
    seed: Annotated[int, typer.Option(help="Random seed for reproducibility")] = 42,
    ground_truth: Annotated[Path, typer.Option(help="Input ground truth JSONL")] = Path(
        "data/ground_truth.jsonl"
    ),
    emails_output: Annotated[Path, typer.Option(help="Output JSONL for emails")] = Path(
        "data/emails.jsonl"
    ),
    enriched: Annotated[Path, typer.Option(help="Enriched ground truth output")] = Path(
        "data/ground_truth_enriched.jsonl"
    ),
):
    """Generate emails from email-channel ground truth records."""
    random.seed(seed)
    dicts = load_dictionaries()

    enriched_records = []
    emails = []
    written = 0

    for line in ground_truth.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        gt = json.loads(line)

        # This sprint: email channel only.
        if gt["expected"]["channel"] != "email":
            enriched_records.append(gt)  # keep untouched
            continue

        if written >= count:
            enriched_records.append(gt)
            continue

        email_text, damage_phrase = build_email(gt, dicts)

        # Collect the email as one JSONL record.
        emails.append({"gt_id": gt["gt_id"], "channel": "email", "text": email_text})

        # Fill in damage_description in the enriched ground truth.
        gt["expected"]["damage_description"] = damage_phrase
        enriched_records.append(gt)
        written += 1

    # Write all emails to a single JSONL file.
    emails_output.parent.mkdir(parents=True, exist_ok=True)
    with emails_output.open("w", encoding="utf-8") as f:
        for email in emails:
            f.write(json.dumps(email, ensure_ascii=False) + "\n")

    # Write the enriched ground truth.
    with enriched.open("w", encoding="utf-8") as f:
        for record in enriched_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    typer.echo(f"Wrote {written} emails to {emails_output}")
    typer.echo(f"Enriched ground truth: {enriched}")


if __name__ == "__main__":
    app()
