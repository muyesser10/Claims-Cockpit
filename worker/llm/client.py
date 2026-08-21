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

import json
import os
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

import instructor
import structlog
from openai import OpenAI
from pydantic import BaseModel

from worker.metrics import llm_calls_total, llm_tokens_total

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


# --- Offline demo (S4-6) ----------------------------------------------------
#
# DEMO_OFFLINE swaps the bottom layer of this module - the OpenAI call itself -
# for answers recorded under demo/fixtures/. Everything above it stays real:
# instructor still validates the schema, structured() still times the call and
# still writes the llm_call audit line. A demo with no network therefore
# exercises the same code path as a live one.

_ENV_TRUE_VALUES = frozenset({"true", "1", "yes"})

# One JSONL per response model. Deliberately not eval/fixtures/, which is
# measurement input - see demo/fixtures/README.md.
FIXTURE_DIR = Path(__file__).resolve().parents[2] / "demo" / "fixtures"
FIXTURE_GLOB = "demo_*.jsonl"

# The record that answers for any message with no recorded one of its own.
WILDCARD_GT_ID = "*"

# What offline reports as its model. Deliberately not gpt-4o-mini/gpt-4o: this
# string reaches ExtractionResult.model and from there audit_trail, and a
# recorded answer must never read back as a live model call.
OFFLINE_API_KEY = "offline"
OFFLINE_CHEAP_MODEL = "offline-fixture-cheap"
OFFLINE_STRONG_MODEL = "offline-fixture-strong"

# response model name -> gt_id -> payload
FixtureIndex = dict[str, dict[str, dict]]

_fixture_cache: dict[Path, FixtureIndex] = {}


class FixtureLoadError(RuntimeError):
    """The fixture set is missing, malformed or incomplete.

    Raised while loading rather than while answering: a broken fixture set is
    the problem of whoever prepares the demo, and it has to surface then - not
    halfway through a pipeline run in front of an audience.
    """


def is_demo_offline() -> bool:
    """Whether the offline demo mode is on. DEMO_OFFLINE, default off."""
    return os.environ.get("DEMO_OFFLINE", "false").strip().lower() in _ENV_TRUE_VALUES


def _read_fixture_file(path: Path, index: FixtureIndex) -> None:
    """Fold one JSONL file into `index`, naming file and line on any problem."""
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path.name}:{number}"

        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FixtureLoadError(f"{where}: not valid JSON ({exc})") from exc

        if not isinstance(record, dict):
            raise FixtureLoadError(f"{where}: expected a JSON object, got {type(record).__name__}")

        missing = [key for key in ("gt_id", "response_model", "payload") if key not in record]
        if missing:
            raise FixtureLoadError(f"{where}: missing required key(s): {', '.join(missing)}")

        payload = record["payload"]
        if not isinstance(payload, dict):
            raise FixtureLoadError(f"{where}: 'payload' must be an object")

        by_gt_id = index.setdefault(str(record["response_model"]), {})
        gt_id = str(record["gt_id"])
        if gt_id in by_gt_id:
            raise FixtureLoadError(
                f"{where}: duplicate record for {record['response_model']} / {gt_id}"
            )
        by_gt_id[gt_id] = payload


def _load_fixtures(directory: Path) -> FixtureIndex:
    """Read every demo_*.jsonl in `directory` and check the set is usable."""
    if not directory.is_dir():
        raise FixtureLoadError(
            f"offline fixture directory not found: {directory}. "
            "Run demo/fixtures/build_extraction_fixtures.py and build_sanity_fixtures.py."
        )

    files = sorted(directory.glob(FIXTURE_GLOB))
    if not files:
        raise FixtureLoadError(f"no {FIXTURE_GLOB} files in {directory}; nothing to answer with.")

    index: FixtureIndex = {}
    for path in files:
        _read_fixture_file(path, index)

    # Every model needs a wildcard, which is what makes a lookup miss safe: a
    # question typed live at the demo has no gt_id, and falling back must never
    # be the thing that raises.
    without_wildcard = sorted(
        name for name, by_gt_id in index.items() if WILDCARD_GT_ID not in by_gt_id
    )
    if without_wildcard:
        raise FixtureLoadError(
            f"every response model needs a '{WILDCARD_GT_ID}' record; missing for: "
            f"{', '.join(without_wildcard)}"
        )

    return index


def load_fixtures(directory: Path | None = None) -> FixtureIndex:
    """Return the fixture index, reading it from disk on first use.

    Lazy on purpose: importing this module must not depend on the fixture set
    existing, or every test and every online run would pay for a demo feature.
    """
    directory = (directory or FIXTURE_DIR).resolve()
    cached = _fixture_cache.get(directory)
    if cached is None:
        cached = _load_fixtures(directory)
        _fixture_cache[directory] = cached
    return cached


class _FixtureChat:
    """Mirrors `openai_client.chat`, so LlmClient's call path is untouched."""

    def __init__(self, completions: "FixtureCompletions") -> None:
        self.completions = completions


class FixtureCompletions:
    """Answers from recorded fixtures instead of OpenAI.

    Injected as `LlmClient(client=...)`, which is the same seam the tests use.
    Matched on `external_ref` - the gt_id replay writes onto every message
    (replay/replay.py) - and falling back to the wildcard for anything else.
    """

    def __init__(self, external_ref: str | None = None, *, directory: Path | None = None) -> None:
        self.external_ref = external_ref
        self.directory = directory

    @property
    def chat(self) -> _FixtureChat:
        return _FixtureChat(self)

    def create_with_completion(self, **request):
        """Return (parsed_model, completion) the way instructor would.

        A missing gt_id is normal and falls back silently. A response model with
        no fixtures at all is not: nothing can answer for it, so it raises with
        the model's name rather than inventing something.
        """
        response_model = request["response_model"]
        name = response_model.__name__

        by_gt_id = load_fixtures(self.directory).get(name)
        if by_gt_id is None:
            raise FixtureLoadError(
                f"no offline fixtures recorded for {name}; "
                f"add records for it under {self.directory or FIXTURE_DIR}"
            )

        payload = by_gt_id.get(self.external_ref or WILDCARD_GT_ID, by_gt_id[WILDCARD_GT_ID])

        # completion=None deliberately: structured() reads usage and
        # system_fingerprint with getattr(..., None), and inventing token counts
        # for an answer that cost nothing would put fiction in the audit trail.
        return response_model(**payload), None


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
            # Counted before the raise, or a provider outage would look like a
            # drop in traffic rather than a wall of failures.
            llm_calls_total.labels(model=model, tier=str(tier), outcome="error").inc()
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
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)

        llm_calls_total.labels(model=model, tier=str(tier), outcome="ok").inc()
        # None is a normal answer here, not a zero: DEMO_OFFLINE hands back
        # completion=None because a recorded answer cost nothing, and a provider
        # can omit usage. Counting those as 0 would report free calls the same
        # way as calls whose cost we simply do not know.
        if prompt_tokens is not None:
            llm_tokens_total.labels(model=model, tier=str(tier), kind="prompt").inc(prompt_tokens)
        if completion_tokens is not None:
            llm_tokens_total.labels(model=model, tier=str(tier), kind="completion").inc(
                completion_tokens
            )

        log.info(
            "llm_call",
            message_id=message_id,
            model=model,
            tier=str(tier),
            response_model=response_model.__name__,
            duration_ms=_elapsed_ms(started),
            prompt_chars=len(system_prompt) + len(user_content),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            seed=seed,
            system_fingerprint=getattr(completion, "system_fingerprint", None),
        )
        return result


def get_llm_client(external_ref: str | None = None) -> LlmClient:
    """The client every caller should build.

    Online this is exactly `LlmClient()`. Offline (DEMO_OFFLINE) it is the same
    LlmClient with its bottom layer swapped for recorded answers, matched on
    `external_ref` and falling back to the wildcard record.

    A factory rather than a branch inside `LlmClient.__init__`, deliberately:
    eval builds `LlmClient()` directly, and a constructor that could quietly
    hand back fixtures would let a scoring run grade the answers it was handed.
    Anything that must never see a fixture keeps calling the constructor.
    """
    if not is_demo_offline():
        return LlmClient()

    settings = LlmSettings(
        api_key=OFFLINE_API_KEY,
        cheap_model=OFFLINE_CHEAP_MODEL,
        strong_model=OFFLINE_STRONG_MODEL,
    )
    return LlmClient(settings=settings, client=FixtureCompletions(external_ref))
