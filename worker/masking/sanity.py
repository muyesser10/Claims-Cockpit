# worker/masking/sanity.py
"""LLM-based sanity pass over already-masked text.

Regex + the name dictionary run first (worker/masking/pipeline.py); this is
the last line of defense for whatever they missed — a rare name, a phone
number in an odd format, an address. Same LLM client and prompt-loading
pattern as worker/extraction/extractor.py (S2-6).
"""

import logging
import os
import time
from pathlib import Path

from pydantic import BaseModel

from worker.llm.client import LlmClient, ModelTier

logger = logging.getLogger("worker.masking.sanity")

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "masking_sanity_v1.txt"

# Read once: the prompt is static and identical for every message.
SANITY_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")

_ENV_FALSE_VALUES = {"false", "0", "no"}


class SanityCheckResult(BaseModel):
    """The model's answer: is there PII left in the masked text."""

    leak_found: bool
    flagged_snippets: list[str] = []
    notes: str | None = None


def is_sanity_enabled() -> bool:
    """Whether the sanity pass should run at all.

    Defaults to on. Set MASKING_SANITY_ENABLED=false to skip it (and its
    OpenAI cost) entirely — independent of DEMO_OFFLINE, which nothing reads
    yet.
    """
    value = os.environ.get("MASKING_SANITY_ENABLED", "true").strip().lower()
    return value not in _ENV_FALSE_VALUES


def check_sanity(
    masked_text: str,
    *,
    message_id: str,
    client: LlmClient | None = None,
    tier: ModelTier = ModelTier.CHEAP,
) -> SanityCheckResult:
    """Ask the model whether `masked_text` still shows any PII.

    `message_id` is not in the original spec's signature but is required by
    LlmClient.structured() (no default) and is how every llm_call log line
    ties back to a raw_message_id (CLAUDE.md §2) — the pipeline passes
    str(msg.id), same as worker/extraction/extractor.py's extract().

    Fails closed: if the LLM call raises for any reason, the result comes
    back as leak_found=True with no snippets and a note explaining why —
    an unexplained failure must route to human review, not silently pass.
    """
    client = client or LlmClient()
    started = time.perf_counter()

    try:
        result = client.structured(
            tier=tier,
            response_model=SanityCheckResult,
            system_prompt=SANITY_PROMPT,
            user_content=masked_text,
            message_id=message_id,
        )
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started) * 1000)
        logger.error(
            f"sanity check failed after {duration_ms}ms, failing closed: {exc}",
            exc_info=True,
        )
        return SanityCheckResult(
            leak_found=True,
            flagged_snippets=[],
            notes=f"sanity check failed: {exc}",
        )

    return result
