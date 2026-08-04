# eval/scoring.py
"""Scores one extraction against its answer key.

The output shape deliberately matches the archived measurement runs
(olcum-arsivi/baseline_100_results_v3.json): `fields` keyed by field name, each
holding `gt`, `llm` and `hit`, plus `hits`, `filled_fields` and
`unverified_fields`. Keeping the shape means the archive can be re-scored by
this code, which is what test_regression.py checks.

Two keys go beyond that shape: `expected` and `extraction` carry the full pair
the score was derived from, so a metric written later can be computed from a run
that is already paid for. Reading stays backwards compatible — an archived run
simply has neither.

Per-record work only. Anything that spans records belongs in metrics.py.
"""

from dataclasses import dataclass, field

from eval.normalize import COMPARED_FIELDS, SILENCE_MEANS_FALSE, compare
from worker.extraction.extractor import SCALAR_FIELDS

# Everything extraction may fill in, dotted where nested — the same list
# extractor.filled_field_names() walks. Imported rather than repeated so the two
# cannot drift: `filled_fields` is the denominator of the unsupported-value
# rate, and a denominator that quietly changes is a broken metric.
#
# The 2026-08-02 archive counted a narrower set: 6.84 filled fields per record
# against 8.29 here, consistent with the two nested location fields not being
# counted there. The unsupported-value *rate* therefore does not compare across
# that boundary; the count does — 27 there, 28 here, over the same 100 records.
FILLABLE_FIELDS = (*SCALAR_FIELDS, "incident_location.city", "incident_location.district")

# The subset of FILLABLE_FIELDS the missing-field metric can actually judge.
# `injury` and `counterparty_exists` are excluded: the ground truth writes False
# rather than null when the text is silent (normalize.SILENCE_MEANS_FALSE), so
# they are never null in the answer key, while the model correctly reports them
# as missing. Scoring them here contradicts the accuracy metric, which counts
# that same null as a hit. Measured 2026-08-04 on the paired 100-record run:
# they produced 100 of the 105 false positives, holding precision at 35%.
MISSING_METRIC_FIELDS = tuple(name for name in FILLABLE_FIELDS if name not in SILENCE_MEANS_FALSE)


@dataclass(frozen=True)
class FieldScore:
    """What the answer key said, what the model said, and whether they agree."""

    gt: object
    llm: object
    hit: bool


@dataclass(frozen=True)
class RecordScore:
    """One record's result, ready to aggregate or to write out as JSON."""

    gt_id: str
    channel: str
    fields: dict[str, FieldScore]
    hits: int
    filled_fields: int
    unverified_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    expected_missing: list[str] = field(default_factory=list)
    duration_ms: int | None = None
    reasoning: str = ""

    # The full pair the score was derived from. Kept because a metric nobody has
    # written yet cannot be added afterwards otherwise: damage_description is
    # free text, is not among COMPARED_FIELDS, and was therefore absent from the
    # 2026-08-04 run — measuring it would have meant paying for the model again.
    # The answer key is stored too, so a result stays readable after the corpus
    # is regenerated, which text_generator.py does wholesale (991 of 1000
    # records in PR #25).
    expected: dict = field(default_factory=dict)
    extraction: dict = field(default_factory=dict)


def dotted_value(data: dict, name: str) -> object:
    """Read a possibly nested field by its dotted name."""
    if "." not in name:
        return data.get(name)
    parent, child = name.split(".", 1)
    nested = data.get(parent)
    return nested.get(child) if isinstance(nested, dict) else None


def filled_names(extraction: dict) -> list[str]:
    """Fields the model actually filled in."""
    return [name for name in FILLABLE_FIELDS if dotted_value(extraction, name) is not None]


def null_names(expected: dict) -> list[str]:
    """Fields the answer key leaves null.

    IhbarKokpiti-Veri-Kontrati.md 3.1: a field that is null in the ground truth
    counts as missing, and the model's own `missing_fields` is measured against
    exactly this set.
    """
    return [name for name in FILLABLE_FIELDS if dotted_value(expected, name) is None]


def score_record(
    gt_id: str,
    channel: str,
    expected: dict,
    extraction: dict,
    *,
    unverified_fields: list[str] | None = None,
    duration_ms: int | None = None,
    reasoning: str = "",
) -> RecordScore:
    """Compare one extraction with its answer key, field by field."""
    fields: dict[str, FieldScore] = {}
    hits = 0
    for name in COMPARED_FIELDS:
        gt = expected.get(name)
        llm = extraction.get(name)
        hit = compare(name, gt, llm)
        fields[name] = FieldScore(gt=gt, llm=llm, hit=hit)
        hits += int(hit)

    return RecordScore(
        gt_id=gt_id,
        channel=channel,
        fields=fields,
        hits=hits,
        filled_fields=len(filled_names(extraction)),
        unverified_fields=sorted(unverified_fields or []),
        missing_fields=sorted(extraction.get("missing_fields") or []),
        expected_missing=null_names(expected),
        duration_ms=duration_ms,
        reasoning=reasoning,
        expected=expected,
        extraction=extraction,
    )


def to_dict(score: RecordScore) -> dict:
    """Serialize in the archive's shape so old and new runs read the same."""
    return {
        "gt_id": score.gt_id,
        "channel": score.channel,
        "fields": {
            name: {"gt": value.gt, "llm": value.llm, "hit": value.hit}
            for name, value in score.fields.items()
        },
        "hits": score.hits,
        "filled_fields": score.filled_fields,
        "unverified_fields": score.unverified_fields,
        "missing_fields": score.missing_fields,
        "expected_missing": score.expected_missing,
        "duration_ms": score.duration_ms,
        "reasoning": score.reasoning,
        "expected": score.expected,
        "extraction": score.extraction,
    }


def from_dict(raw: dict) -> RecordScore:
    """Read a result written by this code or by the 2026-08-02 measurement runs.

    `hit` is recomputed from the stored `gt` and `llm` rather than trusted, so a
    change to a normalization rule re-scores every past run — which is the whole
    reason the raw per-record answers are written out. `hits` follows from the
    fields actually present, so a trimmed file stays self-consistent.

    The archived runs predate `missing_fields`, `expected_missing`, `expected`
    and `extraction`, so those come back empty. metrics.py reports the
    missing-field metric as unavailable rather than as zero when they are — an
    absent measurement is not a bad score.
    """
    fields = {
        name: FieldScore(
            gt=value["gt"],
            llm=value["llm"],
            hit=compare(name, value["gt"], value["llm"]),
        )
        for name, value in raw["fields"].items()
    }
    return RecordScore(
        gt_id=raw["gt_id"],
        channel=raw["channel"],
        fields=fields,
        hits=sum(value.hit for value in fields.values()),
        filled_fields=raw.get("filled_fields", 0),
        unverified_fields=list(raw.get("unverified_fields") or []),
        missing_fields=list(raw.get("missing_fields") or []),
        expected_missing=list(raw.get("expected_missing") or []),
        duration_ms=raw.get("duration_ms"),
        reasoning=raw.get("reasoning", ""),
        expected=raw.get("expected") or {},
        extraction=raw.get("extraction") or {},
    )
