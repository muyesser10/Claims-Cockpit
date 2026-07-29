# worker/llm/test_client.py
"""Tests for the LLM client.

Nothing here touches the network. LlmClient takes an injectable client and
every test passes a stub, so these run in CI with no API key and cost nothing.
"""

import pytest
from pydantic import BaseModel

from worker.llm.client import (
    DEFAULT_CHEAP_MODEL,
    DEFAULT_STRONG_MODEL,
    LlmClient,
    LlmSettings,
    ModelTier,
    load_settings,
)


class Answer(BaseModel):
    """A throwaway response model, standing in for ClaimExtraction."""

    value: str


class _StubCompletion:
    """The raw completion object, carrying only the fields we log."""

    def __init__(self, usage=None, system_fingerprint=None):
        self.usage = usage
        self.system_fingerprint = system_fingerprint


class _StubCompletions:
    """Records the request and hands back a canned answer."""

    def __init__(self, answer=None, usage=None, error=None):
        self.answer = answer
        self.usage = usage
        self.error = error
        self.calls = []

    def create_with_completion(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.answer, _StubCompletion(self.usage, system_fingerprint="fp_test")


class _StubChat:
    def __init__(self, completions):
        self.completions = completions


class _StubClient:
    """Shaped like the instructor-patched OpenAI client, but inert."""

    def __init__(self, completions):
        self.chat = _StubChat(completions)


def _settings(**overrides) -> LlmSettings:
    """Settings with a fake key, so no test needs a real one."""
    return LlmSettings(api_key="sk-test", **overrides)


def _client_with(completions, **setting_overrides) -> LlmClient:
    """Build an LlmClient wired to a stub instead of the network."""
    return LlmClient(settings=_settings(**setting_overrides), client=_StubClient(completions))


def test_missing_api_key_fails_loudly(monkeypatch):
    """A missing key must fail at startup, not inside the first request."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        load_settings()


def test_settings_read_from_environment(monkeypatch):
    """Models, limits and both retry layers are configurable without code changes."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL_CHEAP", "cheap-model")
    monkeypatch.setenv("LLM_MODEL_STRONG", "strong-model")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("LLM_SDK_MAX_RETRIES", "3")
    monkeypatch.setenv("LLM_MAX_RETRIES", "5")

    settings = load_settings()

    assert settings.cheap_model == "cheap-model"
    assert settings.strong_model == "strong-model"
    assert settings.timeout_seconds == 12.5
    assert settings.sdk_max_retries == 3
    assert settings.max_retries == 5


def test_settings_fall_back_to_defaults(monkeypatch):
    """Only the key is mandatory; everything else has a sane default."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    for name in (
        "LLM_MODEL_CHEAP",
        "LLM_MODEL_STRONG",
        "LLM_TIMEOUT_SECONDS",
        "LLM_SDK_MAX_RETRIES",
        "LLM_MAX_RETRIES",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings()

    assert settings.cheap_model == DEFAULT_CHEAP_MODEL
    assert settings.strong_model == DEFAULT_STRONG_MODEL
    assert settings.timeout_seconds == 30.0
    assert settings.sdk_max_retries == 1
    assert settings.max_retries == 2


def test_tiers_do_not_collapse_into_one_model():
    """Cheap and strong must stay distinct, or the cost split is a lie."""
    settings = _settings(cheap_model="small", strong_model="big")
    assert settings.model_for(ModelTier.CHEAP) == "small"
    assert settings.model_for(ModelTier.STRONG) == "big"


def test_structured_returns_the_parsed_model():
    """The caller gets a Pydantic object back, not raw JSON."""
    completions = _StubCompletions(answer=Answer(value="ok"))
    client = _client_with(completions)

    result = client.structured(
        tier=ModelTier.STRONG,
        response_model=Answer,
        system_prompt="sys",
        user_content="user",
        message_id="GT-000002",
    )

    assert result.value == "ok"


def test_structured_sends_the_expected_request():
    """Model, schema, both messages and the retry budget all reach the API."""
    completions = _StubCompletions(answer=Answer(value="ok"))
    client = _client_with(completions, cheap_model="small", strong_model="big", max_retries=3)

    client.structured(
        tier=ModelTier.CHEAP,
        response_model=Answer,
        system_prompt="sys",
        user_content="user",
        message_id="GT-000002",
    )

    sent = completions.calls[0]
    assert sent["model"] == "small"
    assert sent["response_model"] is Answer
    assert sent["max_retries"] == 3
    assert sent["messages"][0] == {"role": "system", "content": "sys"}
    assert sent["messages"][1] == {"role": "user", "content": "user"}


def test_temperature_defaults_to_zero():
    """Extraction has to be reproducible and eval runs comparable."""
    completions = _StubCompletions(answer=Answer(value="ok"))
    client = _client_with(completions)

    client.structured(
        tier=ModelTier.STRONG,
        response_model=Answer,
        system_prompt="sys",
        user_content="user",
        message_id="GT-000002",
    )

    assert completions.calls[0]["temperature"] == 0.0


def test_seed_is_omitted_when_not_given():
    """With no seed the field must be absent; sending None would be wrong."""
    completions = _StubCompletions(answer=Answer(value="ok"))
    client = _client_with(completions)

    client.structured(
        tier=ModelTier.STRONG,
        response_model=Answer,
        system_prompt="sys",
        user_content="user",
        message_id="GT-000002",
    )

    assert "seed" not in completions.calls[0]


def test_seed_is_forwarded_when_given():
    """When an eval run pins a seed, it has to reach the API."""
    completions = _StubCompletions(answer=Answer(value="ok"))
    client = _client_with(completions)

    client.structured(
        tier=ModelTier.STRONG,
        response_model=Answer,
        system_prompt="sys",
        user_content="user",
        message_id="GT-000002",
        seed=42,
    )

    assert completions.calls[0]["seed"] == 42


def test_failures_are_raised_not_swallowed():
    """CLAUDE.md §4: a broken step goes to the dead letter queue, loudly."""
    completions = _StubCompletions(error=TimeoutError("upstream timed out"))
    client = _client_with(completions)

    with pytest.raises(TimeoutError):
        client.structured(
            tier=ModelTier.STRONG,
            response_model=Answer,
            system_prompt="sys",
            user_content="user",
            message_id="GT-000002",
        )
