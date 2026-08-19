# eval/router.py
"""Routing accuracy: does a question reach the path that can answer it.

Cheap and database-free. `route_question` is a pure function of the question, so
this costs one small call per case and needs no Postgres - which is why routing
could go unmeasured for so long: the only number for it came out of a full RAG
run, and that run needs a seeded database and about 350 calls.

It exists because the blended RAG number hid a defect. RQ-101 - "46 NT 7528
plakalı ihbar hangi ilden geldi?" - was answered from a different vehicle's
claim, with a citation, saying İzmir for a claim in İstanbul. The retrieval path
does not refuse what it cannot answer; it answers from whatever it found. So a
misrouted question does not surface as a refusal, and only a routing measurement
finds it.

Questions are masked the way ask() masks them, because that is what the router
sees in production: a lookup arrives as "[Q_PLATE_1] plakalı ihbar hangi ilden
geldi?", and a prompt that recognises a plate but not a placeholder would score
here and fail in the product.

    python -m eval.router                                   # shipped prompt
    python -m eval.router --prompt prompts/rag_router_v2.txt
    python -m eval.router --split holdout
"""

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from worker.llm.client import LlmClient, ModelTier
from worker.rag.question_mask import mask_question
from worker.rag.router import route_question

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "router_questions.jsonl"
RESULTS_DIR = REPO_ROOT / "eval" / "results"

KINDS = ("lookup", "aggregate", "content")
SPLITS = ("tune", "holdout")


def default_prompt_name() -> str:
    """The prompt router.py reads when none is given."""
    from worker.rag.router import PROMPT_PATH

    return PROMPT_PATH.name


@dataclass
class Case:
    id: str
    split: str
    expected_route: str
    question: str
    kind: str
    note: str = ""


@dataclass
class Outcome:
    id: str
    split: str
    kind: str
    question: str
    asked: str
    expected: str
    actual: str
    correct: bool
    reasoning: str


def load_cases(path: Path = FIXTURE) -> list[Case]:
    with path.open(encoding="utf-8") as handle:
        return [Case(**json.loads(line)) for line in handle if line.strip()]


def run(
    cases: list[Case],
    *,
    client: LlmClient | None = None,
    seed: int | None = 42,
    tier: ModelTier = ModelTier.CHEAP,
    system_prompt: str | None = None,
    on_progress=None,
) -> list[Outcome]:
    client = client or LlmClient()
    outcomes: list[Outcome] = []

    for index, case in enumerate(cases, start=1):
        asked, _ = mask_question(case.question)
        result = route_question(
            asked,
            question_id=f"router-{case.id}",
            client=client,
            tier=tier,
            seed=seed,
            system_prompt=system_prompt,
        )
        actual = str(result.route)
        outcomes.append(
            Outcome(
                id=case.id,
                split=case.split,
                kind=case.kind,
                question=case.question,
                asked=asked,
                expected=case.expected_route,
                actual=actual,
                correct=actual == case.expected_route,
                reasoning=result.reasoning,
            )
        )
        if on_progress:
            on_progress(index, len(cases), case.id)

    return outcomes


def _rate(part: int, whole: int) -> str:
    return f"{part}/{whole} = {part / whole:6.1%}" if whole else f"{part}/0 =      -"


def format_report(outcomes: list[Outcome]) -> str:
    lines: list[str] = []

    for split in (*SPLITS, None):
        subset = [o for o in outcomes if split is None or o.split == split]
        if not subset:
            continue
        label = "all" if split is None else split
        hits = sum(1 for o in subset if o.correct)
        lines.append(f"{label:<8} {_rate(hits, len(subset))}")
        for kind in KINDS:
            rows = [o for o in subset if o.kind == kind]
            if rows:
                got = sum(1 for o in rows if o.correct)
                lines.append(f"    {kind:<12} {_rate(got, len(rows))}")
        lines.append("")

    wrong = [o for o in outcomes if not o.correct]
    if wrong:
        lines.append(f"yanlis yonlendirilen ({len(wrong)})")
        for o in wrong:
            lines.append(f"  {o.id} [{o.split}/{o.kind}] {o.expected} -> {o.actual}")
            lines.append(f"        {o.question}")
            lines.append(f"        gerekce: {o.reasoning[:90]}")
    else:
        lines.append("hepsi dogru yonlendirildi")

    return "\n".join(lines)


def write_run(outcomes: list[Outcome], path: Path, *, meta: dict | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "run_at": datetime.now(UTC).isoformat(),
            "cases": len(outcomes),
            "masked": True,
            **(meta or {}),
        },
        "outcomes": [asdict(o) for o in outcomes],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.router", description=__doc__)
    parser.add_argument("--prompt", type=Path, default=None, help="router prompt to use instead")
    parser.add_argument("--split", choices=SPLITS, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--tier", choices=[t.value for t in ModelTier], default=ModelTier.CHEAP.value
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    cases = load_cases()
    if args.split:
        cases = [case for case in cases if case.split == args.split]

    print(f"about to call the model for {len(cases)} cases", file=sys.stderr)

    def progress(index: int, total: int, case_id: str) -> None:
        print(f"  {index}/{total} {case_id}", end="\r", file=sys.stderr)

    system_prompt = args.prompt.read_text(encoding="utf-8") if args.prompt else None
    outcomes = run(
        cases,
        seed=args.seed,
        tier=ModelTier(args.tier),
        system_prompt=system_prompt,
        on_progress=progress,
    )

    print(format_report(outcomes))
    counts = Counter(o.actual for o in outcomes)
    print(f"\nyol dagilimi  {dict(counts)}")

    if args.out:
        path = write_run(
            outcomes,
            args.out,
            meta={
                "seed": args.seed,
                "tier": args.tier,
                "prompt": args.prompt.name if args.prompt else default_prompt_name(),
            },
        )
        print(f"run written to {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
