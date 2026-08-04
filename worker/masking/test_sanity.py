# worker/masking/test_sanity.py
"""Tests for the masking sanity pass. Nothing here touches the network."""

import worker.masking.sanity as sanity_module
from worker.llm.client import LlmSettings
from worker.masking.sanity import (
    SanityCheckResult,
    SanityFlag,
    SanityFlagKind,
    check_sanity,
    is_sanity_enabled,
)


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


class RaisingLlmClientClass:
    """Stands in for the LlmClient *class*: raises on construction, like
    load_settings() does when OPENAI_API_KEY is unset."""

    def __init__(self, *args, **kwargs) -> None:
        raise RuntimeError("OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in.")


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
    assert result.flags == []


def test_check_sanity_leak_found():
    client = StubClient(
        SanityCheckResult(
            leak_found=True,
            flags=[SanityFlag(kind="name", span=(0, 5))],
            notes="isim kaçmış",
        )
    )
    result = check_sanity("kisa metin burada", message_id="1", client=client)
    assert result.leak_found is True
    assert result.flags == [SanityFlag(kind="name", span=(0, 5))]


def test_check_sanity_passes_masked_text_and_message_id():
    client = StubClient(SanityCheckResult(leak_found=False))
    check_sanity("maskelenmis metin", message_id="42", client=client)
    assert client.calls[0]["user_content"] == "maskelenmis metin"
    assert client.calls[0]["message_id"] == "42"


def test_check_sanity_passes_seed_through():
    """seed follows the same optional-pass-through pattern as extract()."""
    client = StubClient(SanityCheckResult(leak_found=False))
    check_sanity("maskelenmis metin", message_id="42", client=client, seed=7)
    assert client.calls[0]["seed"] == 7


def test_check_sanity_fails_closed_on_exception():
    """An LLM call that raises must not silently pass — it comes back as a leak,
    and (critically) with a flag, not an empty list: worker/pipeline.py only
    skips extraction when masking_sanity_flags is non-empty, so an empty
    flags list on a failure would let extraction run over unchecked text."""
    client = RaisingClient(RuntimeError("boom"))
    result = check_sanity("...", message_id="1", client=client)
    assert result.leak_found is True
    assert result.flags == [SanityFlag(kind=SanityFlagKind.OTHER, span=None)]
    assert "boom" in result.notes


def test_check_sanity_fail_closed_flags_are_never_empty():
    """Whatever raises, fail-closed must hand back at least one flag with a
    kind — an empty list is indistinguishable from 'nothing found' downstream."""
    client = RaisingClient(ValueError("schema mismatch"))
    result = check_sanity("bir metin", message_id="1", client=client)
    assert len(result.flags) >= 1
    assert all(flag.kind is not None for flag in result.flags)


def test_check_sanity_fails_closed_when_client_construction_raises(monkeypatch):
    """LlmClient() itself can raise (e.g. OPENAI_API_KEY missing) before any
    LLM call happens. That must be caught too, not escape check_sanity() and
    crash the whole pipeline step (which used to send the message straight
    to dead_letter instead of routing it to human review)."""
    monkeypatch.setattr(sanity_module, "LlmClient", RaisingLlmClientClass)

    result = check_sanity("...", message_id="1", client=None)

    assert result.leak_found is True
    assert result.flags == [SanityFlag(kind=SanityFlagKind.OTHER, span=None)]
    assert "OPENAI_API_KEY" in result.notes


def test_check_sanity_drops_out_of_bounds_span():
    """A span the model invented outside the text is dropped, kind is kept —
    never trust an offset without checking it against the real text length."""
    client = StubClient(
        SanityCheckResult(leak_found=True, flags=[SanityFlag(kind="phone", span=(999, 1010))])
    )
    result = check_sanity("kisa metin", message_id="1", client=client)
    assert result.flags == [SanityFlag(kind="phone", span=None)]


def test_check_sanity_keeps_in_bounds_span():
    client = StubClient(
        SanityCheckResult(leak_found=True, flags=[SanityFlag(kind="tc", span=(2, 5))])
    )
    result = check_sanity("kisa metin", message_id="1", client=client)
    assert result.flags == [SanityFlag(kind="tc", span=(2, 5))]


def test_flagged_pii_text_never_appears_in_result():
    """The whole point of this rewrite: no field on SanityCheckResult can hold
    the leaked text itself, only its kind and a numeric span."""
    leaked_name = "Zülfikar Bey"
    client = StubClient(
        SanityCheckResult(
            leak_found=True,
            flags=[SanityFlag(kind="name", span=(70, 82))],
            notes="isim sözlüğünde olmayan bir isim maskelenmemiş görünüyor",
        )
    )
    result = check_sanity(
        f"...Karşı taraftaki sürücü {leaked_name}'di...", message_id="1", client=client
    )
    dumped = result.model_dump_json()
    assert leaked_name not in dumped
