# eval/__main__.py
"""Command line entry point.

    python -m eval --score eval/results/run_20260802T120000Z.json
    python -m eval --run --seed 42
    python -m eval --run --mix email=3,call_transcript=2,web_form=1

`--score` is free and offline. `--run` calls the model and costs money, so it
prints the sample it is about to buy before it starts.
"""

import argparse
import sys
from pathlib import Path

from eval.loader import BASELINE_CHANNEL_MIX, load_records, sample
from eval.metrics import build_report, format_report
from eval.runner import read_results, read_results_meta, run_live, write_results
from worker.llm.client import ModelTier


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
    parser.add_argument("--seed", type=int, default=42, help="sampling and model seed")
    parser.add_argument(
        "--tier",
        choices=[tier.value for tier in ModelTier],
        default=ModelTier.CHEAP.value,
        help="model tier (default: cheap, per ADR-001)",
    )
    parser.add_argument("--mix", type=parse_mix, default=None, help="channel=count,...")
    parser.add_argument("--out", type=Path, default=None, help="where to write the results")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.score is not None:
        scores = read_results(args.score)
        meta = read_results_meta(args.score)
        if meta:
            print(f"run {meta.get('run_at', '?')}  model {meta.get('model', '?')}\n")
        print(format_report(build_report(scores)))
        return 0

    mix = args.mix or BASELINE_CHANNEL_MIX
    records = sample(load_records(), seed=args.seed, mix=mix)
    print(f"about to call the model for {len(records)} records: {mix}", file=sys.stderr)

    outcome = run_live(
        records,
        seed=args.seed,
        tier=ModelTier(args.tier),
        on_progress=lambda index, total, gt_id: print(
            f"  {index}/{total} {gt_id}", end="\r", file=sys.stderr
        ),
    )
    path = write_results(outcome, args.out, meta={"seed": args.seed, "mix": mix})
    print(f"\nresults written to {path}\n", file=sys.stderr)

    if outcome.failures:
        print(f"{len(outcome.failures)} record(s) failed:", file=sys.stderr)
        for gt_id, error in outcome.failures:
            print(f"  {gt_id}  {error}", file=sys.stderr)

    print(format_report(build_report(outcome.scores)))
    return 1 if outcome.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
