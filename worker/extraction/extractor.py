# worker/extraction/extractor.py
"""Extraction step: prompt + LLM client + quote resolution.

Knows nothing about the database. `worker/pipeline.py` calls `extract()` and
owns persistence, the audit trail and error handling (agreed with @nursenakyga
on 2026-07-30).

Design doc §3.2, principle 2: every value must be traceable to the source text.
The model returns quotes; this module locates each one and records its character
span. A quote that cannot be found is the hallucination signal, so its field is
demoted to low confidence instead of being trusted.
"""

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from worker.extraction.schema import ClaimExtraction
from worker.llm.client import LlmClient, ModelTier, get_llm_client

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "extraction_v1.txt"

# Read once: the prompt is static and identical for every message.
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")

# Fields the model may fill in, in the dotted form used as source_references keys.
SCALAR_FIELDS = (
    "policy_no",
    "plate",
    "incident_date",
    "damage_description",
    "damage_type",
    "injury",
    "counterparty_exists",
    "estimated_amount",
)


class SourceReference(BaseModel):
    """A quote and where it sits in the source text — schemas/claim.json shape."""

    quote: str
    start: int | None = None
    end: int | None = None


class ExtractionResult(BaseModel):
    """Split by where each part belongs.

    `extraction` goes into Claim.data["extraction"]. `reasoning` and the timing
    belong in audit_trail, not in the operator-facing record (design doc §3.3).
    """

    extraction: dict[str, Any]
    reasoning: str
    model: str
    duration_ms: int
    unverified_fields: list[str]


def build_user_content(text: str, received_at: datetime, channel: str) -> str:
    """The message half of the request. Mirrors the examples inside the prompt."""
    return (
        f"Mesajın geliş tarihi: {received_at.isoformat()}\n"
        f"Kanal: {channel}\n\n"
        f"--- İHBAR METNİ ---\n{text}"
    )


def locate_quote(quote: str, text: str) -> tuple[int, int] | None:
    """Return the character span of `quote` inside `text`, or None.

    Exact match first. Failing that, the same words separated by any whitespace:
    models reflow line breaks, and that alone should not condemn a field.
    """
    index = text.find(quote)
    if index >= 0:
        return index, index + len(quote)

    words = quote.split()
    if not words:
        return None

    pattern = re.compile(r"\s+".join(re.escape(word) for word in words))
    match = pattern.search(text)
    return (match.start(), match.end()) if match else None


def filled_field_names(answer: ClaimExtraction) -> list[str]:
    """Names of the fields the model actually filled in, dotted where nested."""
    names = [name for name in SCALAR_FIELDS if getattr(answer, name) is not None]
    names += [
        f"incident_location.{part}"
        for part in ("city", "district")
        if getattr(answer.incident_location, part) is not None
    ]
    return names


def field_value(answer: ClaimExtraction, name: str) -> object:
    """Read a field by its dotted name, the same form used in source_references."""
    if "." in name:
        parent, child = name.split(".", 1)
        return getattr(getattr(answer, parent), child)
    return getattr(answer, name)


def resolve_references(
    answer: ClaimExtraction, text: str
) -> tuple[dict[str, SourceReference], list[str]]:
    """Locate every quote; report the fields whose evidence did not hold up."""
    resolved: dict[str, SourceReference] = {}
    unverified: list[str] = []

    for field, quote in answer.source_references.items():
        span = locate_quote(quote, text)
        if span is None:
            resolved[field] = SourceReference(quote=quote)
            unverified.append(field)
        else:
            resolved[field] = SourceReference(quote=quote, start=span[0], end=span[1])

    # A filled field with no quote of its own is not automatically unsupported.
    # Measured 2026-08-01: where the text reads "İzmir Buca'da", the model files
    # one quote under incident_location.city and leaves district without one —
    # 21 of 39 flags came from that alone. If the value itself is in the source,
    # that is evidence; if it is not, the field stays flagged.
    for name in filled_field_names(answer):
        if name in resolved:
            continue
        span = locate_quote(str(field_value(answer, name)), text)
        if span is None:
            unverified.append(name)
        else:
            resolved[name] = SourceReference(
                quote=text[span[0] : span[1]], start=span[0], end=span[1]
            )

    return resolved, unverified


def extract(
    text: str,
    received_at: datetime,
    channel: str,
    *,
    message_id: str,
    external_ref: str | None = None,
    client: LlmClient | None = None,
    seed: int | None = None,
    tier: ModelTier = ModelTier.CHEAP,
    system_prompt: str | None = None,
) -> ExtractionResult:
    """Run one extraction over `text`, which the pipeline has already masked.

    `external_ref` is the gt_id replay wrote onto the message, and it is only
    read offline (DEMO_OFFLINE), where it picks the recorded answer for this
    record. `message_id` stays what it was - this database's row id, the thing
    every llm_call log line ties back to - because the two answer different
    questions and neither substitutes for the other.

    `seed` is for eval runs, where week-to-week comparability matters more than
    anything else; the live pipeline leaves it unset.

    `tier` defaults to the cheap model. ADR-001 first put extraction on the
    strong tier, before either had been measured; a 100-record run on 2026-08-02
    scored gpt-4o-mini at 99.4% on the required fields against a target of 82%,
    so the default moved. The parameter stays so eval can compare tiers.

    `system_prompt` defaults to the versioned file. Overriding it lets eval
    compare prompt variants on one sample; the pipeline never passes it.
    """
    client = client or get_llm_client(external_ref=external_ref)
    started = time.perf_counter()

    answer = client.structured(
        tier=tier,
        response_model=ClaimExtraction,
        system_prompt=system_prompt or SYSTEM_PROMPT,
        user_content=build_user_content(text, received_at, channel),
        message_id=message_id,
        seed=seed,
    )
    duration_ms = round((time.perf_counter() - started) * 1000)

    references, unverified = resolve_references(answer, text)

    payload = answer.model_dump(mode="json", exclude={"reasoning", "source_references"})
    payload["source_references"] = {
        field: reference.model_dump(mode="json") for field, reference in references.items()
    }
    # Demote whatever we could not verify. The model's own list is kept, not
    # replaced — it knows things a text search cannot see.
    payload["low_confidence_fields"] = sorted(set(answer.low_confidence_fields) | set(unverified))

    return ExtractionResult(
        extraction=payload,
        reasoning=answer.reasoning,
        model=client.settings.model_for(tier),
        duration_ms=duration_ms,
        unverified_fields=sorted(set(unverified)),
    )
