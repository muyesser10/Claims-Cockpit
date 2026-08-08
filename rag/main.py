# rag/main.py
"""The /soru service (ADR-003).

A separate compose service, built from the worker image with a different
command. It exists because the retrieval path embeds the question with a local
sentence-transformers model, and putting torch in the api image would undo the
build work of PR #52.

Deliberately thin: every decision lives in worker/rag/ask.py, which knows
nothing about HTTP. This file authenticates, holds a session, and calls it.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, HTTPException, status
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies import get_current_user
from api.models.db import User
from worker.embedding.store import get_encoder
from worker.rag.ask import QuestionAnswer, ask

log = structlog.get_logger(__name__)

# An operator's question. Long enough for a real one, short enough that nobody
# can push a document through three LLM prompts.
MIN_QUESTION_CHARS = 3
MAX_QUESTION_CHARS = 500

# Set once the e5 model is in memory. The first question would otherwise pay a
# 470 MB download and a model load on top of its own 8-20 seconds, and /health
# would report ready while the service was not.
_model_ready = False


class QuestionRequest(BaseModel):
    question: str = Field(min_length=MIN_QUESTION_CHARS, max_length=MAX_QUESTION_CHARS)


def _preload_model() -> None:
    """Load the encoder at startup rather than on the first question."""
    global _model_ready
    get_encoder()
    _model_ready = True
    log.info("rag_model_loaded")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Loading blocks for about a second. Doing it here blocks the loop before
    # the loop has anything else to do, which is simpler than a thread for a
    # one-off and means /health never reports ready too early.
    _preload_model()
    yield


app = FastAPI(title="Claims-Cockpit RAG", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health():
    """Liveness, deliberately unauthenticated - same reasoning as the api's.

    `model_ready` is the part worth reading: the process answers HTTP a second
    after it starts and cannot answer a question until the model is in memory.
    """
    return {"status": "ok", "service": "rag", "model_ready": _model_ready}


@app.post("/soru", response_model=QuestionAnswer)
def soru(
    request: QuestionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QuestionAnswer:
    """Answer a Turkish question about the claims.

    Declared `def`, not `async def`, on purpose. ask() is synchronous and blocks
    for 8-20 seconds - in a coroutine that would stall the event loop and every
    other request with it. FastAPI runs a sync endpoint in a threadpool instead.

    Authenticated here rather than trusted from the proxy (ADR-003): this is a
    read path into claim data, and it must not repeat /ingest's deliberate
    exemption by accident. Any logged-in role may ask; asking is a read, and
    /claims and /queue are gated the same way.
    """
    try:
        return ask(db, request.question)
    except Exception:
        log.exception("rag_question_failed", user=user.email)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Soru işlenirken beklenmeyen bir hata oluştu.",
        ) from None


# Auto HTTP metrics + GET /metrics, same as the api. Unauthenticated on purpose:
# Prometheus cannot carry a user JWT. Adding this service as a scrape target is
# an edit to monitoring/prometheus.yml, which the backend pair owns.
Instrumentator().instrument(app).expose(app)
