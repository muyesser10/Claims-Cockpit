# worker/classification/test_classifier.py
"""Classifier tests.

Nothing here touches the network. LlmClient takes an injectable client and every
test passes a stub, so these run in CI with no API key and cost nothing - the
same arrangement as worker/llm/test_client.py.
"""

import pytest

from worker.classification.classifier import (
    INJURY_OVERRIDE,
    LLM_URGENCY,
    build_user_content,
    classify,
    find_injury_signals,
)
from worker.classification.schema import ClaimClassification, ContentType, Urgency
from worker.llm.client import LlmClient, LlmSettings, ModelTier


class _StubCompletion:
    def __init__(self):
        self.usage = None
        self.system_fingerprint = "fp_test"


class _StubCompletions:
    """Hands back a canned answer and records the request."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def create_with_completion(self, **kwargs):
        self.calls.append(kwargs)
        return self.answer, _StubCompletion()


class _StubChat:
    def __init__(self, completions):
        self.completions = completions


class _StubClient:
    """Shaped like the instructor-patched OpenAI client, but inert."""

    def __init__(self, completions):
        self.chat = _StubChat(completions)


def make_client(answer):
    completions = _StubCompletions(answer)
    client = LlmClient(settings=LlmSettings(api_key="test-key"), client=_StubClient(completions))
    return client, completions


def answer(content_type="claim", urgency="normal", injury=False):
    return ClaimClassification(
        reasoning="test",
        content_type=content_type,
        urgency=urgency,
        injury_mentioned=injury,
    )


# --- the injury override -------------------------------------------------


def test_a_term_in_the_text_overrides_the_model():
    """The rule design doc §4 exists for: the model said normal, the text says injury."""
    client, _ = make_client(answer(urgency="normal"))
    result = classify("Kaza oldu, ambulans geldi", "email", message_id="m1", client=client)

    assert result.urgency is Urgency.CRITICAL
    assert result.urgency_source == INJURY_OVERRIDE
    assert result.llm_urgency is Urgency.NORMAL
    assert "ambulans" in result.injury_signals


def test_the_models_own_flag_also_overrides():
    """The second path: no term matched, but the model saw an injury anyway."""
    client, _ = make_client(answer(urgency="high", injury=True))
    result = classify("eşim fena çarptı kafasını", "email", message_id="m2", client=client)

    assert result.urgency is Urgency.CRITICAL
    assert result.urgency_source == INJURY_OVERRIDE
    assert result.injury_signals == []


def test_an_agreeing_model_is_not_recorded_as_an_override():
    """Attribution matters: this case is the model's, and the metric has to say so."""
    client, _ = make_client(answer(urgency="critical", injury=True))
    result = classify("yaralı var", "email", message_id="m3", client=client)

    assert result.urgency is Urgency.CRITICAL
    assert result.urgency_source == LLM_URGENCY


def test_no_injury_leaves_the_models_answer_alone():
    client, _ = make_client(answer(urgency="high"))
    result = classify("araç çalışmıyor, yolda kaldım", "email", message_id="m4", client=client)

    assert result.urgency is Urgency.HIGH
    assert result.urgency_source == LLM_URGENCY
    assert result.llm_urgency is Urgency.HIGH


def test_turkish_uppercase_still_matches():
    """'YARALI'.lower() loses the dotted i; worker/shared handles it, so must we."""
    client, _ = make_client(answer(urgency="normal"))
    result = classify("ARAÇTA YARALI VAR", "email", message_id="m5", client=client)

    assert result.urgency is Urgency.CRITICAL


def test_find_injury_signals_reports_every_match():
    signals = find_injury_signals("yaralı vardı, ambulans ve hastane")
    assert {"yaralı", "ambulans", "hastane"} <= set(signals)


def test_find_injury_signals_is_empty_on_clean_text():
    assert find_injury_signals("aracımın camı çatladı") == []


# --- the early exit ------------------------------------------------------


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [("claim", True), ("info_request", False), ("irrelevant", False)],
)
def test_only_claims_go_on_to_extraction(content_type, expected):
    """Design doc §4: an info_request or irrelevant verdict stops the pipeline."""
    client, _ = make_client(answer(content_type=content_type))
    result = classify("herhangi bir metin", "email", message_id="m6", client=client)

    assert result.should_extract is expected


def test_an_injury_in_a_question_still_reaches_critical():
    """Rule 4's exception: a question can be critical if someone is hurt."""
    client, _ = make_client(answer(content_type="info_request", urgency="normal"))
    result = classify(
        "Eşim hastanede, poliçe bunu karşılıyor mu?", "email", message_id="m7", client=client
    )

    assert result.content_type is ContentType.INFO_REQUEST
    assert result.urgency is Urgency.CRITICAL


# --- request shape -------------------------------------------------------


def test_the_cheap_tier_is_the_default():
    """ADR-001: the whole project runs on gpt-4o-mini."""
    client, completions = make_client(answer())
    classify("metin", "email", message_id="m8", client=client)

    assert completions.calls[0]["model"] == client.settings.model_for(ModelTier.CHEAP)


def test_the_versioned_prompt_is_sent():
    client, completions = make_client(answer())
    classify("metin", "email", message_id="m9", client=client)

    system_prompt = completions.calls[0]["messages"][0]["content"]
    assert "İÇERİK TİPİ" in system_prompt


def test_user_content_carries_the_channel():
    content = build_user_content("aracım çizildi", "web_form")
    assert "Kanal: web_form" in content
    assert "aracım çizildi" in content
