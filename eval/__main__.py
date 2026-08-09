# eval/__main__.py
"""Command line entry point.

    python -m eval --score eval/results/run_20260802T120000Z.json
    python -m eval --run --seed 42
    python -m eval --run --mix email=3,call_transcript=2,web_form=1
    python -m eval --gate --seed 42
    python -m eval --gate-score eval/results/gate_20260808T120000Z.json

`--score` and `--gate-score` are free and offline. `--run` and `--gate` call the
model and cost money, so they print the sample they are about to buy before they
start.

`--run` measures extraction alone. `--gate` runs classification and extraction
together, which is what the auto-approval gate reads, and reports four of
CLAUDE.md §7's targets off one sample: field accuracy, the unsupported-value
rate, classification macro-F1, and auto-approval precision against coverage. The
run is the expensive part; every candidate advisory set after the first is
arithmetic over the file it writes.

`--run` without `--mix` uses the pinned baseline sample
(eval/fixtures/baseline_100_ids.json), which is what keeps successive runs
comparable with each other. `--mix` draws a fresh random sample instead — for a
smoke test, not for a measurement anyone intends to compare.
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from eval import gate
from eval.classification import build_reports as build_classification_reports
from eval.classification import format_report as format_classification_report
from eval.loader import baseline_ids, load_records, sample, select
from eval.metrics import build_report, format_report
from eval.runner import read_results, read_results_meta, run_live, write_results
from worker.llm.client import ModelTier

# The services read .env through docker compose's `env_file`. This CLI is run by
# a person from a shell, where nothing has loaded it, and worker/llm/client.py
# reads os.environ directly - so every run failed on a missing OPENAI_API_KEY
# until this line. Done here rather than in a library module: an entry point may
# decide where configuration comes from, an imported module may not.
#
# Does not override a variable that is already set, so an explicit
# `OPENAI_API_KEY=... python -m eval` still wins.
load_dotenv()


def parse_mix(text: str) -> dict[str, int]:
    """Read 'email=3,call_transcript=2' into a channel mix."""
    mix = {}
    for part in text.split(","):
        channel, _, count = part.partition("=")
        if not count.isdigit():
            raise argparse.ArgumentTypeError(f"expected channel=count, got '{part}'")
        mix[channel.strip()] = int(count)
    return mix


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m eval", description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true", help="call the model over a sample")
    mode.add_argument("--score", type=Path, metavar="PATH", help="re-score an existing run")
    mode.add_argument(
        "--gate",
        action="store_true",
        help="classify + extract over a sample, then measure the auto-approval gate",
    )
    mode.add_argument(
        "--gate-score",
        type=Path,
        metavar="PATH",
        help="re-measure an existing gate run (free, offline)",
    )
    parser.add_argument("--seed", type=int, default=42, help="sampling and model seed")
    parser.add_argument(
        "--tier",
        choices=[tier.value for tier in ModelTier],
        default=ModelTier.CHEAP.value,
        help="model tier (default: cheap, per ADR-001)",
    )
    parser.add_argument(
        "--mix",
        type=parse_mix,
        default=None,
        help="channel=count,... (draws a fresh random sample instead of the pinned baseline)",
    )
    parser.add_argument("--out", type=Path, default=None, help="where to write the results")
    return parser


def report_gate(records: list[gate.GateRecord]) -> None:
    """Everything a finished gate run has to say, in one place.

    Rule frequencies come first because they are what the candidate table is
    built from: a reader who disagrees with the candidates can see immediately
    which rules were available to choose between.
    """
    for report in build_classification_reports(records):
        print(format_classification_report(report))
        print()

    frequencies = gate.blocking_rule_names(records)
    if frequencies:
        print("validation rules that fired (records):")
        for rule, count in frequencies.items():
            print(f"  {rule:<40} {count}")
        print()

    print(gate.format_measurements(gate.sweep(records, gate.candidate_sets(records))))

    shipped = gate.measure(records)
    if shipped.reasons:
        print("\nwhy the rest were held:")
        for reason, count in shipped.reasons.items():
            print(f"  {reason:<32} {count}")
    if shipped.wrong_ids:
        print("\napproved but wrong: " + ", ".join(shipped.wrong_ids))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.gate_score is not None:
        report_gate(gate.read_run(args.gate_score))
        return 0

    if args.score is not None:
        scores = read_results(args.score)
        meta = read_results_meta(args.score)
        if meta:
            print(f"run {meta.get('run_at', '?')}  model {meta.get('model', '?')}\n")
        print(format_report(build_report(scores)))
        return 0

    records = load_records()
    if args.mix:
        records = sample(records, seed=args.seed, mix=args.mix)
        description = f"random sample, seed {args.seed}, mix {args.mix}"
    else:
        records = select(records, baseline_ids())
        description = "pinned baseline sample"

    progress = lambda index, total, gt_id: print(  # noqa: E731
        f"  {index}/{total} {gt_id}", end="\r", file=sys.stderr
    )

    if args.gate:
        # Two calls per claim, one per non-claim: classification runs for every
        # record, extraction only for the ones it calls a claim, as the pipeline
        # does.
        print(
            f"about to call the model for {len(records)} records "
            f"(classification + extraction): {description}",
            file=sys.stderr,
        )
        outcome = gate.run_live(
            records,
            seed=args.seed,
            tier=ModelTier(args.tier),
            on_progress=progress,
        )
        path = gate.write_run(outcome, args.out, meta={"seed": args.seed, "sample": description})
        print(f"\nrun written to {path}\n", file=sys.stderr)

        if outcome.failures:
            print(f"{len(outcome.failures)} record(s) failed:", file=sys.stderr)
            for gt_id, error in outcome.failures:
                print(f"  {gt_id}  {error}", file=sys.stderr)

        report_gate(outcome.records)
        return 1 if outcome.failures else 0

    print(f"about to call the model for {len(records)} records: {description}", file=sys.stderr)

    outcome = run_live(
        records,
        seed=args.seed,
        tier=ModelTier(args.tier),
        on_progress=progress,
    )
    path = write_results(outcome, args.out, meta={"seed": args.seed, "sample": description})
    print(f"\nresults written to {path}\n", file=sys.stderr)

    if outcome.failures:
        print(f"{len(outcome.failures)} record(s) failed:", file=sys.stderr)
        for gt_id, error in outcome.failures:
            print(f"  {gt_id}  {error}", file=sys.stderr)

    print(format_report(build_report(outcome.scores)))
    return 1 if outcome.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
