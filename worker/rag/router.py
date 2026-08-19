# worker/rag/router.py
"""Decides which path answers a question, and pulls any filters out of it.

Design doc §7. Two paths exist: Text-to-SQL for questions that need a number
over every record, retrieval for questions answered by reading a few. Sending a
question down the wrong one produces a confident wrong answer, so this runs
before either.

Nothing here executes anything. It reads a question and returns a decision.
"""

import time
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from worker.llm.client import LlmClient, ModelTier

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "rag_router_v2.txt"

# Read once: the prompt is static and identical for every question.
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")


class Route(StrEnum):
    SQL = "sql"
    RETRIEVAL = "retrieval"


class QuestionRoute(BaseModel):
    """What the model fills in.

    urgency and status are Literals rather than plain strings on purpose. A
    model that answers "acil" instead of "critical" would produce a filter
    matching nothing, and a search that quietly returns zero rows looks like
    "no such claims exist" rather than like a bug. Pydantic rejects the value
    instead, and instructor asks again.
    """

    reasoning: str = Field(
        description="Bu yolu neden seçtin? En fazla 2 cümle.",
    )
    route: Route = Field(
        description=(
            "sql: sayı, toplam, ortalama, sıralama isteyen sorular. "
            "retrieval: ihbarların içeriğini soran sorular."
        ),
    )
    urgency: Literal["critical", "high", "normal"] | None = Field(
        default=None,
        description="Soru aciliyet belirtiyorsa doldur, geçmiyorsa null bırak.",
    )
    status: Literal["in_human_review", "approved", "archived"] | None = Field(
        default=None,
        description="Soru kayıt durumu belirtiyorsa doldur, geçmiyorsa null bırak.",
    )


class RouteResult(BaseModel):
    """The decision, plus what the audit trail needs."""

    route: Route
    urgency: str | None
    status: str | None
    reasoning: str
    model: str
    duration_ms: int

    @property
    def mode(self) -> str:
        """The mode name the frontend contract uses.

        A retrieval question carrying a filter is what that contract calls
        hybrid: text search narrowed by a structured condition. Computed here so
        the endpoint does not restate the rule and drift from it.
        """
        if self.route is Route.SQL:
            return "sql"
        return "hybrid" if (self.urgency or self.status) else "retrieval"


def route_question(
    question: str,
    *,
    question_id: str,
    client: LlmClient | None = None,
    tier: ModelTier = ModelTier.CHEAP,
    seed: int | None = None,
    system_prompt: str | None = None,
) -> RouteResult:
    """Pick a path for `question` and extract its filters.

    One call does both. Routing and filtering read the same sentence, and
    asking twice would double the latency of a step that sits in front of an
    already slow request.

    `seed` is for eval runs, where week-to-week comparability matters more than
    anything else; a live question leaves it unset. `system_prompt` defaults to
    the versioned file and is overridable so eval can compare prompt variants
    on one sample.
    """
    client = client or LlmClient()
    started = time.perf_counter()

    answer = client.structured(
        tier=tier,
        response_model=QuestionRoute,
        system_prompt=system_prompt or SYSTEM_PROMPT,
        user_content=f"SORU: {question}",
        message_id=question_id,
        seed=seed,
    )
    duration_ms = round((time.perf_counter() - started) * 1000)

    return RouteResult(
        route=answer.route,
        # Filters are only meaningful on the retrieval path. On the SQL path the
        # condition belongs inside the generated query, and carrying it here as
        # well invites two sources of truth for one WHERE clause.
        urgency=answer.urgency if answer.route is Route.RETRIEVAL else None,
        status=answer.status if answer.route is Route.RETRIEVAL else None,
        reasoning=answer.reasoning,
        model=client.settings.model_for(tier),
        duration_ms=duration_ms,
    )
