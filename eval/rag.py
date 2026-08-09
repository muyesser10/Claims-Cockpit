# eval/rag.py
"""RAG accuracy — the eighth §7 metric, and the one that had no measurement.

Every question in eval/fixtures/rag_questions.jsonl carries the way to check its
own answer, so the answer key is never a number someone typed and later
forgot to update:

  sql        a reference query. It runs against the same database the question
             does, and the value it returns has to appear in the answer. The
             expectation is therefore always current, whatever the database
             happens to hold.
  retrieval  a reference query listing the claims that should be found. The
             answer has to cite at least one of them.
  refusal    nothing to compute. The system must decline, and answering is the
             failure.

The three categories are scored and reported separately as well as together.
They fail for different reasons - a wrong number, a missed document, a
fabricated capability - and one blended percentage would hide which.

Needs the database and an API key; the corpus files are not involved. Reads
EVAL_DATABASE_URL, or DATABASE_URL with the compose hostname swapped for
localhost, because this runs on the host and `db` only resolves inside compose.

    python -m eval.rag --limit 5        # smoke test, five questions
    python -m eval.rag --out eval/results/rag.json
"""

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from worker.llm.client import ModelTier
from worker.rag.ask import ask

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rag_questions.jsonl"
RESULTS_DIR = REPO_ROOT / "eval" / "results"

CATEGORIES = ("sql", "retrieval", "refusal")


def database_url() -> str:
    """Where to reach the database from the host.

    DATABASE_URL names the compose service (`db`), which does not resolve
    outside the network, and the repo's URLs carry no driver so SQLAlchemy
    reaches for psycopg2 while the project installs psycopg v3 (CLAUDE.md §2).
    Both are fixed here rather than asking every caller to know.
    """
    url = os.environ.get("EVAL_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("EVAL_DATABASE_URL or DATABASE_URL must be set.")
    return url.replace("@db:", "@localhost:").replace("postgresql://", "postgresql+psycopg://")


@dataclass
class Question:
    id: str
    category: str
    question: str
    reference_sql: str | None = None
    expected_any: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class Outcome:
    """One scored question."""

    id: str
    category: str
    question: str
    passed: bool
    reason: str
    expected: str
    answerable: bool
    mode: str
    answer: str | None
    duration_ms: int
    # The query the model wrote. Not scored, but it is what a failure is
    # diagnosed from: the first run of this eval showed four questions
    # returning 0, and only the SQL said why (city = 'Izmir' against a database
    # holding 'İzmir').
    sql: str | None = None


def load_questions(path: Path = FIXTURE) -> list[Question]:
    with path.open(encoding="utf-8") as handle:
        return [Question(**json.loads(line)) for line in handle if line.strip()]


# A number as Turkish writes it: "." groups thousands, "," opens the decimals.
_NUMBER = re.compile(r"\d[\d.,]*\d|\d")
_THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3})+(,\d+)?$")
_DECIMAL_COMMA = re.compile(r"^\d+,\d+$")


def parse_number(token: str) -> float | None:
    """One written number as a float, or None if it is not one.

    "44.481" is forty-four thousand here, not forty-four point four - which is
    the whole reason this is not a float() call.
    """
    token = token.strip(".,")
    if not token:
        return None
    if _THOUSANDS.match(token):
        token = token.replace(".", "").replace(",", ".")
    elif _DECIMAL_COMMA.match(token):
        token = token.replace(",", ".")
    else:
        token = token.replace(",", "")
    try:
        return float(token)
    except ValueError:
        return None


def numbers_in(text_value: str) -> list[float]:
    found = (parse_number(match.group()) for match in _NUMBER.finditer(text_value))
    return [value for value in found if value is not None]


def _fold(value: str) -> str:
    """Casefold plus the Turkish letters, so "İstanbul" matches "istanbul"."""
    lowered = value.replace("I", "ı").replace("İ", "i").lower()
    return lowered.translate(str.maketrans("çğıöşü", "cgiosu"))


def score_sql(question: Question, answer, expected) -> tuple[bool, str]:
    """The reference value has to be in the answer, as a number or as a word."""
    if not answer.answerable:
        return False, f"reddetti: {answer.refusal_reason}"
    if answer.answer is None:
        return False, "answerable ama cevap boş"

    if question.expected_any:
        wanted = [_fold(item) for item in question.expected_any]
        haystack = _fold(answer.answer)
        if any(item in haystack for item in wanted):
            return True, ""
        return False, f"cevapta {question.expected_any} yok"

    if isinstance(expected, (int, float)) or (
        hasattr(expected, "__float__") and not isinstance(expected, str)
    ):
        target = float(expected)
        if any(round(value) == round(target) for value in numbers_in(answer.answer)):
            return True, ""
        return False, f"beklenen {target:g}, cevapta yok"

    if _fold(str(expected)) in _fold(answer.answer):
        return True, ""
    return False, f"beklenen '{expected}' cevapta yok"


def score_retrieval(answer, expected_ids: set[int]) -> tuple[bool, str]:
    """At least one of the claims that should have been found has to be cited."""
    if not answer.answerable:
        return False, f"reddetti: {answer.refusal_reason}"
    cited = {source.claim_id for source in answer.sources}
    if cited & expected_ids:
        return True, ""
    if not cited:
        return False, "hiç kaynak gösterilmedi"
    return False, f"gösterilen {sorted(cited)}, beklenen {sorted(expected_ids)}"


def score_refusal(answer) -> tuple[bool, str]:
    """Answering is the failure: the schema cannot support these."""
    if answer.answerable:
        return False, f"cevaplamamalıydı: {(answer.answer or '')[:70]}"
    return True, ""


def run(
    db: Session,
    questions: list[Question],
    *,
    seed: int | None = 42,
    tier: ModelTier = ModelTier.CHEAP,
    on_progress=None,
) -> list[Outcome]:
    outcomes: list[Outcome] = []

    for index, item in enumerate(questions, start=1):
        expected: object = ""
        expected_ids: set[int] = set()
        if item.reference_sql:
            rows = db.execute(text(item.reference_sql)).fetchall()
            if item.category == "retrieval":
                expected_ids = {row[0] for row in rows}
            else:
                expected = rows[0][0] if rows else None

        answer = ask(db, item.question, seed=seed, audit=False)

        if item.category == "sql":
            passed, reason = score_sql(item, answer, expected)
        elif item.category == "retrieval":
            passed, reason = score_retrieval(answer, expected_ids)
        else:
            passed, reason = score_refusal(answer)

        outcomes.append(
            Outcome(
                id=item.id,
                category=item.category,
                question=item.question,
                passed=passed,
                reason=reason,
                expected=str(sorted(expected_ids)) if expected_ids else str(expected),
                answerable=answer.answerable,
                mode=answer.mode,
                answer=answer.answer,
                duration_ms=answer.duration_ms,
                sql=answer.sql,
            )
        )
        if on_progress:
            on_progress(index, len(questions), item.id)

    return outcomes


def format_report(outcomes: list[Outcome]) -> str:
    lines = []
    total_passed = sum(1 for item in outcomes if item.passed)

    for category in CATEGORIES:
        subset = [item for item in outcomes if item.category == category]
        if not subset:
            continue
        passed = sum(1 for item in subset if item.passed)
        lines.append(f"\n{category}  {passed}/{len(subset)} = {passed / len(subset):.1%}")
        for item in subset:
            if not item.passed:
                lines.append(f"    {item.id}  {item.reason}")
                lines.append(f"          soru: {item.question}")

    lines.append("")
    lines.append("=" * 64)
    rate = total_passed / len(outcomes)
    lines.append(f"  RAG accuracy  {total_passed}/{len(outcomes)} = {rate:.1%}   hedef >= 65%")

    modes: dict[str, int] = {}
    for item in outcomes:
        modes[item.mode] = modes.get(item.mode, 0) + 1
    lines.append(f"  yol dagilimi  {modes}")

    durations = sorted(item.duration_ms for item in outcomes)
    if durations:
        p95 = durations[min(len(durations) - 1, int(len(durations) * 0.95))] / 1000
        median = durations[len(durations) // 2] / 1000
        lines.append(f"  sure          medyan {median:.1f} sn, p95 {p95:.1f} sn")
    return "\n".join(lines)


def write_run(outcomes: list[Outcome], path: Path, *, meta: dict | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "run_at": datetime.now(UTC).isoformat(),
            "questions": len(outcomes),
            **(meta or {}),
        },
        "outcomes": [asdict(item) for item in outcomes],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.rag", description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="only the first N questions")
    parser.add_argument("--category", choices=CATEGORIES, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--tier", choices=[tier.value for tier in ModelTier], default=ModelTier.CHEAP.value
    )
    parser.add_argument("--out", type=Path, default=RESULTS_DIR / "rag.json")
    args = parser.parse_args(argv)

    questions = load_questions()
    if args.category:
        questions = [item for item in questions if item.category == args.category]
    if args.limit:
        questions = questions[: args.limit]

    print(f"about to call the model for {len(questions)} questions", file=sys.stderr)

    def progress(index: int, total: int, question_id: str) -> None:
        print(f"  {index}/{total} {question_id}", end="\r", file=sys.stderr)

    engine = create_engine(database_url())
    with Session(engine) as db:
        outcomes = run(
            db, questions, seed=args.seed, tier=ModelTier(args.tier), on_progress=progress
        )

    print(format_report(outcomes))
    path = write_run(outcomes, args.out, meta={"seed": args.seed, "tier": args.tier})
    print(f"\nrun written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
