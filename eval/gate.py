# eval/gate.py
"""Measures the auto-approval gate against ground truth.

worker/routing/auto_approve.py ships closed, because CLAUDE.md §7 asks for >= 95%
precision and no run had measured it. This is that run.

Precision here means what it means to an operator who never sees the claim: of
the claims the gate approved unattended, how many were right in every compared
field. Not "mostly right" - a claim approved with one invented field is a wrong
claim that nobody will read.

Coverage is reported beside it and is the reason precision alone cannot decide
anything. A gate that approves two claims out of a hundred can hit any precision
target you like and has not automated anything, so the pair has to be read
together. Precision over zero approvals is reported as None rather than 100%,
which is the same fact stated honestly.

The run mirrors the pipeline: mask, classify, extract from the masked copy only
when the verdict is `claim`, unmask, validate. Skipping the mask, or extracting
from raw text, would measure a system nobody runs.
"""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from eval.loader import EvalRecord
from eval.scoring import score_record
from worker.classification.classifier import PROMPT_PATH as CLASSIFICATION_PROMPT_PATH
from worker.classification.classifier import classify
from worker.extraction.extractor import PROMPT_PATH as EXTRACTION_PROMPT_PATH
from worker.extraction.extractor import extract
from worker.llm.client import LlmClient, ModelTier
from worker.masking.pipeline import mask_all
from worker.masking.unmask import unmask_data
from worker.routing.auto_approve import ADVISORY_RULES, evaluate
from worker.validation.validator import validate

RESULTS_DIR = Path(__file__).resolve().parent / "results"


@dataclass(frozen=True)
class GateRecord:
    """One record, reduced to what the gate reads plus whether it was right.

    Held rather than recomputed so a candidate sweep costs nothing: the LLM calls
    happen once, and every advisory set after that is arithmetic over this.
    """

    gt_id: str
    channel: str
    content_type: str
    urgency: str
    validation_flags: list[dict]
    unverified_fields: list[str]
    extraction_present: bool
    # Every compared field matched the answer key. The bar for a claim nobody
    # will read.
    correct: bool
    # What the answer key said, kept for the classification report and so a
    # disagreement can be looked at rather than guessed at.
    expected_content_type: str | None = None
    expected_urgency: str | None = None
    hits: int = 0
    scored_fields: int = 0


@dataclass
class GateRunOutcome:
    """A live run's records, and the ones that never produced any."""

    records: list[GateRecord] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    model: str = ""
    masked: bool = True


@dataclass(frozen=True)
class GateMeasurement:
    """What one advisory set achieves over one run."""

    label: str
    advisory_rules: list[str]
    total: int
    approved: int
    correct: int
    # The approved claims that were not right. Named rather than counted: a
    # precision number nobody can trace back to a record is not actionable.
    wrong_ids: list[str]
    # Why the rest were held, most common first. This is what says which rule is
    # the bottleneck, and therefore which one is worth measuring as advisory.
    reasons: dict[str, int]

    @property
    def coverage(self) -> float:
        """Share of records the gate approved."""
        return self.approved / self.total if self.total else 0.0

    @property
    def precision(self) -> float | None:
        """Share of approved claims that were right, or None if none were approved.

        None rather than 1.0. A gate that approves nothing has not earned a
        perfect score, and reporting one would let a broken candidate win a
        sweep.
        """
        return self.correct / self.approved if self.approved else None


def build_record(
    record: EvalRecord,
    *,
    client: LlmClient,
    tier: ModelTier = ModelTier.CHEAP,
    seed: int | None = None,
) -> GateRecord:
    """Run one record through the pipeline's steps and reduce it to a GateRecord.

    Extraction is skipped for non-claims, as step_extract skips them. Running it
    anyway would measure a call production does not make and would hand the gate
    an extraction it would never have had.
    """
    masked_text, mappings = mask_all(record.text)

    classification = classify(
        masked_text,
        record.channel,
        message_id=record.gt_id,
        client=client,
        tier=tier,
        seed=seed,
    )
    content_type = str(classification.content_type)
    urgency = str(classification.urgency)

    expected = record.expected or {}

    if content_type != "claim":
        return GateRecord(
            gt_id=record.gt_id,
            channel=record.channel,
            content_type=content_type,
            urgency=urgency,
            validation_flags=[],
            unverified_fields=[],
            extraction_present=False,
            correct=False,
            expected_content_type=expected.get("content_type"),
            expected_urgency=expected.get("urgency"),
        )

    result = extract(
        masked_text,
        record.received_at,
        record.channel,
        message_id=record.gt_id,
        client=client,
        tier=tier,
        seed=seed,
    )
    extraction = unmask_data(result.extraction, mappings)

    merged = {**extraction, "urgency": urgency, "content_type": content_type}
    flags = validate(merged, masked_text)

    score = score_record(
        record.gt_id,
        record.channel,
        record.expected,
        extraction,
        unverified_fields=result.unverified_fields,
        duration_ms=result.duration_ms,
        reasoning=result.reasoning,
    )
    scored = list(score.fields.values())

    return GateRecord(
        gt_id=record.gt_id,
        channel=record.channel,
        content_type=content_type,
        urgency=urgency,
        validation_flags=flags,
        unverified_fields=result.unverified_fields,
        extraction_present=True,
        correct=bool(scored) and all(item.hit for item in scored),
        expected_content_type=expected.get("content_type"),
        expected_urgency=expected.get("urgency"),
        hits=score.hits,
        scored_fields=len(scored),
    )


def run_live(
    records: list[EvalRecord],
    *,
    client: LlmClient | None = None,
    tier: ModelTier = ModelTier.CHEAP,
    seed: int | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> GateRunOutcome:
    """Build a GateRecord for every record, keeping going when one fails.

    Costs two cheap-tier calls per claim and one per non-claim. A failure is
    recorded rather than dropped: a run that quietly scored 97 of 100 and
    reported an average is the dishonest version of this.
    """
    client = client or LlmClient()
    outcome = GateRunOutcome(model=client.settings.model_for(tier))

    for index, record in enumerate(records, start=1):
        try:
            outcome.records.append(build_record(record, client=client, tier=tier, seed=seed))
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            outcome.failures.append((record.gt_id, f"{type(exc).__name__}: {exc}"))
        if on_progress is not None:
            on_progress(index, len(records), record.gt_id)

    return outcome


def measure(
    records: list[GateRecord],
    *,
    label: str = "shipped",
    advisory_rules: frozenset[str] = ADVISORY_RULES,
) -> GateMeasurement:
    """Apply one advisory set to a finished run.

    `enabled=True` is forced. The environment flag says whether the gate is
    switched on in production; it has nothing to say about what the gate would
    achieve, which is the whole question here.
    """
    approved_ids: list[str] = []
    wrong_ids: list[str] = []
    reasons: dict[str, int] = {}

    for item in records:
        decision = evaluate(
            content_type=item.content_type,
            urgency=item.urgency,
            validation_flags=item.validation_flags,
            unverified_fields=item.unverified_fields,
            has_sanity_flags=False,
            extraction_present=item.extraction_present,
            enabled=True,
            advisory_rules=advisory_rules,
        )
        if decision.approved:
            approved_ids.append(item.gt_id)
            if not item.correct:
                wrong_ids.append(item.gt_id)
        else:
            for reason in decision.reasons:
                reasons[reason] = reasons.get(reason, 0) + 1

    return GateMeasurement(
        label=label,
        advisory_rules=sorted(advisory_rules),
        total=len(records),
        approved=len(approved_ids),
        correct=len(approved_ids) - len(wrong_ids),
        wrong_ids=wrong_ids,
        reasons=dict(sorted(reasons.items(), key=lambda pair: -pair[1])),
    )


def sweep(
    records: list[GateRecord],
    candidates: dict[str, frozenset[str]],
) -> list[GateMeasurement]:
    """Measure several advisory sets over one run.

    The point of the exercise: moving a rule between blocking and advisory is a
    claim about the system, and this is what turns it into a number instead.
    """
    return [
        measure(records, label=label, advisory_rules=rules) for label, rules in candidates.items()
    ]


def blocking_rule_names(records: list[GateRecord]) -> dict[str, int]:
    """How often each validation rule fired, most common first.

    Read before choosing candidates: a rule that never fires cannot change
    coverage, and moving it to advisory would be a decision about nothing.
    """
    counts: dict[str, int] = {}
    for item in records:
        for rule in {flag.get("rule") for flag in item.validation_flags if flag.get("rule")}:
            counts[rule] = counts.get(rule, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: -pair[1]))


def candidate_sets(records: list[GateRecord], *, top: int = 3) -> dict[str, frozenset[str]]:
    """The advisory sets worth measuring, drawn from what actually fired.

    A hardcoded list of candidates would measure someone's imagination rather
    than the corpus. `strict` and `shipped` anchor the two ends; each remaining
    candidate adds one frequently-firing rule to the shipped set, so every row
    of the table reads as "what would forgiving this one rule buy, and what
    would it cost".

    Rules that never fired are left out. Moving one of those between blocking
    and advisory cannot change a number, so measuring it would be a decision
    about nothing.
    """
    counts = blocking_rule_names(records)
    ranked = [rule for rule in counts if rule not in ADVISORY_RULES][:top]

    candidates: dict[str, frozenset[str]] = {
        "strict": frozenset(),
        "shipped": ADVISORY_RULES,
    }
    for rule in ranked:
        candidates[f"shipped+{rule}"] = ADVISORY_RULES | {rule}
    return candidates


def write_run(
    outcome: GateRunOutcome,
    path: Path | None = None,
    *,
    meta: dict | None = None,
) -> Path:
    """Write the per-record facts plus the settings that produced them.

    Written out because the sweep is free and the run is not: every candidate
    set after the first is arithmetic over this file.
    """
    path = path or RESULTS_DIR / f"gate_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "run_at": datetime.now(UTC).isoformat(),
            "model": outcome.model,
            "records": len(outcome.records),
            "failures": outcome.failures,
            "masked": outcome.masked,
            # Both prompts, because this run uses both and either one moving
            # changes the numbers. Recorded after a classification prompt was
            # replaced and two committed §7 rows silently became measurements of
            # a prompt that no longer ships.
            "prompts": {
                "classification": CLASSIFICATION_PROMPT_PATH.name,
                "extraction": EXTRACTION_PROMPT_PATH.name,
            },
            **(meta or {}),
        },
        "records": [asdict(item) for item in outcome.records],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_run(path: Path) -> list[GateRecord]:
    """Read a run written by write_run."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [GateRecord(**item) for item in raw["records"]]


def format_measurements(measurements: list[GateMeasurement]) -> str:
    """A table an operator or a standup can read.

    Coverage sits next to precision in every row on purpose: neither number
    means anything on its own.
    """
    # Wide enough for "shipped+" plus the longest rule name; a candidate label
    # that overflows its column misaligns every row after it.
    width = max([len("candidate"), *(len(item.label) for item in measurements)]) + 2
    lines = [
        f"{'candidate':<{width}} {'approved':>9} {'coverage':>9} {'precision':>10}",
        "-" * (width + 31),
    ]
    for item in measurements:
        precision = "n/a" if item.precision is None else f"{item.precision:.1%}"
        lines.append(
            f"{item.label:<{width}} {item.approved:>4}/{item.total:<4} "
            f"{item.coverage:>8.1%} {precision:>10}"
        )
    return "\n".join(lines)
