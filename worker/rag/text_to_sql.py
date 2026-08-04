# worker/rag/text_to_sql.py
"""Turns a Turkish question into a SELECT that is safe to run.

Design doc §7.1. This module knows nothing about the database: it builds the
prompt, asks the model, and puts the answer through the guard. Running the SQL
needs a read-only connection, which the backend pair owns, and turning result
rows into a Turkish answer is the layer above this one.

The single self-correction round §7.1 asks for happens here, over the guard's
refusal - that is the error this module can see. The other place a correction
round belongs, a query the database itself rejects, sits with whoever runs it.
"""

import time

import structlog
from pydantic import BaseModel

from worker.llm.client import LlmClient, ModelTier
from worker.rag.schema import SqlQuery
from worker.rag.schema_context import build_system_prompt
from worker.rag.sql_guard import SqlGuardError, check

log = structlog.get_logger(__name__)


class TextToSqlResult(BaseModel):
    """What came back, in one of three shapes.

    answerable and sql set     the query passed the guard and may be run
    answerable false           the model declined; refusal_reason says why (§7.4)
    answerable true, sql None  failure - guard_error says what was wrong

    The third shape is deliberately not folded into the second. A question the
    model refused and a question it botched look identical to a caller that only
    checks `sql`, and they are not the same thing: one is correct behaviour, the
    other belongs in the error centre.
    """

    answerable: bool
    sql: str | None = None
    refusal_reason: str | None = None
    guard_error: str | None = None
    reasoning: str
    model: str
    duration_ms: int
    attempts: int


def build_user_content(question: str) -> str:
    """The message half of the request. Mirrors the examples inside the prompt."""
    return f"SORU: {question}"


def build_retry_content(question: str, sql: str, error: str) -> str:
    """The second attempt: the question again, plus what was wrong with the first.

    The rejected SQL is quoted back on purpose. Without it the model tends to
    produce the same query again, having no idea which part failed.
    """
    return (
        f"SORU: {question}\n\n"
        f"Bir önceki denemende şu sorguyu yazdın:\n{sql}\n\n"
        f"Bu sorgu güvenlik kontrolünden geçmedi. Sebep: {error}\n\n"
        "Aynı soruyu, kurallara uyan tek bir SELECT sorgusuyla yeniden cevapla. "
        "Soru gerçekten bu şemayla cevaplanamıyorsa answerable=false ver."
    )


def generate_sql(
    question: str,
    *,
    question_id: str,
    client: LlmClient | None = None,
    tier: ModelTier = ModelTier.CHEAP,
    seed: int | None = None,
    system_prompt: str | None = None,
    self_correct: bool = True,
) -> TextToSqlResult:
    """Ask the model for one SELECT answering `question`, and vet it.

    `tier` defaults to the cheap model: the whole project runs on gpt-4o-mini
    (ADR-001, update of 2026-08-04). The parameter stays so the 40-question RAG
    set can put both tiers on the same sample, which is the measurement that
    decision is still waiting on.

    `seed` is for eval runs, where week-to-week comparability matters more than
    anything else; a live question leaves it unset.

    `system_prompt` defaults to the versioned file with the schema injected.
    Overriding it lets eval compare prompt variants on one sample.
    """
    client = client or LlmClient()
    prompt = system_prompt or build_system_prompt()
    started = time.perf_counter()

    user_content = build_user_content(question)
    attempts = 0
    guard_error: str | None = None
    answer: SqlQuery | None = None

    while True:
        attempts += 1
        answer = client.structured(
            tier=tier,
            response_model=SqlQuery,
            system_prompt=prompt,
            user_content=user_content,
            message_id=question_id,
            seed=seed,
        )

        if not answer.answerable:
            # A model that declines and hands over SQL anyway is contradicting
            # itself; the decline is the safer half, so the query is dropped.
            return TextToSqlResult(
                answerable=False,
                refusal_reason=answer.refusal_reason,
                reasoning=answer.reasoning,
                model=client.settings.model_for(tier),
                duration_ms=_elapsed_ms(started),
                attempts=attempts,
            )

        if answer.sql and answer.sql.strip():
            try:
                safe_sql = check(answer.sql)
            except SqlGuardError as exc:
                guard_error = str(exc)
                log.warning(
                    "sql_guard_rejected",
                    question_id=question_id,
                    attempt=attempts,
                    error=guard_error,
                    sql=answer.sql,
                )
            else:
                return TextToSqlResult(
                    answerable=True,
                    sql=safe_sql,
                    reasoning=answer.reasoning,
                    model=client.settings.model_for(tier),
                    duration_ms=_elapsed_ms(started),
                    attempts=attempts,
                )
        else:
            # Not a refusal: the model said the question was answerable. Treated
            # as a failure so it lands in the error centre rather than being
            # reported to the operator as "cannot answer".
            guard_error = "model reported the question as answerable but returned no SQL"
            log.warning("sql_missing", question_id=question_id, attempt=attempts)

        if attempts > 1 or not self_correct:
            break
        user_content = build_retry_content(question, answer.sql or "", guard_error)

    return TextToSqlResult(
        answerable=True,
        guard_error=guard_error,
        reasoning=answer.reasoning,
        model=client.settings.model_for(tier),
        duration_ms=_elapsed_ms(started),
        attempts=attempts,
    )


def _elapsed_ms(started: float) -> int:
    """Milliseconds since `started`, rounded - for the audit trail."""
    return round((time.perf_counter() - started) * 1000)
