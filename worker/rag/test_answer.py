# worker/rag/test_answer.py
"""Tests for answer synthesis and its citation check.

Nothing here reaches the network: the LLM client is a stub that returns a
prepared RagAnswer and records how it was called.
"""

from types import SimpleNamespace

from worker.llm.client import ModelTier
from worker.rag.answer import (
    NO_SOURCES_REFUSAL,
    SOURCES_PLACEHOLDER,
    UNSOURCED_REFUSAL,
    AnswerResult,
    RagAnswer,
    answer_question,
    build_sources_block,
    build_system_prompt,
    renumber_citations,
    split_citations,
)
from worker.rag.retrieval import RetrievedClaim

STUB_MODEL = "gpt-4o-mini-stub"


class StubClient:
    """Returns a prepared answer and records the call."""

    def __init__(self, reply: RagAnswer) -> None:
        self.reply = reply
        self.calls: list[dict] = []
        self.settings = SimpleNamespace(model_for=lambda tier: STUB_MODEL)

    def structured(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


def _source(claim_id: int, *, urgency: str | None = "normal", date: str | None = "2026-07-14"):
    return RetrievedClaim(
        claim_id=claim_id,
        external_ref=f"GT-{claim_id:06d}",
        snippet=f"{claim_id} numarali kaydin cumlesi.",
        score=0.9,
        urgency=urgency,
        incident_date=date,
    )


def _reply(**kwargs) -> RagAnswer:
    defaults = {
        "reasoning": "test",
        "answerable": True,
        "answer": "Cevap [1]",
        "refusal_reason": None,
        "used_sources": [1],
    }
    return RagAnswer(**{**defaults, **kwargs})


def test_no_sources_refuses_without_calling_the_model():
    """Asking a model to answer from nothing invites the invention the prompt
    spends seven rules forbidding."""
    client = StubClient(_reply())

    result = answer_question("soru", [], question_id="q1", client=client)

    assert client.calls == []
    assert result.answerable is False
    assert result.refusal_reason == NO_SOURCES_REFUSAL
    assert result.sources == []


def test_only_cited_sources_come_back_in_the_models_order():
    sources = [_source(10), _source(20), _source(30)]
    client = StubClient(_reply(answer="Cevap [3][1]", used_sources=[3, 1]))

    result = answer_question("soru", sources, question_id="q1", client=client)

    assert [s.claim_id for s in result.sources] == [30, 10]
    assert result.invalid_citations == []


def test_the_answers_numbers_follow_the_sources_it_ships_with():
    """The bug this renumbering exists for.

    Cite 1 and 3 out of five and only two chips come back; left alone, the [3]
    in the prose points at a third chip that is not on screen.
    """
    sources = [_source(10), _source(20), _source(30), _source(40), _source(50)]
    client = StubClient(_reply(answer="Önce şu [1], sonra şu [3].", used_sources=[1, 3]))

    result = answer_question("soru", sources, question_id="q1", client=client)

    assert result.answer == "Önce şu [1], sonra şu [2]."
    assert [s.claim_id for s in result.sources] == [10, 30]


def test_renumbering_follows_the_models_own_order():
    sources = [_source(10), _source(20), _source(30)]
    client = StubClient(_reply(answer="Önce [3], sonra [1].", used_sources=[3, 1]))

    result = answer_question("soru", sources, question_id="q1", client=client)

    # [3] was cited first, so it is the first chip - and now reads as [1].
    assert result.answer == "Önce [1], sonra [2]."


def test_a_marker_pointing_at_nothing_is_dropped_from_the_text():
    sources = [_source(10), _source(20)]
    client = StubClient(_reply(answer="Bir kaynak var [1], bir de bu [7].", used_sources=[1, 7]))

    result = answer_question("soru", sources, question_id="q1", client=client)

    # The unfollowable number is gone; the space it left behind is too.
    assert result.answer == "Bir kaynak var [1], bir de bu."
    assert result.invalid_citations == [7]


def test_renumber_citations_leaves_an_already_correct_answer_alone():
    assert renumber_citations("Tek kaynak [1].", [1]) == "Tek kaynak [1]."


def test_renumber_citations_handles_two_markers_side_by_side():
    assert renumber_citations("Cevap [2][4]", [2, 4]) == "Cevap [1][2]"


def test_citation_pointing_at_nothing_is_reported_not_silently_dropped():
    sources = [_source(10), _source(20)]
    client = StubClient(_reply(answer="Cevap [1][7]", used_sources=[1, 7]))

    result = answer_question("soru", sources, question_id="q1", client=client)

    # The real citation still carries the answer.
    assert [s.claim_id for s in result.sources] == [10]
    assert result.invalid_citations == [7]
    assert result.answerable is True


def test_answer_with_no_resolvable_citation_is_withheld():
    """The defence this module exists for.

    A model that answers and cites only numbers that do not exist has produced
    an unsourced answer. Nothing sits between this text and the operator's
    decision, so it is not shown.
    """
    sources = [_source(10), _source(20)]
    client = StubClient(_reply(answer="Emin bir cevap [9]", used_sources=[9]))

    result = answer_question("soru", sources, question_id="q1", client=client)

    assert result.answerable is False
    assert result.answer is None
    assert result.refusal_reason == UNSOURCED_REFUSAL
    assert result.sources == []
    # Still recorded: "the model answered but could not ground it" is a signal
    # the error centre needs, not something to swallow.
    assert result.invalid_citations == [9]


def test_models_own_refusal_keeps_its_reason():
    """The citation check must not overwrite a refusal that already explains
    itself - a counting question is refused for being a counting question."""
    sources = [_source(10)]
    client = StubClient(
        _reply(
            answerable=False,
            answer=None,
            refusal_reason="Bu bir sayim sorusu, verilen kayitlar tamami degil.",
            used_sources=[],
        )
    )

    result = answer_question("kac tane", sources, question_id="q1", client=client)

    assert result.answerable is False
    assert result.refusal_reason == "Bu bir sayim sorusu, verilen kayitlar tamami degil."
    assert result.refusal_reason != UNSOURCED_REFUSAL


def test_same_source_cited_twice_is_one_chip():
    sources = [_source(10), _source(20)]
    client = StubClient(_reply(answer="Bir [2]. Iki [2].", used_sources=[2, 2]))

    result = answer_question("soru", sources, question_id="q1", client=client)

    assert [s.claim_id for s in result.sources] == [20]


def test_sources_block_numbers_from_one():
    """Numbering from zero would misattribute every citation in every answer."""
    block = build_sources_block([_source(10), _source(20)])

    assert block.startswith("[1] ")
    assert "\n\n[2] " in block


def test_missing_urgency_and_date_are_written_as_unknown():
    block = build_sources_block([_source(10, urgency=None, date=None)])

    assert "belirtilmemiş" in block
    assert "None" not in block


def test_system_prompt_injects_sources_and_keeps_the_rules():
    prompt = build_system_prompt([_source(10)])

    assert SOURCES_PLACEHOLDER not in prompt
    assert "10 numarali kaydin cumlesi." in prompt
    assert "HER CÜMLEYE ATIF" in prompt


def test_split_citations_handles_out_of_range_numbers():
    valid, invalid = split_citations([1, 0, -3, 2, 5], source_count=2)

    assert valid == [1, 2]
    assert invalid == [0, -3, 5]


def test_cheap_tier_is_the_default():
    """ADR-001 (2026-08-04 update) put everything on the cheap model."""
    client = StubClient(_reply())

    answer_question("soru", [_source(10)], question_id="q1", client=client)

    assert client.calls[0]["tier"] is ModelTier.CHEAP


def test_result_carries_what_the_audit_trail_needs():
    client = StubClient(_reply())

    result = answer_question("soru", [_source(10)], question_id="q1", client=client)

    assert isinstance(result, AnswerResult)
    assert result.model == STUB_MODEL
    assert result.duration_ms >= 0
    assert result.reasoning == "test"
