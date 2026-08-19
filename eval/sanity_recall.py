# eval/sanity_recall.py
"""What the LLM sanity pass adds after the deterministic layer has missed.

eval/masking_recall.py measures the layer CLAUDE.md §7 scopes its target to -
regex plus the name dictionary - and reports 82.2%, with holdout surnames at
0/352. That number gets read as "the system leaks four names in five", and that
is not what it says. It describes one layer of two.

The second layer does not mask anything, so it cannot move that percentage. It
reads the masked text and answers one question: is there still PII in here. A
flag routes the claim differently and keeps the text away from extraction
(worker/pipeline.py), so what it buys is containment, not coverage. The honest
question is therefore not "what is recall with sanity on" but:

    when the dictionary lets a name through, does the system notice?

Two numbers answer it, and neither means much alone:

  detection    of records that still hold a real PII value after masking, the
               share the sanity pass flags. This is what the KVKK claim rests
               on once the deterministic number is understood properly.
  false alarm  of records with nothing left to find, the share it flags anyway.
               Not free: a flag costs the claim its extraction step, so a layer
               that shouts at everything would "catch" every leak and be worth
               nothing.

Ground truth is masking_recall's: data/ground_truth_enriched.jsonl carries the
real values, so a leak is "the value is still in the masked text" rather than a
judgement call.

Costs one cheap call per record and needs no database.

    python -m eval.sanity_recall --limit 40
    python -m eval.sanity_recall --out eval/results/sanity_recall.json
"""

import argparse
import json
import random
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from eval.masking_recall import GROUND_TRUTH_PATH, TEXTS_PATH, pii_items, read_jsonl
from worker.llm.client import LlmClient, ModelTier
from worker.masking.pipeline import mask_all
from worker.masking.sanity import PROMPT_PATH, check_sanity

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "eval" / "results"

# A leaked kind, as masking_recall names it, mapped to the SanityFlagKind the
# model would use for the same thing.
FLAG_FOR = {"tc": "tc", "phone": "phone", "plate": "plate", "name": "name"}


@dataclass
class Case:
    """One record, and what survived masking in it."""

    gt_id: str
    masked_text: str
    # (kind, value) pairs still present in masked_text. Empty means clean.
    leaks: list[tuple[str, str]] = field(default_factory=list)

    @property
    def leaked(self) -> bool:
        return bool(self.leaks)

    @property
    def leaked_kinds(self) -> set[str]:
        """Normalised, so name_first[holdout] and name_last[faker] both read as
        the kind a sanity flag would name."""
        return {kind.split("_")[0].split("[")[0] for kind, _ in self.leaks}


@dataclass
class Outcome:
    gt_id: str
    leaked: bool
    leaked_kinds: list[str]
    flagged: bool
    flag_kinds: list[str]
    # Whether the model named the right kind of thing, not merely that
    # something was wrong. None on clean records, where there is no kind to get
    # right - absence of a question, not a failed one.
    kind_matched: bool | None
    notes: str | None


def build_cases() -> list[Case]:
    """Mask every record and record what is still in the text afterwards."""
    texts = {row["gt_id"]: row.get("text", "") for row in read_jsonl(TEXTS_PATH)}
    truths = {row["gt_id"]: row for row in read_jsonl(GROUND_TRUTH_PATH)}

    cases: list[Case] = []
    for gt_id, text in texts.items():
        truth = truths.get(gt_id)
        if truth is None:
            continue
        masked, _ = mask_all(text)
        leaks = [(kind, value) for kind, value in pii_items({}, truth) if value in masked]
        cases.append(Case(gt_id=gt_id, masked_text=masked, leaks=leaks))
    return cases


def sample(cases: list[Case], *, limit: int, seed: int, group: str = "tune") -> list[Case]:
    """Equal numbers of leaking and clean records, in two disjoint groups.

    Balanced deliberately. The two numbers are read together and a natural
    sample would be mostly one of them; what is measured here is how the layer
    behaves on each kind of input, not how often each kind occurs.

    One shuffle, two slices: `tune` takes the first `limit` of each pool and
    `holdout` the next `limit`. Disjoint by construction and reproducible from
    the seed, so a prompt written against tune can be checked on records it was
    never shown - the discipline eval/fixtures/injury_phrasings.jsonl
    established.
    """
    rng = random.Random(seed)
    leaked = [case for case in cases if case.leaked]
    clean = [case for case in cases if not case.leaked]
    rng.shuffle(leaked)
    rng.shuffle(clean)
    start = 0 if group == "tune" else limit
    stop = start + limit
    return leaked[start:stop] + clean[start:stop]


def run(
    cases: list[Case],
    *,
    client: LlmClient | None = None,
    seed: int | None = 42,
    tier: ModelTier = ModelTier.CHEAP,
    system_prompt: str | None = None,
    on_progress=None,
) -> list[Outcome]:
    """Ask the sanity pass about each masked text.

    The client is built here rather than left to check_sanity's default. That
    default is get_llm_client(), which hands back recorded fixtures when
    DEMO_OFFLINE is on, and a scoring run must never grade answers it was
    handed (worker/llm/client.py).
    """
    client = client or LlmClient()
    outcomes: list[Outcome] = []

    for index, case in enumerate(cases, start=1):
        result = check_sanity(
            case.masked_text,
            message_id=f"sanity-{case.gt_id}",
            client=client,
            tier=tier,
            seed=seed,
            system_prompt=system_prompt,
        )
        flag_kinds = sorted({str(flag.kind) for flag in result.flags})
        wanted = {FLAG_FOR.get(kind, kind) for kind in case.leaked_kinds}

        outcomes.append(
            Outcome(
                gt_id=case.gt_id,
                leaked=case.leaked,
                leaked_kinds=sorted(case.leaked_kinds),
                flagged=result.leak_found,
                flag_kinds=flag_kinds,
                kind_matched=bool(wanted & set(flag_kinds)) if case.leaked else None,
                notes=result.notes,
            )
        )
        if on_progress:
            on_progress(index, len(cases), case.gt_id)

    return outcomes


def _rate(part: int, whole: int) -> str:
    return f"{part}/{whole} = {part / whole:6.1%}" if whole else f"{part}/0 =      -"


def format_report(outcomes: list[Outcome]) -> str:
    leaked = [o for o in outcomes if o.leaked]
    clean = [o for o in outcomes if not o.leaked]
    caught = sum(1 for o in leaked if o.flagged)
    right_kind = sum(1 for o in leaked if o.kind_matched)
    false_alarm = sum(1 for o in clean if o.flagged)

    lines = [
        f"leaking records   n={len(leaked)}",
        f"  detected          {_rate(caught, len(leaked))}",
        f"  right kind named  {_rate(right_kind, len(leaked))}",
        "",
        f"clean records     n={len(clean)}",
        f"  false alarms      {_rate(false_alarm, len(clean))}",
        "",
    ]

    by_kind: dict[str, list[Outcome]] = {}
    for outcome in leaked:
        for kind in outcome.leaked_kinds:
            by_kind.setdefault(kind, []).append(outcome)
    if by_kind:
        lines.append("detection by what leaked")
        for kind in sorted(by_kind):
            rows = by_kind[kind]
            lines.append(f"  {kind:<12} {_rate(sum(1 for o in rows if o.flagged), len(rows))}")
        lines.append("")

    missed = [o for o in leaked if not o.flagged]
    if missed:
        lines.append(f"missed ({len(missed)}) - leaked and not flagged")
        for outcome in missed[:12]:
            lines.append(f"  {outcome.gt_id}  {','.join(outcome.leaked_kinds)}")
    return "\n".join(lines)


def write_run(
    outcomes: list[Outcome], path: Path, *, args_prompt_name: str = "", meta: dict | None = None
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "run_at": datetime.now(UTC).isoformat(),
            "records": len(outcomes),
            "prompt": args_prompt_name,
            **(meta or {}),
        },
        "outcomes": [asdict(o) for o in outcomes],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.sanity_recall", description=__doc__)
    parser.add_argument("--limit", type=int, default=40, help="records per group (leaking/clean)")
    parser.add_argument("--group", choices=("tune", "holdout"), default="tune")
    parser.add_argument("--prompt", type=Path, default=None, help="sanity prompt to use instead")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--tier", choices=[t.value for t in ModelTier], default=ModelTier.CHEAP.value
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    cases = build_cases()
    counts = Counter("leaked" if case.leaked else "clean" for case in cases)
    print(f"corpus: {dict(counts)}", file=sys.stderr)

    chosen = sample(cases, limit=args.limit, seed=args.seed, group=args.group)
    print(f"about to call the model for {len(chosen)} records", file=sys.stderr)

    def progress(index: int, total: int, gt_id: str) -> None:
        print(f"  {index}/{total} {gt_id}", end="\r", file=sys.stderr)

    system_prompt = args.prompt.read_text(encoding="utf-8") if args.prompt else None
    outcomes = run(
        chosen,
        seed=args.seed,
        tier=ModelTier(args.tier),
        system_prompt=system_prompt,
        on_progress=progress,
    )
    print(format_report(outcomes))

    if args.out:
        path = write_run(
            outcomes,
            args.out,
            args_prompt_name=args.prompt.name if args.prompt else PROMPT_PATH.name,
            meta={"seed": args.seed, "tier": args.tier, "group": args.group},
        )
        print(f"\nrun written to {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
