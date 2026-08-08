# worker/rag/answer.py
"""Turns retrieved claims into a Turkish answer that cites them.

Design doc §7.3. The retrieval half found the records; this half writes the
sentence an operator reads. It knows nothing about the database - it takes the
claims retrieval already found and hands back an answer.

Citations are checked here rather than trusted. A model that writes [7] over
four sources has produced something that looks sourced and is not, and that
failure is invisible downstream: the number renders, the chip is missing, and
nobody can tell whether the record behind the sentence ever existed.
"""

import re
import time
from pathlib import Path

import structlog
from pydantic import BaseModel, Field

from worker.llm.client import LlmClient, ModelTier
from worker.rag.retrieval import RetrievedClaim

log = structlog.get_logger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "rag_answer_v1.txt"

# Read once: the rules are static, only the sources change per question.
PROMPT_TEMPLATE = PROMPT_PATH.read_text(encoding="utf-8")

# Same reason as schema_context.py's SCHEMA_PLACEHOLDER: the prompt is full of
# brackets, so str.format() over it would fail or silently mangle an example.
SOURCES_PLACEHOLDER = "<<SOURCES>>"

CITATION_PATTERN = re.compile(r"\[(\d+)\]")

NO_SOURCES_REFUSAL = "Soruyla eşleşen bir ihbar kaydı bulunamadı."
UNSOURCED_REFUSAL = "Cevap üretildi ancak hiçbir kaynağa dayandırılamadı, bu yüzden gösterilmiyor."


class RagAnswer(BaseModel):
    """What the model fills in.

    Descriptions are shipped to the model as part of the tool schema, so they
    are written in Turkish for it. Repo-internal notes stay in `#` comments.
    """

    # Reasoning first, deliberately: it makes the model settle which source
    # answers what before it commits to a sentence.
    reasoning: str = Field(
        description=(
            "Önce kısa muhakeme: hangi kaynak soruya ne cevap veriyor, hangisini "
            "neden kullanmadın. En fazla 3 cümle."
        ),
    )
    answerable: bool = Field(
        description=(
            "Soru sana verilen kaynaklarla cevaplanabiliyor mu? Sayım isteyen "
            "sorularda ve cevabı kaynaklarda geçmeyen sorularda false ver."
        ),
    )
    answer: str | None = Field(
        default=None,
        description=(
            "Türkçe cevap, en fazla 4 cümle. Her cümlenin sonunda dayandığı "
            "kaynağın numarası köşeli parantez içinde olmalı: [1] veya [1][3]. "
            "answerable=false ise null bırak."
        ),
    )
    refusal_reason: str | None = Field(
        default=None,
        description=(
            "answerable=false ise sorunun neden cevaplanamadığını tek Türkçe "
            "cümleyle yaz. answerable=true ise null bırak."
        ),
    )
    used_sources: list[int] = Field(
        default_factory=list,
        description=(
            "Cevabında gerçekten atıf yaptığın kaynak numaraları. Okuyup "
            "kullanmadığın kaynağı buraya yazma, var olmayan numara yazma."
        ),
    )


class AnswerResult(BaseModel):
    """What the service returns and the audit trail records."""

    answerable: bool
    answer: str | None
    refusal_reason: str | None
    reasoning: str
    # Only the sources the model actually cited, in its own numbering order.
    # `answer`'s markers are rewritten to match this list, so [1] in the text is
    # the first chip on screen and [2] the second - see renumber_citations.
    sources: list[RetrievedClaim]
    # Numbers cited that point at no source. Kept rather than dropped silently:
    # this is the hallucination signal the error centre needs.
    invalid_citations: list[int]
    model: str
    duration_ms: int


def build_sources_block(sources: list[RetrievedClaim]) -> str:
    """The numbered source list the prompt is built around.

    Numbering starts at 1 because the model writes [1], not [0]; an off-by-one
    here would misattribute every citation in the answer.
    """
    blocks = []
    for number, source in enumerate(sources, start=1):
        date = source.incident_date or "belirtilmemiş"
        urgency = source.urgency or "belirtilmemiş"
        blocks.append(f"[{number}] (aciliyet: {urgency}, olay tarihi: {date})\n{source.snippet}")
    return "\n\n".join(blocks)


def build_system_prompt(sources: list[RetrievedClaim]) -> str:
    """The versioned prompt with this question's sources injected."""
    return PROMPT_TEMPLATE.replace(SOURCES_PLACEHOLDER, build_sources_block(sources))


def split_citations(cited: list[int], source_count: int) -> tuple[list[int], list[int]]:
    """Separate citations that point at a real source from those that do not.

    Duplicates collapse: a model citing [2] twice means one chip, not two.
    """
    seen: set[int] = set()
    valid: list[int] = []
    invalid: list[int] = []
    for number in cited:
        if number in seen:
            continue
        seen.add(number)
        if 1 <= number <= source_count:
            valid.append(number)
        else:
            invalid.append(number)
    return valid, invalid


def renumber_citations(answer: str, valid: list[int]) -> str:
    """Rewrite the answer's citation markers to match the sources it ships with.

    Only cited sources come back, so a reply citing [1] and [3] out of five
    arrives with two chips - and the [3] in its text then points at a chip that
    is not on screen. Seen end to end on 2026-08-06: the model answered from
    sources 1 and 3, the operator got two chips, and the second one was labelled
    [3] in the prose with nothing to match it.

    Numbers are remapped to their new position rather than left alone, and a
    marker that resolves to nothing is dropped from the text: a number the
    reader cannot follow to a source is worse than no number at all.
    """
    positions = {old: new for new, old in enumerate(valid, start=1)}

    def replace(match: re.Match[str]) -> str:
        new = positions.get(int(match.group(1)))
        return f"[{new}]" if new is not None else ""

    rewritten = CITATION_PATTERN.sub(replace, answer)
    # Dropping a marker leaves the space in front of it behind, as "cümle ." or
    # a double space mid-sentence.
    rewritten = re.sub(r"\s+([.,;:!?])", r"\1", rewritten)
    return re.sub(r" {2,}", " ", rewritten).strip()


def answer_question(
    question: str,
    sources: list[RetrievedClaim],
    *,
    question_id: str,
    client: LlmClient | None = None,
    tier: ModelTier = ModelTier.CHEAP,
    seed: int | None = None,
) -> AnswerResult:
    """Answer `question` from `sources`, withholding anything unsourced.

    `tier` defaults to the cheap model, as everything else has since ADR-001's
    2026-08-04 update. Summarising is not extraction and has not been measured
    here; the parameter stays so the 40-question set can put both tiers on one
    sample.

    An empty `sources` list never reaches the model: there is nothing to answer
    from, and asking anyway invites exactly the invention the prompt forbids.
    """
    if not sources:
        return AnswerResult(
            answerable=False,
            answer=None,
            refusal_reason=NO_SOURCES_REFUSAL,
            reasoning="retrieval returned no claims",
            sources=[],
            invalid_citations=[],
            model="none",
            duration_ms=0,
        )

    client = client or LlmClient()
    started = time.perf_counter()

    reply = client.structured(
        tier=tier,
        response_model=RagAnswer,
        system_prompt=build_system_prompt(sources),
        user_content=f"SORU: {question}",
        message_id=question_id,
        seed=seed,
    )
    duration_ms = round((time.perf_counter() - started) * 1000)
    model_name = client.settings.model_for(tier)

    valid, invalid = split_citations(reply.used_sources, len(sources))
    if invalid:
        log.warning(
            "rag_invalid_citation",
            question_id=question_id,
            invalid=invalid,
            source_count=len(sources),
        )

    # An answer whose citations all fail to resolve is not a weakly sourced
    # answer, it is an unsourced one. Everywhere else in this system an
    # unverifiable claim is withheld rather than shown - extraction drops a
    # field's confidence when its quote is absent, the SQL guard refuses a query
    # it cannot vet - and RAG has less protection than either: nothing sits
    # between this text and the operator's decision.
    if reply.answerable and not valid:
        log.warning(
            "rag_answer_without_valid_citation",
            question_id=question_id,
            invalid=invalid,
            source_count=len(sources),
        )
        return AnswerResult(
            answerable=False,
            answer=None,
            refusal_reason=UNSOURCED_REFUSAL,
            reasoning=reply.reasoning,
            sources=[],
            invalid_citations=invalid,
            model=model_name,
            duration_ms=duration_ms,
        )

    return AnswerResult(
        answerable=reply.answerable,
        # Renumbered to the filtered list: the text and the chips have to agree.
        answer=renumber_citations(reply.answer, valid) if reply.answer else reply.answer,
        refusal_reason=reply.refusal_reason,
        reasoning=reply.reasoning,
        sources=[sources[number - 1] for number in valid],
        invalid_citations=invalid,
        model=model_name,
        duration_ms=duration_ms,
    )
