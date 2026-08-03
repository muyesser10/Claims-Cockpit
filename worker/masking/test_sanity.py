# worker/masking/test_sanity.py
"""Tests for the masking sanity pass. Nothing here touches the network."""

from worker.llm.client import LlmSettings
from worker.masking.sanity import SanityCheckResult, check_sanity, is_sanity_enabled


class StubClient:
    """Stands in for LlmClient: returns a fixed answer, records the call."""

    def __init__(self, answer: SanityCheckResult) -> None:
        self.answer = answer
        self.settings = LlmSettings(api_key="not-used")
        self.calls: list[dict] = []

    def structured(self, **kwargs):
        self.calls.append(kwargs)
        return self.answer


class RaisingClient:
    """Stands in for LlmClient: always raises, like a network/API failure."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.settings = LlmSettings(api_key="not-used")

    def structured(self, **kwargs):
        raise self.exc


# --- is_sanity_enabled() ------------------------------------------------------


def test_enabled_by_default(monkeypatch):
    monkeypatch.delenv("MASKING_SANITY_ENABLED", raising=False)
    assert is_sanity_enabled() is True


def test_disabled_when_false(monkeypatch):
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "false")
    assert is_sanity_enabled() is False


def test_disabled_when_zero(monkeypatch):
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "0")
    assert is_sanity_enabled() is False


def test_disabled_when_no_case_insensitive(monkeypatch):
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "NO")
    assert is_sanity_enabled() is False


def test_enabled_for_other_values(monkeypatch):
    monkeypatch.setenv("MASKING_SANITY_ENABLED", "true")
    assert is_sanity_enabled() is True


# --- check_sanity() ------------------------------------------------------------


def test_check_sanity_clean_result():
    client = StubClient(SanityCheckResult(leak_found=False))
    result = check_sanity("Merhaba [NAME_1] aradı", message_id="1", client=client)
    assert result.leak_found is False
    assert result.flagged_snippets == []


def test_check_sanity_leak_found():
    client = StubClient(
        SanityCheckResult(leak_found=True, flagged_snippets=["Zülfikar Bey"], notes="isim kaçmış")
    )
    result = check_sanity("...", message_id="1", client=client)
    assert result.leak_found is True
    assert result.flagged_snippets == ["Zülfikar Bey"]


def test_check_sanity_passes_masked_text_and_message_id():
    client = StubClient(SanityCheckResult(leak_found=False))
    check_sanity("maskelenmis metin", message_id="42", client=client)
    assert client.calls[0]["user_content"] == "maskelenmis metin"
    assert client.calls[0]["message_id"] == "42"


def test_check_sanity_fails_closed_on_exception():
    """An LLM call that raises must not silently pass — it comes back as a leak."""
    client = RaisingClient(RuntimeError("boom"))
    result = check_sanity("...", message_id="1", client=client)
    assert result.leak_found is True
    assert result.flagged_snippets == []
    assert "boom" in result.notes
