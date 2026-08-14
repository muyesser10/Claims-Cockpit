# worker/rag/sql_answer.py
"""Runs a vetted SELECT and turns its rows into a Turkish sentence.

Design doc §7.1's last step, left out of text_to_sql.py on purpose: that module
ends where the guard does. This one holds a Session, runs the query the guard
approved, and asks the model to narrate what came back.

Two things happen here that happen nowhere else in the RAG path.

The rows are masked on the way in and the answer unmasked on the way out.
claims_flat reads claims.data->'extraction', and pipeline.py:194 unmasks that
before storing it - a real plate, a real policy number, a real name inside
damage_description. The retrieval path never had this problem: it reads
masked_text. Without the round trip here, the one place in the system that sends
personal data to a third party would be the question screen.

And the numbers in the answer are checked against the rows. A model narrating
"1.247 ihbar" over a result of 12 has produced the SQL path's version of a
fabricated citation, and it hides better: no chip is missing, there is just a
wrong number in a fluent sentence.
"""

import re
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from worker.llm.client import LlmClient, ModelTier
from worker.masking.pipeline import mask_all
from worker.masking.unmask import unmask_text

log = structlog.get_logger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "rag_sql_answer_v2.txt"

# Read once: the rules are static, only the rows change per question.
PROMPT_TEMPLATE = PROMPT_PATH.read_text(encoding="utf-8")

# Same reason as schema_context.py's SCHEMA_PLACEHOLDER: str.format() over a
# prompt full of brackets either fails or silently mangles an example.
ROWS_PLACEHOLDER = "<<ROWS>>"

# The guard bounds a query at MAX_LIMIT (100); this bounds what the narrator is
# shown. A three-sentence summary does not get better from row 80, and a question
# that genuinely needs row 80 belongs on the queue screen.
NARRATE_ROW_LIMIT = 20

# The guard cannot tell a cheap SELECT from one that cross-joins the table to
# itself. This turns that into a refusal after 10s instead of a request that
# never returns.
STATEMENT_TIMEOUT_MS = 10_000

EMPTY_RESULT_REFUSAL = "Sorgu çalıştı ancak eşleşen kayıt bulunamadı."
UNVERIFIED_NUMBER_REFUSAL = (
    "Cevap üretildi ancak içindeki sayılar sorgu sonucuyla doğrulanamadı, bu yüzden gösterilmiyor."
)

NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)*")


class SqlNarration(BaseModel):
    """What the model fills in.

    Descriptions are shipped to the model as part of the tool schema, so they
    are written in Turkish for it. Repo-internal notes stay in `#` comments.
    """

    # Reasoning first, deliberately: it makes the model read the rows before it
    # commits to a sentence about them.
    reasoning: str = Field(
        description="Sonuç satırları soruyu nasıl cevaplıyor? En fazla 2 cümle.",
    )
    answerable: bool = Field(
        description="Sonuç satırları soruyu cevaplıyor mu? Boş veya alakasız sonuçta false ver.",
    )
    answer: str | None = Field(
        default=None,
        description=(
            "Türkçe cevap, en fazla 3 cümle. Yalnızca sonuç satırlarında geçen "
            "sayıları kullan. answerable=false ise null bırak."
        ),
    )
    refusal_reason: str | None = Field(
        default=None,
        description="answerable=false ise nedeni tek Türkçe cümleyle yaz. Aksi halde null.",
    )


class SqlAnswerResult(BaseModel):
    """What the service returns and the audit trail records."""

    answerable: bool
    answer: str | None
    refusal_reason: str | None
    reasoning: str
    row_count: int
    # Number tokens the model wrote that appear nowhere in the result. Kept
    # rather than dropped silently - this is the SQL path's counterpart of
    # answer.py's invalid_citations, and the error centre's only signal here.
    unverified_numbers: list[str]
    model: str
    duration_ms: int


def run_query(db: Session, sql: str) -> list[dict]:
    """Execute `sql` and return its rows as dicts.

    `sql` must be the guard's output, never the model's own text: check()
    regenerates the query from the parse tree, so what runs is what the guard
    understood.

    statement_timeout is SET LOCAL, so it expires with this transaction instead
    of leaking into whatever the session does next.
    """
    db.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
    return [dict(row) for row in db.execute(text(sql)).mappings()]


def render_rows(rows: list[dict], *, limit: int = NARRATE_ROW_LIMIT) -> str:
    """The rows as the model sees them: one line each, `column: value`.

    Not a markdown table. The column count changes with every question, and a
    wide table wraps into something a model reads out of alignment.
    """
    shown = rows[:limit]
    lines = [
        f"{number}. " + ", ".join(f"{key}: {_render_value(value)}" for key, value in row.items())
        for number, row in enumerate(shown, start=1)
    ]
    if len(rows) > len(shown):
        lines.append(f"... ({len(rows) - len(shown)} satır daha gösterilmedi)")
    return "\n".join(lines)


def _render_value(value: object) -> str:
    """None is written out rather than left blank: `injury: yok` is a fact, an
    empty cell reads like a rendering bug."""
    return "yok" if value is None else str(value)


def parse_number(token: str) -> Decimal | None:
    """Read a number the way a Turkish sentence writes one.

    `12.500` is twelve and a half thousand, `12,5` is twelve and a half. The
    ambiguous case is a lone dot, resolved as grouping only when exactly three
    digits follow it - the shape Turkish grouping produces. `12500.00`, which is
    how Postgres renders a numeric, keeps its dot and parses as itself.
    """
    if "," in token:
        candidate = token.replace(".", "").replace(",", ".")
    elif token.count(".") > 1 or _looks_grouped(token):
        candidate = token.replace(".", "")
    else:
        candidate = token
    try:
        return Decimal(candidate)
    except InvalidOperation:
        return None


def _looks_grouped(token: str) -> bool:
    """A single dot with exactly three digits after it, e.g. 12.500."""
    head, _, tail = token.partition(".")
    return bool(head) and len(tail) == 3


def unverified_numbers(answer: str, rendered_rows: str, row_count: int) -> list[str]:
    """Number tokens in `answer` that appear nowhere in the result.

    Two ways to pass, because the same value is written differently on each side.
    A numeric match handles formatting: Postgres renders 12500.00 where the model
    writes 12.500. A literal digit-run match handles what is not really a number -
    a year inside a date, an id, a plate - where parsing would be wrong but the
    digits are sitting right there in the text.

    `row_count` counts as present: "5 kayıt bulundu" over five rows is correct
    even when no 5 appears in any column.

    This catches fabrication, not error. A model that writes 3 where the answer
    is 4 passes whenever a 3 occurs anywhere in the rows. What it stops is the
    invented aggregate - a 1.247 over a result of 12 - which is the failure that
    survives a reader's glance.
    """
    row_tokens = set(NUMBER_PATTERN.findall(rendered_rows))
    row_values = {value for token in row_tokens if (value := parse_number(token)) is not None}
    row_values.add(Decimal(row_count))

    missing = []
    for token in NUMBER_PATTERN.findall(answer):
        if token in row_tokens:
            continue
        value = parse_number(token)
        if value is not None and value in row_values:
            continue
        missing.append(token)
    return missing


def narrate(
    question: str,
    rows: list[dict],
    *,
    question_id: str,
    client: LlmClient | None = None,
    tier: ModelTier = ModelTier.CHEAP,
    seed: int | None = None,
) -> SqlAnswerResult:
    """Turn `rows` into a Turkish answer, withholding anything unverifiable.

    The SQL that produced the rows is deliberately not shown to the model. The
    column names already carry the meaning, and a WHERE clause can hold personal
    data lifted straight out of the operator's question - which would walk past
    the masking this function exists to do.

    `tier` defaults to the cheap model, as everything else has since ADR-001's
    2026-08-04 update. `seed` is for eval runs, where week-to-week comparability
    matters more than anything else; a live question leaves it unset.
    """
    if not rows:
        return SqlAnswerResult(
            answerable=False,
            answer=None,
            refusal_reason=EMPTY_RESULT_REFUSAL,
            reasoning="query returned no rows",
            row_count=0,
            unverified_numbers=[],
            model="none",
            duration_ms=0,
        )

    masked_rows, mappings = mask_all(render_rows(rows))

    client = client or LlmClient()
    started = time.perf_counter()
    reply = client.structured(
        tier=tier,
        response_model=SqlNarration,
        system_prompt=PROMPT_TEMPLATE.replace(ROWS_PLACEHOLDER, masked_rows),
        user_content=f"SORU: {question}",
        message_id=question_id,
        seed=seed,
    )
    duration_ms = round((time.perf_counter() - started) * 1000)
    model_name = client.settings.model_for(tier)

    if not reply.answerable or not reply.answer:
        return SqlAnswerResult(
            answerable=False,
            answer=None,
            refusal_reason=reply.refusal_reason,
            reasoning=reply.reasoning,
            row_count=len(rows),
            unverified_numbers=[],
            model=model_name,
            duration_ms=duration_ms,
        )

    missing = unverified_numbers(reply.answer, masked_rows, len(rows))
    if missing:
        log.warning(
            "rag_sql_unverified_number",
            question_id=question_id,
            numbers=missing,
            row_count=len(rows),
        )
        return SqlAnswerResult(
            answerable=False,
            answer=None,
            refusal_reason=UNVERIFIED_NUMBER_REFUSAL,
            reasoning=reply.reasoning,
            row_count=len(rows),
            unverified_numbers=missing,
            model=model_name,
            duration_ms=duration_ms,
        )

    return SqlAnswerResult(
        answerable=True,
        answer=unmask_text(reply.answer, mappings),
        refusal_reason=None,
        reasoning=reply.reasoning,
        row_count=len(rows),
        unverified_numbers=[],
        model=model_name,
        duration_ms=duration_ms,
    )
