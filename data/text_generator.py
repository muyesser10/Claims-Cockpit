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
    form_damage_phrases = json.loads(
        (DICT_DIR / "form_damage_phrases.json").read_text(encoding="utf-8")
    )
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
        "form_damage_phrases": form_damage_phrases,
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


def resolve_location(expected: dict) -> str:
    """Return the location phrase and align GT district with the text.

    If the district is present, 60% of the time it is written into the text
    (GT keeps it); 40% of the time it is omitted from the text AND set to
    null in GT — so text and ground truth stay consistent, and some records
    exercise the "leave null when not in text" rule.
    """
    city = expected["incident_location"]["city"]
    suffix = CITY_SUFFIX.get(city, "'de")
    district = expected["incident_location"].get("district")

    if district and random.random() < 0.6:
        # Keep district: write it into the text, GT stays as is.
        return f"{city} {district}{_district_suffix(district)}"
    else:
        # Omit district: not in text, so null it in GT for consistency.
        expected["incident_location"]["district"] = None
        return f"{city}{suffix}"


def _district_suffix(district: str) -> str:
    """Locative suffix for a district (rough Turkish vowel harmony)."""
    back_vowels = "aıou"
    last_vowel = next((ch for ch in reversed(district.lower()) if ch in "aeıioöuü"), "e")
    return "'da" if last_vowel in back_vowels else "'de"


def build_body(gt: dict, damage_phrase: str, date_phrase: str) -> str:
    """Build the email body from ground truth, respecting null fields.

    Fields that are null in ground truth must NOT appear in the text,
    otherwise the extraction ground truth would be inconsistent.
    """
    expected = gt["expected"]
    parts = []

    # Opening line: date + plate + location + damage.
    location = resolve_location(expected)
    plate = expected["plate"]
    parts.append(f"{date_phrase} {plate} plakalı aracımla {location} {damage_phrase}.")

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


def build_transcript(gt: dict, dicts: dict) -> tuple[str, str]:
    """Build a call-center transcript from a ground truth record.

    Agent/Müşteri dialogue with fillers and scattered info. Same fidelity
    rules as email: null fields never appear, PII goes in text not expected,
    damage phrase matches damage_type. Returns (text, damage_phrase).
    """
    expected = gt["expected"]
    personal = gt["_personal"]
    fillers = dicts["fillers"]

    # Damage phrase matching the type (same as email).
    damage_type = expected["damage_type"]
    if damage_type and damage_type in dicts["damage_phrases"]:
        damage_phrase = random.choice(dicts["damage_phrases"][damage_type])
    else:
        damage_phrase = "aracımda hasar oluştu"

    date_phrase = make_date_phrase(
        expected["incident_date"], gt["received_at"], dicts["relative_dates"]
    )
    location = resolve_location(expected)

    def filler() -> str:
        """Return a filler word 40% of the time, else empty."""
        return random.choice(fillers) + " " if random.random() < 0.4 else ""

    turns = []
    turns.append(
        "Ajan: "
        + random.choice(
            [
                "Merhaba, size nasıl yardımcı olabilirim?",
                "İyi günler, buyurun sizi dinliyorum.",
                "Merhaba, sigorta hasar kaydı için mi aradınız?",
                "İyi günler, hasar kaydı oluşturmak için mi aradınız?",
            ]
        )
    )
    turns.append(f"Müşteri: {filler()}{date_phrase} {location} {damage_phrase}.")
    turns.append(
        "Ajan: "
        + random.choice(
            [
                "Poliçe numaranızı alabilir miyim?",
                "Poliçe numaranız neydi?",
                "Poliçenizin numarasını öğrenebilir miyim?",
                "Poliçe no'yu paylaşır mısınız?",
            ]
        )
    )
    turns.append(f"Müşteri: {expected['policy_no']}.")
    turns.append(
        "Ajan: "
        + random.choice(
            [
                "Aracınızın plakası neydi?",
                "Plakanızı alabilir miyim?",
                "Araç plakanızı söyler misiniz?",
                "Plaka numaranızı öğrenebilir miyim?",
            ]
        )
    )
    turns.append(f"Müşteri: {expected['plate']}.")

    # Injury: sometimes volunteered, sometimes asked.
    if expected["injury"]:
        turns.append("Ajan: Yaralanan var mı?")
        turns.append(
            "Müşteri: "
            + random.choice(
                [
                    "evet, bir kişi hafif yaralandı.",
                    "maalesef birkaç yaralımız var.",
                    "evet, ambulans çağırdık.",
                    "evet, ufak yaralanmalar oldu.",
                    "evet, bir yaralı hastaneye götürüldü.",
                    "evet, birkaç kişi tedavi gördü.",
                    "evet,  yaralanan oldu.",
                    "evet",
                ]
            )
        )
    else:
        turns.append("Ajan: Aracınızda yaralanan var mı?")
        turns.append(
            "Müşteri: "
            + random.choice(
                [
                    "hayır, kimse zarar görmedi.",
                    "yok, sadece araçta hasar var.",
                    "çok şükür yaralanan olmadı.",
                    "hayır, herkes iyi durumda.",
                    "yok, ufak tefek çizikler dışında kimseye bir şey olmadı.",
                    "yok, sadece maddi hasar var.",
                    "hayır, kazada kimse yaralanmadı.",
                    "hayır",
                    "yok",
                ]
            )
        )

    # Counterparty
    turns.append(
        "Ajan: "
        + random.choice(
            [
                "Karşı tarafta başka araç var mıydı?",
                "Olayda başka bir araç var mıydı?",
                "Kazaya karışan başka araç oldu mu?",
            ]
        )
    )
    if expected["counterparty_exists"]:
        turns.append(
            "Müşteri: "
            + random.choice(
                [
                    "evet, karşı tarafta bir araç vardı.",
                    "evet, başka bir araç da olaya karıştı.",
                    "evet, iki araç da olaya karıştı.",
                ]
            )
        )
    else:
        turns.append(
            "Müşteri: "
            + random.choice(
                [
                    "hayır, tek taraflı bir olaydı.",
                    "yok, başka araç yoktu.",
                    "hayır, karşı taraf yoktu.",
                ]
            )
        )

    # Amount only if not null (never invent).
    if expected["estimated_amount"] is not None:
        turns.append(
            "Ajan: "
            + random.choice(
                [
                    "Tahmini hasar tutarı hakkında fikriniz var mı?",
                    "Hasar ne kadar tutar tahmini olarak?",
                    "Yaklaşık hasar bedeli ne kadar?",
                ]
            )
        )
        turns.append(
            "Müşteri: "
            + random.choice(
                [
                    f"yaklaşık {expected['estimated_amount']} TL civarı.",
                    f"tahminen {expected['estimated_amount']} TL kadar.",
                    f"{expected['estimated_amount']} TL civarında sanırım.",
                ]
            )
        )

    # Closing with personal info (masking material).
    turns.append("Ajan: Son olarak ad soyad ve telefon alabilir miyim?")
    turns.append(f"Müşteri: {personal['name']}, {personal['phone']}.")

    return "\n".join(turns), damage_phrase


def build_form(gt: dict, dicts: dict) -> tuple[str, str]:
    """Build a web-form record as labeled plain text.

    Most structured but trickiest channel. Damage description is short and
    telegraphic. Some fields are occasionally blank (~10%). Same fidelity
    rules: null fields absent, PII in text not expected. Returns (text, phrase).
    """
    expected = gt["expected"]
    personal = gt["_personal"]

    # Short, telegraphic damage phrase from the form-specific dictionary.
    damage_type = expected["damage_type"]
    if damage_type and damage_type in dicts["form_damage_phrases"]:
        damage_phrase = random.choice(dicts["form_damage_phrases"][damage_type])
    else:
        damage_phrase = "araç hasarlı"

    # Short, telegraphic damage phrase from the form-specific dictionary.
    damage_type = expected["damage_type"]
    if damage_type and damage_type in dicts["form_damage_phrases"]:
        damage_phrase = random.choice(dicts["form_damage_phrases"][damage_type])
    else:
        damage_phrase = "araç hasarlı"

    # Free-text description (the real extraction target) from the normal dict.
    if damage_type and damage_type in dicts["damage_phrases"]:
        description = random.choice(dicts["damage_phrases"][damage_type])
    else:
        description = damage_phrase

    lines = []
    lines.append(f"Poliçe No: {expected['policy_no']}")
    lines.append(f"Plaka: {expected['plate']}")

    # Date: 10% blank (form fields often left empty).
    if random.random() < 0.1:
        lines.append("Olay Tarihi: ")
    else:
        lines.append(f"Olay Tarihi: {expected['incident_date']}")

    # Location: keep district in text 60% of the time, else null it in GT.
    city = expected["incident_location"]["city"]
    district = expected["incident_location"].get("district")
    lines.append(f"İl: {city}")
    if district and random.random() < 0.6:
        lines.append(f"İlçe: {district}")
    else:
        expected["incident_location"]["district"] = None

    # Damage: short label + free-text description (extraction's real work).
    lines.append(f"Hasar: {damage_phrase}")
    lines.append(f"Açıklama: {description}")

    # Injury: 10% blank, otherwise evet/hayır.
    if random.random() < 0.1:
        lines.append("Yaralanma: ")
    else:
        lines.append(f"Yaralanma: {'evet' if expected['injury'] else 'hayır'}")

    # Counterparty only if true (single-sided events omit it).
    if expected["counterparty_exists"]:
        lines.append("Karşı Taraf: evet")

    # Amount only if not null.
    if expected["estimated_amount"] is not None:
        lines.append(f"Tahmini Hasar: {expected['estimated_amount']} TL")

    # Personal info (masking material).
    lines.append(f"Ad Soyad: {personal['name']}")
    lines.append(f"Telefon: {personal['phone']}")

    return "\n".join(lines), description


app = typer.Typer()


@app.command()
def generate(
    count: Annotated[int, typer.Option(help="Max emails to generate")] = 100,
    seed: Annotated[int, typer.Option(help="Random seed for reproducibility")] = 42,
    ground_truth: Annotated[Path, typer.Option(help="Input ground truth JSONL")] = Path(
        "data/ground_truth.jsonl"
    ),
    texts_output: Annotated[Path, typer.Option(help="Output JSONL for texts")] = Path(
        "data/texts.jsonl"
    ),
    enriched: Annotated[Path, typer.Option(help="Enriched ground truth output")] = Path(
        "data/ground_truth_enriched.jsonl"
    ),
):
    """Generate texts (email + transcript) from ground truth records."""
    random.seed(seed)
    dicts = load_dictionaries()

    enriched_records = []
    texts = []
    written = 0

    for line in ground_truth.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        gt = json.loads(line)

        channel = gt["expected"]["channel"]

        # All three channels supported.
        if channel not in ("email", "call_transcript", "web_form"):
            enriched_records.append(gt)  # keep untouched
            continue

        if written >= count:
            enriched_records.append(gt)
            continue

        if channel == "email":
            text, damage_phrase = build_email(gt, dicts)
        elif channel == "call_transcript":
            text, damage_phrase = build_transcript(gt, dicts)
        else:  # web_form
            text, damage_phrase = build_form(gt, dicts)

        # Collect the text as one JSONL record.
        texts.append({"gt_id": gt["gt_id"], "channel": channel, "text": text})

        # Fill in damage_description in the enriched ground truth.
        gt["expected"]["damage_description"] = damage_phrase
        enriched_records.append(gt)
        written += 1

    # Write all texts (email + transcript) to a single JSONL file.
    texts_output.parent.mkdir(parents=True, exist_ok=True)
    with texts_output.open("w", encoding="utf-8") as f:
        for text_record in texts:
            f.write(json.dumps(text_record, ensure_ascii=False) + "\n")

    # Write the enriched ground truth.
    with enriched.open("w", encoding="utf-8") as f:
        for record in enriched_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    typer.echo(f"Wrote {written} texts to {texts_output}")
    typer.echo(f"Enriched ground truth: {enriched}")


if __name__ == "__main__":
    app()
