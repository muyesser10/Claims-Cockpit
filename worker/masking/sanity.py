# worker/masking/sanity.py
"""LLM-based sanity pass over already-masked text.

Regex + the name dictionary run first (worker/masking/pipeline.py); this is
the last line of defense for whatever they missed — a rare name, a phone
number in an odd format, an address. Same LLM client and prompt-loading
pattern as worker/extraction/extractor.py (S2-6).

The model is never asked to echo back the leaked text itself — only its
*kind* (name/phone/tc/...) and, best-effort, where it sits. A model that is
asked to find PII it should not have seen and hand it back to us just moves
the leak one hop, from the masked text into our own LLM response, logs and
DB rows. See git history on this file for the incident: an earlier version
put the raw snippet in flagged_snippets, which pipeline.py then wrote
verbatim into audit_trail.detail and Claim.data.masking_sanity_flags —
exactly what masking exists to prevent. Caught in review by @Cagri12345.
"""

import logging
import os
import time
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from worker.llm.client import LlmClient, ModelTier

logger = logging.getLogger("worker.masking.sanity")

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "masking_sanity_v1.txt"

# Read once: the prompt is static and identical for every message.
SANITY_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")

_ENV_FALSE_VALUES = {"false", "0", "no"}


class SanityFlagKind(StrEnum):
    """What kind of PII the model believes it spotted. No raw text — a
    category is all the operator/audit trail ever needs to know something
    slipped through; the actual value stays out of every DB row."""

    NAME = "name"
    PHONE = "phone"
    TC = "tc"
    PLATE = "plate"
    IBAN = "iban"
    ADDRESS = "address"
    OTHER = "other"


class SanityFlag(BaseModel):
    """One suspected leak: its kind, and where it sits in masked_text.

    `span` is the model's own best-effort [start, end) character offsets —
    it is never derived by searching masked_text for text the model gave us,
    because that would require the model to hand the leaked substring back
    in the first place. pipeline.py clamps it against the text's actual
    bounds and drops it to None if the model's guess does not fit; a bad
    offset only costs the highlight, never a fallback to raw text.
    """

    kind: SanityFlagKind
    span: tuple[int, int] | None = None


class SanityCheckResult(BaseModel):
    """The model's answer: is there PII left in the masked text."""

    leak_found: bool
    flags: list[SanityFlag] = []
    notes: str | None = None


def is_sanity_enabled() -> bool:
    """Whether the sanity pass should run at all.

    Defaults to on. Set MASKING_SANITY_ENABLED=false to skip it (and its
    OpenAI cost) entirely — independent of DEMO_OFFLINE, which nothing reads
    yet.
    """
    value = os.environ.get("MASKING_SANITY_ENABLED", "true").strip().lower()
    return value not in _ENV_FALSE_VALUES


def _clamp_span(span: tuple[int, int] | None, text_len: int) -> tuple[int, int] | None:
    """Drop a span that does not fit inside masked_text instead of trusting it.

    The model's offsets are a best-effort guess (see SanityFlag docstring),
    never verified by searching the text for text the model gave us. A span
    outside [0, text_len] or with start >= end is just discarded — the flag
    itself (its `kind`) is kept either way.
    """
    if span is None:
        return None
    start, end = span
    if 0 <= start < end <= text_len:
        return start, end
    return None


def check_sanity(
    masked_text: str,
    *,
    message_id: str,
    client: LlmClient | None = None,
    tier: ModelTier = ModelTier.CHEAP,
    seed: int | None = None,
) -> SanityCheckResult:
    """Ask the model whether `masked_text` still shows any PII.

    `message_id` is not in the original spec's signature but is required by
    LlmClient.structured() (no default) and is how every llm_call log line
    ties back to a raw_message_id (CLAUDE.md §2) — the pipeline passes
    str(msg.id), same as worker/extraction/extractor.py's extract().

    `seed` follows the same pattern as worker/extraction/extractor.py's
    extract(): unset for the live pipeline, pinned by eval runs that need
    week-to-week comparability.

    Fails closed: if anything raises — building the client (e.g. a missing
    OPENAI_API_KEY) or the LLM call itself — the result comes back as
    leak_found=True with a single `other`-kind flag and a note explaining
    why. The flag is what matters downstream: worker/pipeline.py only skips
    extraction when masking_sanity_flags is non-empty, so an unexplained
    failure that came back with no flags (as an earlier version of this
    function did) would silently let extraction run over text nobody has
    actually cleared — the exact opposite of failing closed.
    """
    started = time.perf_counter()

    try:
        client = client or LlmClient()
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started) * 1000)
        logger.error(
            f"sanity check failed after {duration_ms}ms (client init), failing closed: {exc}",
            exc_info=True,
        )
        return SanityCheckResult(
            leak_found=True,
            flags=[SanityFlag(kind=SanityFlagKind.OTHER, span=None)],
            notes=f"client init failed: {exc}",
        )

    try:
        result = client.structured(
            tier=tier,
            response_model=SanityCheckResult,
            system_prompt=SANITY_PROMPT,
            user_content=masked_text,
            message_id=message_id,
            seed=seed,
        )
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started) * 1000)
        logger.error(
            f"sanity check failed after {duration_ms}ms (llm call), failing closed: {exc}",
            exc_info=True,
        )
        return SanityCheckResult(
            leak_found=True,
            flags=[SanityFlag(kind=SanityFlagKind.OTHER, span=None)],
            notes=f"llm call failed: {exc}",
        )

    text_len = len(masked_text)
    clamped_flags = [
        SanityFlag(kind=flag.kind, span=_clamp_span(flag.span, text_len)) for flag in result.flags
    ]
    return SanityCheckResult(leak_found=result.leak_found, flags=clamped_flags, notes=result.notes)
