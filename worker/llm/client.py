# worker/llm/client.py
"""Single entry point for every LLM call.

DS/LLM design doc §2:
  - provider: OpenAI cloud (see docs/decisions/ADR-001)
  - two tiers: cheap for classification/triage, strong for extraction
  - structured output through instructor + Pydantic, with automatic retry

Nothing else in the codebase talks to OpenAI directly. One place to swap the
model, one place that writes the audit trail (CLAUDE.md §1: input, model,
output and duration are recorded for every pipeline step).
"""

import os
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

import instructor
import structlog
from openai import OpenAI
from pydantic import BaseModel

log = structlog.get_logger(__name__)

# The schema the caller wants filled in, e.g. ClaimExtraction.
ResponseT = TypeVar("ResponseT", bound=BaseModel)

DEFAULT_CHEAP_MODEL = "gpt-4o-mini"
DEFAULT_STRONG_MODEL = "gpt-4o"

# Ceiling for one request. A normal call takes 2-15s, so this is the "something
# hung" threshold. CLAUDE.md §7 wants end-to-end p95 <= 60s and the pipeline
# makes two LLM calls, which is why the ceiling is kept tight.
DEFAULT_TIMEOUT_SECONDS = 30.0

# Two separate retry layers; keep both visible and bounded:
#   SDK         -> network errors, 429 (quota), 5xx
#   instructor  -> the answer did not fit the schema
DEFAULT_SDK_MAX_RETRIES = 1
DEFAULT_MAX_RETRIES = 2


class ModelTier(StrEnum):
    """Which of the two tiers a call belongs to.

    CHEAP   classification, triage, RAG routing
    STRONG  extraction, Text-to-SQL, RAG answers
    """

    CHEAP = "cheap"
    STRONG = "strong"


@dataclass(frozen=True)
class LlmSettings:
    """Everything the client needs, read once from the environment."""

    api_key: str
    cheap_model: str = DEFAULT_CHEAP_MODEL
    strong_model: str = DEFAULT_STRONG_MODEL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    sdk_max_retries: int = DEFAULT_SDK_MAX_RETRIES
    max_retries: int = DEFAULT_MAX_RETRIES

    def model_for(self, tier: ModelTier) -> str:
        """Map a tier to the configured model name."""
        return self.cheap_model if tier is ModelTier.CHEAP else self.strong_model


def load_settings() -> LlmSettings:
    """Build settings from environment variables.

    Raises when the key is missing, so the failure happens at startup with a
    readable message instead of halfway through the first request.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in.")

    return LlmSettings(
        api_key=api_key,
        cheap_model=os.environ.get("LLM_MODEL_CHEAP", DEFAULT_CHEAP_MODEL),
        strong_model=os.environ.get("LLM_MODEL_STRONG", DEFAULT_STRONG_MODEL),
        timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
        sdk_max_retries=int(os.environ.get("LLM_SDK_MAX_RETRIES", DEFAULT_SDK_MAX_RETRIES)),
        max_retries=int(os.environ.get("LLM_MAX_RETRIES", DEFAULT_MAX_RETRIES)),
    )


def _elapsed_ms(started: float) -> int:
    """Milliseconds since `started`, rounded — for the audit trail."""
    return round((time.perf_counter() - started) * 1000)


def _build_client(settings: LlmSettings):
    """Wrap an OpenAI client with instructor so it can return Pydantic models."""
    return instructor.from_openai(
        OpenAI(
            api_key=settings.api_key,
            timeout=settings.timeout_seconds,
            max_retries=settings.sdk_max_retries,
        )
    )


class LlmClient:
    """Asks the model to fill in a Pydantic schema, and records what happened.

    `client` is injectable so tests can pass a stub and never touch the network.
    """

    def __init__(self, settings: LlmSettings | None = None, client=None) -> None:
        self.settings = settings or load_settings()
        self.client = client if client is not None else _build_client(self.settings)

    def structured(
        self,
        *,
        tier: ModelTier,
        response_model: type[ResponseT],
        system_prompt: str,
        user_content: str,
        message_id: str,
        temperature: float = 0.0,
        seed: int | None = None,
    ) -> ResponseT:
        """Return `response_model`, filled in by the model.

        instructor validates the answer against the schema and re-asks on a
        validation error, up to `settings.max_retries` times. A field the model
        gets wrong therefore costs an extra call, not a crash.

        temperature defaults to 0: extraction has to be reproducible, and eval
        runs from different weeks have to be comparable.

        A seed tightens reproducibility one notch further; eval runs pin it,
        the normal pipeline does not need it. It is not a guarantee, which is
        why system_fingerprint is logged too: when OpenAI changes the backend,
        that is where a metric shift becomes explainable.
        """
        model = self.settings.model_for(tier)
        started = time.perf_counter()

        request = {
            "model": model,
            "response_model": response_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
            "max_retries": self.settings.max_retries,
        }
        # Only send a seed when one was actually given; passing None would put
        # a pointless field on the request.
        if seed is not None:
            request["seed"] = seed

        try:
            result, completion = self.client.chat.completions.create_with_completion(**request)
        except Exception as exc:
            # Never swallow it. The pipeline will send the message to the dead
            # letter queue (CLAUDE.md §4), but the reason has to be on record.
            log.error(
                "llm_call_failed",
                message_id=message_id,
                model=model,
                tier=str(tier),
                response_model=response_model.__name__,
                duration_ms=_elapsed_ms(started),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise

        usage = getattr(completion, "usage", None)
        log.info(
            "llm_call",
            message_id=message_id,
            model=model,
            tier=str(tier),
            response_model=response_model.__name__,
            duration_ms=_elapsed_ms(started),
            prompt_chars=len(system_prompt) + len(user_content),
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            seed=seed,
            system_fingerprint=getattr(completion, "system_fingerprint", None),
        )
        return result
