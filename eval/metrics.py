# eval/metrics.py
"""Aggregates record scores into the reported metrics.

Design doc 6.2, the three the corpus can currently support:
  1  field-level extraction accuracy   overall, per field, per channel
  4  unsupported-value rate            filled values with no quote found in the text
  +  missing-field detection           the model's `missing_fields` against the
                                       ground truth's nulls (data contract 3.1)

Metrics 2, 3 and 5 (content type, triage, critical recall) are deliberately
absent. The corpus labels them at random — data/gt_generator.py:139 draws
content_type from a weighted choice and data/text_generator.py never reads it —
so any number computed for them would describe the dice, not the model. They
land once the corpus does.
"""

from dataclasses import dataclass, field

from eval.normalize import COMPARED_FIELDS
from eval.scoring import MISSING_METRIC_FIELDS, RecordScore


@dataclass(frozen=True)
class Ratio:
    """A hit count over a total, carried together so a rate is never orphaned."""

    hits: int
    total: int

    @property
    def rate(self) -> float:
        """Share of hits, or 0.0 when nothing was measured."""
        return self.hits / self.total if self.total else 0.0

    def __str__(self) -> str:
        return f"{self.rate:.2%} ({self.hits}/{self.total})"


@dataclass(frozen=True)
class MissingFieldScore:
    """How well the model reports the fields it left null.

    `available` is False when the results carry no missing-field data at all —
    the archived 2026-08-02 runs predate it. An absent measurement is reported
    as absent, never as a zero.
    """

    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    available: bool = True

    @property
    def precision(self) -> float:
        claimed = self.true_positives + self.false_positives
        return self.true_positives / claimed if claimed else 0.0

    @property
    def recall(self) -> float:
        actual = self.true_positives + self.false_negatives
        return self.true_positives / actual if actual else 0.0

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0


@dataclass(frozen=True)
class Miss:
    """One field the model got wrong — the raw material for error analysis."""

    gt_id: str
    channel: str
    field: str
    gt: object
    llm: object


@dataclass(frozen=True)
class Report:
    """Everything one run measured."""

    records: int
    field_accuracy: Ratio
    per_field: dict[str, Ratio]
    per_channel: dict[str, Ratio]
    unsupported: Ratio
    missing_detection: MissingFieldScore
    misses: list[Miss] = field(default_factory=list)

    @property
    def noise_floor(self) -> float:
        """One field either way, as a share of the total compared.

        Measured 2026-08-02: with temperature 0 and a pinned seed, a repeated
        run still moves by about a field. Differences below this are not
        results, and the report prints it next to the accuracy for that reason.
        """
        return 1 / self.field_accuracy.total if self.field_accuracy.total else 0.0


def build_report(scores: list[RecordScore]) -> Report:
    """Aggregate per-record scores into the reported metrics."""
    per_field = {
        name: Ratio(
            hits=sum(1 for score in scores if score.fields[name].hit),
            total=sum(1 for score in scores if name in score.fields),
        )
        for name in COMPARED_FIELDS
        if any(name in score.fields for score in scores)
    }

    channels = sorted({score.channel for score in scores})
    per_channel = {
        channel: Ratio(
            hits=sum(score.hits for score in scores if score.channel == channel),
            total=sum(len(score.fields) for score in scores if score.channel == channel),
        )
        for channel in channels
    }

    misses = [
        Miss(
            gt_id=score.gt_id,
            channel=score.channel,
            field=name,
            gt=value.gt,
            llm=value.llm,
        )
        for score in scores
        for name, value in score.fields.items()
        if not value.hit
    ]

    return Report(
        records=len(scores),
        field_accuracy=Ratio(
            hits=sum(score.hits for score in scores),
            total=sum(len(score.fields) for score in scores),
        ),
        per_field=per_field,
        per_channel=per_channel,
        unsupported=Ratio(
            hits=sum(len(score.unverified_fields) for score in scores),
            total=sum(score.filled_fields for score in scores),
        ),
        missing_detection=_missing_detection(scores),
        misses=misses,
    )


def _missing_detection(scores: list[RecordScore]) -> MissingFieldScore:
    """Compare what the model said it left out with what the answer key omits.

    Restricted to the fields this metric can judge; scoring.MISSING_METRIC_FIELDS
    records why two of them are not among those. Filtering here rather than at
    scoring time keeps the per-record file a faithful record of what the model
    said, and lets an already-paid-for run be re-scored under the corrected rule.
    """
    measurable = set(MISSING_METRIC_FIELDS)
    pairs = [
        (set(score.missing_fields) & measurable, set(score.expected_missing) & measurable)
        for score in scores
    ]
    if not any(claimed or actual for claimed, actual in pairs):
        return MissingFieldScore(available=False)

    return MissingFieldScore(
        true_positives=sum(len(claimed & actual) for claimed, actual in pairs),
        false_positives=sum(len(claimed - actual) for claimed, actual in pairs),
        false_negatives=sum(len(actual - claimed) for claimed, actual in pairs),
    )


def format_report(report: Report, *, max_misses: int = 20) -> str:
    """Render a report for the console.

    Targets come from CLAUDE.md 7; they are printed beside the measurement so a
    number is never read without the bar it has to clear.
    """
    lines = [
        f"records            {report.records}",
        f"field accuracy     {report.field_accuracy}   target >= 82%",
        f"unsupported values {report.unsupported}   target <= 7%",
        f"noise floor        +/-{report.noise_floor:.2%} (one field)",
        "",
        "per channel",
    ]
    lines += [f"  {channel:<16} {ratio}" for channel, ratio in report.per_channel.items()]

    lines += ["", "per field"]
    lines += [f"  {name:<21} {ratio}" for name, ratio in report.per_field.items()]

    lines += ["", "missing-field detection"]
    detection = report.missing_detection
    if not detection.available:
        lines.append("  not available in this result set")
    else:
        lines.append(
            f"  precision {detection.precision:.2%}  recall {detection.recall:.2%}  "
            f"f1 {detection.f1:.2%}"
        )

    if report.misses:
        lines += ["", f"misses ({len(report.misses)})"]
        for miss in report.misses[:max_misses]:
            lines.append(f"  {miss.gt_id}  {miss.field:<21} gt={miss.gt!r} llm={miss.llm!r}")
        if len(report.misses) > max_misses:
            lines.append(f"  ... {len(report.misses) - max_misses} more")

    return "\n".join(lines)
