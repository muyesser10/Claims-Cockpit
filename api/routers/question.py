# api/routers/question.py
"""Proxies POST /soru to the rag service (ADR-003).

The answer is produced by a separate container: /soru needs a local embedding
model, and torch in the api image would undo PR #52's build work. The web app
never learns this split exists - it keeps talking to one origin through the
existing /api/... proxy.

This module deliberately imports nothing from worker/. api/Dockerfile does not
copy that directory, so such an import would work in a dev checkout and fail in
the built image.
"""

import os

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.dependencies import get_current_user
from api.models.db import User

log = structlog.get_logger("api.question")

router = APIRouter(tags=["soru"])

RAG_SERVICE_URL = os.environ.get("RAG_SERVICE_URL", "http://rag:8100")

# A RAG answer takes 8-20s: a local embedding plus two or three LLM calls, each
# with its own 30s ceiling. This has to outlast the slowest honest answer while
# still ending a request against a service that has hung.
RAG_TIMEOUT_SECONDS = 120.0

RAG_UNREACHABLE_DETAIL = "Soru servisine ulaşılamıyor."
RAG_TIMEOUT_DETAIL = "Soru zaman aşımına uğradı, lütfen tekrar deneyin."


class QuestionRequest(BaseModel):
    """An operator's Turkish question.

    Length bounds live in the rag service rather than here. It validates the
    same field, and its 422 travels back unchanged - two copies of one ceiling
    would only differ eventually.
    """

    question: str


class QuestionSource(BaseModel):
    """One source chip behind an answer.

    Mirrors worker/rag/retrieval.py's RetrievedClaim, which this package cannot
    import (see the module docstring). The contract is frozen and shared with
    web/src/api/useQuestion.ts; test_question.py asserts the two definitions
    still carry the same fields, so a change on either side fails loudly rather
    than silently dropping a chip.
    """

    claim_id: int
    external_ref: str | None
    snippet: str
    score: float
    urgency: str | None
    incident_date: str | None


class QuestionResponse(BaseModel):
    """The /soru answer. Mirrors worker/rag/ask.py's QuestionAnswer.

    `mode` is one of sql | retrieval | hybrid, and `sources` is empty on the SQL
    path where `sql` and `row_count` are filled in instead.
    """

    question: str
    answer: str | None
    mode: str
    answerable: bool
    refusal_reason: str | None
    sources: list[QuestionSource]
    sql: str | None
    row_count: int | None
    duration_ms: int


@router.post("/soru", response_model=QuestionResponse)
async def ask_question(
    body: QuestionRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> QuestionResponse:
    """Answer a Turkish question about the claims.

    Authenticated here as well as in the rag service. Checking twice costs one
    user lookup and means an unauthenticated request never reaches the network;
    the rag service still checks for itself, because it must not depend on this
    hop being the only door (ADR-003).

    `async def`, unlike the rag service's own handler: the work here is waiting
    on a socket, not blocking on a model. Twenty concurrent questions in a
    threadpool would exhaust it; awaiting them costs nothing.
    """
    token = request.headers.get("Authorization")

    try:
        # A client per request rather than one shared in the lifespan: a question
        # arrives every few seconds at most, and the connection setup disappears
        # next to a 10-second answer. Not worth adding state to api/main.py for.
        async with httpx.AsyncClient(timeout=RAG_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{RAG_SERVICE_URL}/soru",
                json={"question": body.question},
                headers={"Authorization": token} if token else {},
            )
    except httpx.TimeoutException:
        log.warning("rag_proxy_timeout", user=user.email, timeout=RAG_TIMEOUT_SECONDS)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=RAG_TIMEOUT_DETAIL,
        ) from None
    except httpx.RequestError as exc:
        log.error("rag_proxy_unreachable", url=RAG_SERVICE_URL, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=RAG_UNREACHABLE_DETAIL,
        ) from None

    if response.status_code != status.HTTP_200_OK:
        # Passed through rather than flattened: a 401 from the rag service is an
        # authentication failure, and reporting it as a 502 would send the
        # frontend looking for an outage instead of a login.
        log.warning("rag_proxy_error", status=response.status_code, user=user.email)
        raise HTTPException(status_code=response.status_code, detail=_detail_of(response))

    return QuestionResponse(**response.json())


def _detail_of(response: httpx.Response) -> object:
    """The rag service's own error message, however it phrased it.

    FastAPI puts a string under `detail` for an HTTPException and a list for a
    422; both are passed on as they are. A body that is not JSON at all - a
    proxy's own error page, say - falls back to the raw text.
    """
    try:
        return response.json().get("detail", response.text)
    except ValueError:
        return response.text
