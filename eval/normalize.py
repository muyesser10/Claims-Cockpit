# eval/normalize.py
"""Field-by-field normalization and comparison.

Design doc 6.1: structured fields are normalized, then compared for exact
equality. Every leniency the scorer grants lives here and nowhere else, so any
number can be traced back to the rule that produced it.

These are the conventions the 2026-08-02 baseline was measured with. Changing
one changes the meaning of every number measured since — a decision, not a
refactor.
"""

import re
from datetime import date, datetime

from worker.shared.injury_terms import _normalize_tr

# The eight fields the baseline compared. incident_location counts as one, the
# same way the archived run counted it: splitting it into city and district
# would move the denominator from 800 to 900 and break that comparison.
COMPARED_FIELDS = (
    "policy_no",
    "plate",
    "incident_date",
    "incident_location",
    "damage_type",
    "injury",
    "counterparty_exists",
    "estimated_amount",
)

# The ground truth writes False here, but the text stays silent: text_generator
# only mentions injury and counterparty when they are true (lines 155 and 159),
# and the extraction prompt tells the model not to read silence as "no"
# (extraction_v1.txt rule 6). Both sides are right on their own terms; eval maps
# null to False so they can meet. Locked convention, recorded in docs/STATUS.md.
SILENCE_MEANS_FALSE = ("injury", "counterparty_exists")

# Turkish attaches case suffixes to proper nouns with an apostrophe: "İzmir'de".
APOSTROPHES = "'’`"

# "1.250" and "12.500,75": dots group thousands in the Turkish written form.
THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3})+$")


def normalize_text(value: object) -> str | None:
    """Trim, drop a Turkish case suffix, lowercase the Turkish way.

    Empty becomes None: a model that answers "" found nothing, which is what a
    null means, and the two should not count as different answers.
    """
    if value is None:
        return None
    text = str(value).strip()
    for mark in APOSTROPHES:
        head, separator, _suffix = text.partition(mark)
        if separator:
            text = head
            break
    return _normalize_tr(text).strip() or None


def normalize_plate(value: object) -> str | None:
    """Spacing is the only thing that varies between sources: '45ABC123'."""
    if value is None:
        return None
    return _normalize_tr("".join(str(value).split())) or None


def normalize_date(value: object) -> date | str | None:
    """Accept a date, a datetime or an ISO string.

    An unparseable value is returned as text rather than raised on: it is a real
    miss that belongs in the error list, not a crash that ends the run.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        return text


def normalize_amount(value: object) -> float | str | None:
    """Numbers as numbers.

    The schema makes the model send a number, so the string branch is a
    fallback for hand-written fixtures and for ground truth written by a
    different generator: "12.500,75 TL" -> 12500.75.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return float(value)

    text = re.sub(r"[^\d.,-]", "", str(value))
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif THOUSANDS.match(text):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return str(value).strip()


def normalize_location(value: object) -> tuple[str | None, str | None]:
    """City and district as a pair, so one field compares both halves."""
    if not isinstance(value, dict):
        return (normalize_text(value), None)
    return (normalize_text(value.get("city")), normalize_text(value.get("district")))


def normalize_field(field: str, value: object) -> object:
    """Normalize one value by the rule its field uses."""
    if field == "incident_location":
        return normalize_location(value)
    if field == "incident_date":
        return normalize_date(value)
    if field == "estimated_amount":
        return normalize_amount(value)
    if field == "plate":
        return normalize_plate(value)
    if field in SILENCE_MEANS_FALSE:
        return False if value is None else bool(value)
    return normalize_text(value)


def compare(field: str, expected: object, actual: object) -> bool:
    """True when the two values agree once normalized."""
    return normalize_field(field, expected) == normalize_field(field, actual)
