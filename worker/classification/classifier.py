# worker/classification/classifier.py
"""Classification step: prompt + LLM client + the deterministic injury override.

Knows nothing about the database. `worker/pipeline.py` calls `classify()` and
owns persistence, the audit trail and error handling - the same boundary
extraction has.

Design doc §4 puts a deterministic rule over whatever urgency the model proposes.
That rule lives here rather than in the pipeline for one reason: eval calls this
module, and an override that sat in the pipeline would leave eval measuring a
system nobody runs. Critical recall is the metric the override exists for
(CLAUDE.md §7, >= 97%), so it has to be inside what gets measured.
"""

import time
from pathlib import Path

from pydantic import BaseModel

from worker.classification.schema import ClaimClassification, ContentType, Urgency
from worker.llm.client import LlmClient, ModelTier
from worker.shared.injury_terms import find_injury_signals

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "classification_v1.txt"

# Read once: the prompt is static and identical for every message.
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")

LLM_URGENCY = "llm"
INJURY_OVERRIDE = "injury_override"


class ClassificationResult(BaseModel):
    """What the pipeline persists, plus what the audit trail needs.

    `llm_urgency` sits next to `urgency` on purpose. When the override fires, the
    model's own answer is the only evidence of whether it would have missed the
    case; dropping it makes the override's value impossible to measure, and the
    split between "the model caught it" and "the rule caught it" is exactly what
    a critical-recall number has to be able to explain.
    """

    content_type: ContentType
    urgency: Urgency
    llm_urgency: Urgency
    urgency_source: str
    injury_signals: list[str]
    reasoning: str
    model: str
    duration_ms: int

    @property
    def should_extract(self) -> bool:
        """Design doc §4's early exit: only claims go on to extraction."""
        return self.content_type is ContentType.CLAIM


def build_user_content(text: str, channel: str) -> str:
    """The message half of the request. Mirrors the examples inside the prompt."""
    return f"Kanal: {channel}\n\n--- MESAJ ---\n{text}"


def classify(
    text: str,
    channel: str,
    *,
    message_id: str,
    client: LlmClient | None = None,
    seed: int | None = None,
    tier: ModelTier = ModelTier.CHEAP,
    system_prompt: str | None = None,
) -> ClassificationResult:
    """Classify one message, then let the deterministic rule have the last word.

    `text` is the masked text: the pipeline masks before it classifies, and the
    prompt tells the model to ignore the placeholders.

    `seed` is for eval runs, where week-to-week comparability matters more than
    anything else; the live pipeline leaves it unset.

    `system_prompt` defaults to the versioned file. Overriding it lets eval
    compare prompt variants on one sample; the pipeline never passes it.
    """
    client = client or LlmClient()
    started = time.perf_counter()

    answer = client.structured(
        tier=tier,
        response_model=ClaimClassification,
        system_prompt=system_prompt or SYSTEM_PROMPT,
        user_content=build_user_content(text, channel),
        message_id=message_id,
        seed=seed,
    )
    duration_ms = round((time.perf_counter() - started) * 1000)

    signals = find_injury_signals(text)
    urgency = answer.urgency
    source = LLM_URGENCY

    # Design doc §4: the deterministic rule overrides whatever the model said.
    # Two independent paths reach it - a term matched in the text, or the model's
    # own flag - because a missed injury is the one error this system must not
    # make. Either path alone is enough; neither is trusted to be complete.
    if (signals or answer.injury_mentioned) and urgency is not Urgency.CRITICAL:
        urgency = Urgency.CRITICAL
        source = INJURY_OVERRIDE

    return ClassificationResult(
        content_type=answer.content_type,
        urgency=urgency,
        llm_urgency=answer.urgency,
        urgency_source=source,
        injury_signals=signals,
        reasoning=answer.reasoning,
        model=client.settings.model_for(tier),
        duration_ms=duration_ms,
    )
