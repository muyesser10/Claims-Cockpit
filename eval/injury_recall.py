# eval/injury_recall.py
"""Critical-urgency recall on injury phrasings the corpus does not contain.

CLAUDE.md §7 wants >= 97% critical recall, and the pinned corpus reports 100%.
That number is measured on an easy case, and the reason is structural rather than
accidental: data/gt_generator.py decides `injury` first and forces `critical`
from it, and data/dictionaries/urgency_phrases.json gives every critical record
one of four urgency cues - all four of which contain a canonical injury term
("araçta yaralı var", "yaralanma söz konusu", ...). So every critical record in
the corpus carries a dictionary word in boilerplate, whatever its injury
sentence says. Measured: 80/80 injuries found, and in the email channel not one
of them was found via the injury sentence - all 38 matched on the urgency cue.

This fixture is the other half. Three groups, each answering a different
question:

  non_canonical           A real injury described without any of the twelve
                          terms ("kolu kırıldı", "112'yi aradık", "bayıldı").
                          The deterministic rule is expected to score ~0 here;
                          what matters is what the LLM path adds, because that
                          difference IS the cost of the LLM being down.

  ascii_fold              The right stem written without Turkish characters
                          ("yarali var"). Known gap, never quantified.

  false_positive_control  No injury, but a word that starts with a term
                          ("kanal", "kanaat", "bilinçli"). Known gap #1. This
                          group is why the fixture is not a recall-only test:
                          the override is an OR, so a deterministic false
                          positive cannot be corrected by the model - it becomes
                          a false critical every time. Any fix to the matcher
                          has to be paid for here.

Together those are the two measurements docs/STATUS.md says the injury_terms.py
fix is waiting on.

    python -m eval.injury_recall              # deterministic only, free
    python -m eval.injury_recall --live       # + the classifier, ~34 calls
"""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from worker.classification.schema import Urgency
from worker.llm.client import ModelTier
from worker.shared.injury_terms import find_injury_signals

# Same reason as eval/__main__.py: worker/llm/client.py reads os.environ, and a
# person running this from a shell has not loaded .env.
load_dotenv()

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "injury_phrasings.jsonl"

GROUPS = ("non_canonical", "ascii_fold", "false_positive_control")


def default_prompt_name() -> str:
    """The prompt classifier.py reads when none is given.

    Imported inside the function for the same reason `classify` is: the offline
    path must not need an API key, and the client module sits behind this import.
    """
    from worker.classification.classifier import PROMPT_PATH

    return PROMPT_PATH.name


@dataclass
class Case:
    id: str
    group: str
    injury: bool
    channel: str
    text: str
    note: str
    # Which half this case belongs to. `tune` are the cases prompt and dictionary
    # work was done while looking at; `holdout` were written without running
    # anything against them. Both numbers are reported, and only the second one
    # estimates reach rather than fit. Defaulted so a fixture written before the
    # split still loads.
    split: str = "tune"


@dataclass
class Outcome:
    case: Case
    signals: list[str]
    # None when the run was offline: absence of an answer, not a negative one.
    critical: bool | None = None
    llm_urgency: str | None = None
    # The quote the model offered as proof of injury, and whether it is really in
    # the text. A prompt that asks for evidence is only worth anything if the
    # evidence is real; an invented quote is the same failure extraction guards
    # against, arriving through a different field.
    injury_evidence: str | None = None
    evidence_found: bool | None = None

    @property
    def deterministic(self) -> bool:
        return bool(self.signals)

    @property
    def llm_only(self) -> bool:
        """Reached critical without a term matching - so the model's path did it."""
        return self.critical is True and not self.signals


def load_cases(path: Path = FIXTURE) -> list[Case]:
    with path.open(encoding="utf-8") as handle:
        return [Case(**json.loads(line)) for line in handle if line.strip()]


def run(
    cases: list[Case],
    *,
    live: bool,
    seed: int,
    tier: ModelTier,
    system_prompt: str | None = None,
) -> list[Outcome]:
    """Deterministic rule for every case; the classifier too when `live`.

    `system_prompt` overrides the versioned file classifier.py would read, so two
    prompt variants can be compared on one fixture at one seed. Switching the
    default is a decision that should follow the measurement rather than precede
    it, and without this there is no way to run the measurement.
    """
    outcomes = []
    for index, case in enumerate(cases, start=1):
        outcome = Outcome(case=case, signals=find_injury_signals(case.text))
        if live:
            # Imported lazily so the offline path needs no API key.
            from worker.classification.classifier import classify

            print(f"  {index}/{len(cases)} {case.id}", end="\r", file=sys.stderr)
            result = classify(
                case.text,
                case.channel,
                message_id=f"injury-recall-{case.id}",
                seed=seed,
                tier=tier,
                system_prompt=system_prompt,
            )
            outcome.critical = result.urgency is Urgency.CRITICAL
            outcome.llm_urgency = str(result.llm_urgency)
            outcome.injury_evidence = result.injury_evidence
            if result.injury_evidence:
                # Same locator extraction uses, rather than a second rule: exact
                # match, then the same words across reflowed whitespace.
                from worker.extraction.extractor import locate_quote

                outcome.evidence_found = locate_quote(result.injury_evidence, case.text) is not None
        outcomes.append(outcome)
    return outcomes


def _rate(part: int, whole: int) -> str:
    return f"{part}/{whole} = {part / whole:6.1%}" if whole else f"{part}/0 =      -"


def format_report(outcomes: list[Outcome], *, live: bool) -> str:
    lines: list[str] = []
    by_group = {group: [o for o in outcomes if o.case.group == group] for group in GROUPS}

    for group in GROUPS:
        items = by_group[group]
        if not items:
            continue
        positive = group != "false_positive_control"
        lines.append(f"--- {group}  (n={len(items)}) ---")
        det = sum(o.deterministic for o in items)
        if positive:
            lines.append(f"  deterministic rule caught   {_rate(det, len(items))}")
            if live:
                final = sum(o.critical is True for o in items)
                lines.append(f"  pipeline reached critical   {_rate(final, len(items))}")
                lines.append(f"  model-only saves            {sum(o.llm_only for o in items)}")
        else:
            lines.append(f"  deterministic false fires   {_rate(det, len(items))}")
            if live:
                final = sum(o.critical is True for o in items)
                lines.append(f"  false criticals (end-end)   {_rate(final, len(items))}")
        for o in items:
            mark = "FIRE" if o.deterministic else "   ."
            crit = "" if not live else ("  critical" if o.critical else "  ok")
            terms = ",".join(o.signals)
            lines.append(f"    {mark} {o.case.id}{crit}  {terms:<20} {o.case.text[:52]}")
        lines.append("")

    # The headline: recall over both hard positive groups, and what the fallback
    # keeps when the model is unreachable. Split three ways, because a number
    # measured on the cases the rules were written against says how well they
    # were written, not how far they reach.
    hard = by_group["non_canonical"] + by_group["ascii_fold"]
    controls = by_group["false_positive_control"]
    lines.append("=" * 72)

    for split in ("tune", "holdout", None):
        positives = [o for o in hard if split is None or o.case.split == split]
        negatives = [o for o in controls if split is None or o.case.split == split]
        if not positives and not negatives:
            continue

        label = "all" if split is None else split
        det = sum(o.deterministic for o in positives)
        lines.append(f"{label:<8} hard positives n={len(positives)}, controls n={len(negatives)}")
        lines.append(f"  deterministic recall (= fallback)   {_rate(det, len(positives))}")
        if live:
            final = sum(o.critical is True for o in positives)
            lines.append(f"  pipeline recall (rule OR model)    {_rate(final, len(positives))}")
            lines.append(f"  lost if the LLM is down            {final - det} of {len(positives)}")
        false_fires = sum(o.deterministic for o in negatives)
        lines.append(f"  deterministic false criticals      {_rate(false_fires, len(negatives))}")
        if live:
            false_end = sum(o.critical is True for o in negatives)
            lines.append(f"  end-to-end false criticals         {_rate(false_end, len(negatives))}")
        lines.append("")

    if live:
        quoted = [o for o in outcomes if o.injury_evidence]
        if quoted:
            real = sum(1 for o in quoted if o.evidence_found)
            lines.append(f"evidence quotes offered {len(quoted)}, found in the text {real}")
            for o in quoted:
                if not o.evidence_found:
                    lines.append(f"    NOT FOUND {o.case.id}  {o.injury_evidence!r}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.injury_recall", description=__doc__)
    parser.add_argument("--live", action="store_true", help="also call the classifier")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--tier", choices=[t.value for t in ModelTier], default=ModelTier.CHEAP.value
    )
    parser.add_argument(
        "--prompt",
        type=Path,
        default=None,
        help="classification prompt to use instead of the one classifier.py reads",
    )
    parser.add_argument(
        "--split", choices=("tune", "holdout"), default=None, help="only one half of the fixture"
    )
    parser.add_argument("--out", type=Path, default=None, help="write raw outcomes as JSON")
    args = parser.parse_args(argv)

    cases = load_cases()
    if args.split:
        cases = [case for case in cases if case.split == args.split]
    if args.live:
        print(f"about to call the model for {len(cases)} cases", file=sys.stderr)

    system_prompt = args.prompt.read_text(encoding="utf-8") if args.prompt else None
    outcomes = run(
        cases,
        live=args.live,
        seed=args.seed,
        tier=ModelTier(args.tier),
        system_prompt=system_prompt,
    )
    print(format_report(outcomes, live=args.live))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(
                {
                    # Which prompt produced these answers. The repo versions its
                    # prompts and its runs did not record which version they were
                    # measured with, so a number could not be traced back to the
                    # text that produced it.
                    "meta": {
                        "run_at": datetime.now(UTC).isoformat(),
                        "live": args.live,
                        "seed": args.seed,
                        "tier": args.tier,
                        "prompt": args.prompt.name if args.prompt else default_prompt_name(),
                        "cases": len(outcomes),
                    },
                    "outcomes": [
                        {
                            "id": o.case.id,
                            "group": o.case.group,
                            "split": o.case.split,
                            "injury": o.case.injury,
                            "text": o.case.text,
                            "signals": o.signals,
                            "critical": o.critical,
                            "llm_urgency": o.llm_urgency,
                            "injury_evidence": o.injury_evidence,
                            "evidence_found": o.evidence_found,
                        }
                        for o in outcomes
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nwritten to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
