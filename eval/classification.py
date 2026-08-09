# eval/classification.py
"""Macro-F1 for content type and urgency, over a gate run.

CLAUDE.md §7 asks for >= 85% classification macro-F1. Until the classifier was
wired into the pipeline the number could not be computed at all: `content_type`
was the literal "claim" and `high` was never produced, so a macro average over
those classes would have been an average over classes the system could not emit.

Macro rather than micro, deliberately, and it is the harder number. Micro-F1
would be dominated by `claim` and `normal`, which are most of the corpus; the
classes that matter for triage - `high`, and the two non-claim types - are the
rare ones, and macro weights each class equally regardless of how few there are.
A system that answered "claim, normal" to everything would score well on micro
and badly here, which is the correct verdict on it.
"""

from dataclasses import dataclass, field

from eval.gate import GateRecord

# Which GateRecord field holds the answer key for each prediction.
FIELDS = {
    "content_type": ("content_type", "expected_content_type"),
    "urgency": ("urgency", "expected_urgency"),
}


@dataclass(frozen=True)
class ClassScore:
    """One class's result. `support` is how many records truly are this class."""

    label: str
    support: int
    predicted: int
    true_positives: int

    @property
    def precision(self) -> float:
        """Of the records called this class, how many were."""
        return self.true_positives / self.predicted if self.predicted else 0.0

    @property
    def recall(self) -> float:
        """Of the records that are this class, how many were found."""
        return self.true_positives / self.support if self.support else 0.0

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0


@dataclass(frozen=True)
class ClassificationReport:
    """One field's scores, plus what could not be scored."""

    field_name: str
    classes: list[ClassScore]
    scored: int
    # Records whose answer key has no value for this field. Reported rather than
    # quietly dropped: a macro-F1 over 40 of 100 records is a different number
    # from one over 100, and nothing in the average says which it was.
    unscorable: int
    # Every (expected, predicted) pair that disagreed, most common first. This is
    # what turns "macro-F1 is 0.71" into something anyone can act on.
    confusions: dict[str, int] = field(default_factory=dict)

    @property
    def macro_f1(self) -> float:
        """Mean F1 across classes, each weighted the same."""
        return sum(item.f1 for item in self.classes) / len(self.classes) if self.classes else 0.0

    @property
    def accuracy(self) -> float:
        hits = sum(item.true_positives for item in self.classes)
        return hits / self.scored if self.scored else 0.0


def build_report(records: list[GateRecord], field_name: str) -> ClassificationReport:
    """Score one field over a run.

    Classes are taken from the union of what the answer key holds and what the
    model produced. A class the model invents therefore lowers the average
    rather than being ignored, and a class the model never produces shows up as
    F1 zero with its real support beside it.
    """
    predicted_attr, expected_attr = FIELDS[field_name]

    pairs: list[tuple[str, str]] = []
    unscorable = 0
    for item in records:
        expected = getattr(item, expected_attr)
        if expected is None:
            unscorable += 1
            continue
        pairs.append((expected, getattr(item, predicted_attr)))

    labels = sorted({label for pair in pairs for label in pair})
    classes = [
        ClassScore(
            label=label,
            support=sum(1 for expected, _ in pairs if expected == label),
            predicted=sum(1 for _, actual in pairs if actual == label),
            true_positives=sum(1 for expected, actual in pairs if expected == actual == label),
        )
        for label in labels
    ]

    confusions: dict[str, int] = {}
    for expected, actual in pairs:
        if expected != actual:
            key = f"{expected} -> {actual}"
            confusions[key] = confusions.get(key, 0) + 1

    return ClassificationReport(
        field_name=field_name,
        classes=classes,
        scored=len(pairs),
        unscorable=unscorable,
        confusions=dict(sorted(confusions.items(), key=lambda pair: -pair[1])),
    )


def build_reports(records: list[GateRecord]) -> list[ClassificationReport]:
    """Both fields, in the order §7 lists them."""
    return [build_report(records, name) for name in FIELDS]


def format_report(report: ClassificationReport) -> str:
    """A table for a standup, with support beside every class.

    Support is not decoration: an F1 of 0.0 over a support of 1 and the same
    number over a support of 40 are different findings, and a column of bare
    scores hides which one you are looking at.
    """
    lines = [
        f"{report.field_name}  (macro-F1 {report.macro_f1:.1%}, accuracy {report.accuracy:.1%}, "
        f"n={report.scored}"
        + (f", {report.unscorable} unscorable" if report.unscorable else "")
        + ")",
        f"  {'class':<16} {'support':>8} {'precision':>10} {'recall':>8} {'f1':>8}",
    ]
    for item in report.classes:
        lines.append(
            f"  {item.label:<16} {item.support:>8} {item.precision:>9.1%} "
            f"{item.recall:>7.1%} {item.f1:>7.1%}"
        )
    if report.confusions:
        lines.append(
            "  confusions: " + ", ".join(f"{k} ×{v}" for k, v in report.confusions.items())
        )
    return "\n".join(lines)
