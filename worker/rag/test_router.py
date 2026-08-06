# worker/rag/test_router.py
"""Tests for question routing. The LLM client is a stub; nothing reaches the network."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from worker.llm.client import ModelTier
from worker.rag.router import QuestionRoute, Route, route_question

STUB_MODEL = "gpt-4o-mini-stub"


class StubClient:
    def __init__(self, reply: QuestionRoute) -> None:
        self.reply = reply
        self.calls: list[dict] = []
        self.settings = SimpleNamespace(model_for=lambda tier: STUB_MODEL)

    def structured(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


def _reply(**kwargs) -> QuestionRoute:
    defaults = {
        "reasoning": "test",
        "route": Route.RETRIEVAL,
        "urgency": None,
        "status": None,
    }
    return QuestionRoute(**{**defaults, **kwargs})


def test_counting_question_goes_to_sql():
    client = StubClient(_reply(route=Route.SQL))

    result = route_question("kac kritik ihbar geldi", question_id="q1", client=client)

    assert result.route is Route.SQL
    assert result.mode == "sql"


def test_content_question_without_filters_is_plain_retrieval():
    client = StubClient(_reply(route=Route.RETRIEVAL))

    result = route_question("dolu hasari nasil tarif ediliyor", question_id="q1", client=client)

    assert result.mode == "retrieval"
    assert result.urgency is None


def test_retrieval_with_a_filter_is_hybrid():
    """The mode name the Soru screen shows comes from this rule."""
    client = StubClient(_reply(route=Route.RETRIEVAL, urgency="critical"))

    result = route_question("kritik ihbarlarda ne anlatiliyor", question_id="q1", client=client)

    assert result.mode == "hybrid"
    assert result.urgency == "critical"


def test_status_filter_alone_also_counts_as_hybrid():
    client = StubClient(_reply(route=Route.RETRIEVAL, status="approved"))

    assert route_question("onaylanmis ihbarlar", question_id="q1", client=client).mode == "hybrid"


def test_filters_are_dropped_on_the_sql_path():
    """On the SQL path the condition belongs inside the generated query.

    Carrying it here as well would give one WHERE clause two sources of truth,
    and they would disagree the first time either changed.
    """
    client = StubClient(_reply(route=Route.SQL, urgency="critical", status="approved"))

    result = route_question("kac kritik ihbar var", question_id="q1", client=client)

    assert result.urgency is None
    assert result.status is None
    assert result.mode == "sql"


def test_invalid_urgency_is_rejected_by_the_schema():
    """A plain str field would let "acil" through, and a filter matching nothing
    reads as "no such claims exist" rather than as a bug."""
    with pytest.raises(ValidationError):
        QuestionRoute(reasoning="x", route=Route.RETRIEVAL, urgency="acil")


def test_cheap_tier_is_the_default():
    client = StubClient(_reply())

    route_question("soru", question_id="q1", client=client)

    assert client.calls[0]["tier"] is ModelTier.CHEAP


def test_result_carries_what_the_audit_trail_needs():
    client = StubClient(_reply(reasoning="icerik sorusu"))

    result = route_question("soru", question_id="q1", client=client)

    assert result.model == STUB_MODEL
    assert result.duration_ms >= 0
    assert result.reasoning == "icerik sorusu"


def test_prompt_can_be_overridden_for_eval():
    client = StubClient(_reply())

    route_question("soru", question_id="q1", client=client, system_prompt="OZEL PROMPT")

    assert client.calls[0]["system_prompt"] == "OZEL PROMPT"
