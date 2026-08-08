# worker/rag/ask.py
"""One question in, one answer out - the whole /soru flow.

Design doc §7. The pieces are separate modules because each is testable alone:
the router picks a path, text_to_sql writes a query, the guard vets it,
sql_answer runs and narrates it, retrieval finds claims and answer.py writes a
cited reply. This module is the only place that knows the order.

It stays HTTP-free on purpose (ADR-003). The rag service is a thin shell over
ask(), and an eval run calls the same function in-process with no network in
the loop.
"""

import time
import uuid
from dataclasses import dataclass

import structlog
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.models.db import AuditTrail
from worker.embedding.encoder import Encoder
from worker.llm.client import LlmClient
from worker.rag.answer import answer_question
from worker.rag.retrieval import RetrievedClaim, search
from worker.rag.router import Route, RouteResult, route_question
from worker.rag.sql_answer import narrate, run_query
from worker.rag.text_to_sql import generate_sql

log = structlog.get_logger(__name__)

# One value, so the error centre and the RAG scoring run can both find these
# rows by step. Also listed in schema_context.SCHEMA_TEXT, or a question about
# question latency would be written against a step that appears not to exist.
AUDIT_STEP = "rag_question"

CANNOT_ANSWER_REFUSAL = "Bu soru mevcut verilerle cevaplanamıyor."
GENERATION_FAILED_REFUSAL = "Soru için güvenli bir sorgu üretilemedi."
EXECUTION_FAILED_REFUSAL = "Sorgu çalıştırılamadı; bu soru şu an cevaplanamıyor."


class QuestionAnswer(BaseModel):
    """The /soru response.

    This shape is frozen: web/src/api/useQuestion.ts was built against it while
    the endpoint was still a mock. Renaming a field here breaks the Soru screen.
    """

    question: str
    answer: str | None
    mode: str
    answerable: bool
    refusal_reason: str | None
    sources: list[RetrievedClaim]
    sql: str | None
    row_count: int | None
    duration_ms: int


@dataclass
class _Outcome:
    """A branch's result: what the caller sees, plus what only the audit row does.

    Split because `sources` and `sql` belong on screen while `guard_error` and
    `unverified_numbers` belong in the error centre, and putting the second pair
    in the response would make them part of the frozen contract.
    """

    answer: QuestionAnswer
    detail: dict


def ask(
    db: Session,
    question: str,
    *,
    question_id: str | None = None,
    client: LlmClient | None = None,
    encoder: Encoder | None = None,
    seed: int | None = None,
    sql_db: Session | None = None,
    audit: bool = True,
) -> QuestionAnswer:
    """Answer `question`, by whichever path the router picks.

    One LlmClient is built here and threaded through every step, so a question
    costs one client rather than three, and one place decides the model.

    `sql_db` is the session generated SQL runs on. The rag service passes a
    second connection there, one that authenticates as rag_readonly and can see
    nothing but claims_flat and audit_trail (rag/readonly.py). Left unset it
    falls back to `db`, which is what an eval run and every existing caller do:
    the isolation is a deployment property, not something ask() depends on.

    `audit=False` is for eval runs: a thousand scored questions should not land
    in the operator's error centre as a thousand audit rows.
    """
    question_id = question_id or uuid.uuid4().hex
    client = client or LlmClient()
    started = time.perf_counter()

    route = route_question(question, question_id=question_id, client=client, seed=seed)
    log.info(
        "rag_route",
        question_id=question_id,
        route=str(route.route),
        mode=route.mode,
        urgency=route.urgency,
        status=route.status,
    )

    if route.route is Route.SQL:
        outcome = _answer_with_sql(
            sql_db or db, question, question_id=question_id, client=client, seed=seed
        )
    else:
        outcome = _answer_with_retrieval(
            db,
            question,
            route,
            question_id=question_id,
            client=client,
            encoder=encoder,
            seed=seed,
        )

    # Wall time, not the sum of the steps: the operator waited for all of it,
    # including the parts nobody timed.
    answer = outcome.answer.model_copy(
        update={"duration_ms": round((time.perf_counter() - started) * 1000)}
    )

    if audit:
        _log_question(
            db,
            question=question,
            question_id=question_id,
            route=route,
            answer=answer,
            detail=outcome.detail,
        )
    return answer


def _answer_with_sql(
    sql_db: Session,
    question: str,
    *,
    question_id: str,
    client: LlmClient,
    seed: int | None,
) -> _Outcome:
    """Text-to-SQL: generate, vet, run, narrate.

    `sql_db` is whatever ask() decided the query may run on - the read-only
    connection in the rag service, the caller's own session everywhere else.
    Nothing in this function writes, which is what makes that substitution safe.

    Three ways this ends without an answer, kept apart because they are not the
    same event. The model declining is correct behaviour. The guard rejecting
    both attempts is a failure worth reading. The query not running at all is
    infrastructure - and until the claims_flat migration lands it is the
    expected outcome of every SQL question, which is exactly why it has to
    surface as a readable Turkish refusal rather than a 500.
    """
    generated = generate_sql(question, question_id=question_id, client=client, seed=seed)

    if not generated.answerable:
        return _Outcome(
            _refusal(question, "sql", generated.refusal_reason or CANNOT_ANSWER_REFUSAL),
            {"outcome": "model_refused", "attempts": generated.attempts},
        )

    if generated.sql is None:
        log.warning(
            "rag_sql_generation_failed",
            question_id=question_id,
            guard_error=generated.guard_error,
            attempts=generated.attempts,
        )
        return _Outcome(
            _refusal(question, "sql", GENERATION_FAILED_REFUSAL),
            {
                "outcome": "guard_rejected",
                "guard_error": generated.guard_error,
                "attempts": generated.attempts,
            },
        )

    try:
        rows = run_query(sql_db, generated.sql)
    except SQLAlchemyError as exc:
        # A failed statement poisons its transaction until something rolls it
        # back, and this session goes back to a pool. It no longer protects the
        # audit write - that runs on the api's own session now, a different
        # connection - but the rollback is still this branch's to do.
        sql_db.rollback()
        log.error(
            "rag_sql_execution_failed",
            question_id=question_id,
            sql=generated.sql,
            error=str(exc),
        )
        return _Outcome(
            _refusal(question, "sql", EXECUTION_FAILED_REFUSAL, sql=generated.sql),
            {"outcome": "execution_failed", "error": str(exc), "sql": generated.sql},
        )

    narrated = narrate(question, rows, question_id=question_id, client=client, seed=seed)
    return _Outcome(
        QuestionAnswer(
            question=question,
            answer=narrated.answer,
            mode="sql",
            answerable=narrated.answerable,
            refusal_reason=narrated.refusal_reason,
            sources=[],
            sql=generated.sql,
            row_count=narrated.row_count,
            duration_ms=0,
        ),
        {
            "outcome": "answered",
            "sql": generated.sql,
            "attempts": generated.attempts,
            "row_count": narrated.row_count,
            "unverified_numbers": narrated.unverified_numbers,
            "narrator_ms": narrated.duration_ms,
        },
    )


def _answer_with_retrieval(
    db: Session,
    question: str,
    route: RouteResult,
    *,
    question_id: str,
    client: LlmClient,
    encoder: Encoder | None,
    seed: int | None,
) -> _Outcome:
    """Vector search, then a cited answer over what it found."""
    sources = search(db, question, urgency=route.urgency, status=route.status, encoder=encoder)
    replied = answer_question(question, sources, question_id=question_id, client=client, seed=seed)

    return _Outcome(
        QuestionAnswer(
            question=question,
            answer=replied.answer,
            mode=route.mode,
            answerable=replied.answerable,
            refusal_reason=replied.refusal_reason,
            # The answer layer returns only the sources it actually cited, in
            # its own numbering order, so [1] in the text is the first chip.
            sources=replied.sources,
            sql=None,
            row_count=None,
            duration_ms=0,
        ),
        {
            "outcome": "answered",
            "retrieved": len(sources),
            "cited": len(replied.sources),
            "invalid_citations": replied.invalid_citations,
            "answer_ms": replied.duration_ms,
        },
    )


def _refusal(question: str, mode: str, reason: str, *, sql: str | None = None) -> QuestionAnswer:
    """A "cannot answer" in the shape the contract expects.

    `sql` is carried through even on a failure: the Soru screen shows it, and a
    query an operator can read is worth more than a blank box when the answer
    did not arrive.
    """
    return QuestionAnswer(
        question=question,
        answer=None,
        mode=mode,
        answerable=False,
        refusal_reason=reason,
        sources=[],
        sql=sql,
        row_count=None,
        duration_ms=0,
    )


def _log_question(
    db: Session,
    *,
    question: str,
    question_id: str,
    route: RouteResult,
    answer: QuestionAnswer,
    detail: dict,
) -> None:
    """Record the question in audit_trail.

    Written directly rather than through worker/pipeline.py's log_audit:
    importing that module would drag the extraction and masking pipeline into
    the rag service for the sake of eight lines, and pipeline.py belongs to the
    backend pair (CLAUDE.md §3).

    claim_id stays NULL - a question is not about one claim, and the column is
    nullable (api/models/db.py:46).

    A failure here must not cost the operator their answer: the answer already
    exists, and losing it to a logging problem would be the worst possible
    trade. The exception is logged, not raised.
    """
    try:
        db.add(
            AuditTrail(
                claim_id=None,
                step=AUDIT_STEP,
                # ADR-001: OpenAI is the only provider the code reads.
                provider="openai",
                duration_ms=answer.duration_ms,
                detail={
                    "question_id": question_id,
                    "question": question,
                    "route": str(route.route),
                    "mode": answer.mode,
                    "answerable": answer.answerable,
                    "refusal_reason": answer.refusal_reason,
                    "router_reasoning": route.reasoning,
                    "router_ms": route.duration_ms,
                    "urgency_filter": route.urgency,
                    "status_filter": route.status,
                    **detail,
                },
            )
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        log.exception("rag_audit_write_failed", question_id=question_id)
