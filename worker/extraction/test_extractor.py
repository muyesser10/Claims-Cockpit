# worker/extraction/test_extractor.py
"""Tests for the extraction step. Nothing here touches the network."""

from datetime import datetime

import worker.extraction.extractor as extractor_module
from worker.extraction.extractor import (
    SYSTEM_PROMPT,
    ExtractionResult,
    build_user_content,
    extract,
    locate_quote,
)
from worker.extraction.schema import ClaimExtraction
from worker.llm.client import LlmSettings, ModelTier

TEXT = (
    "Merhaba, aracımı bildirmek istiyorum.\n\n"
    "11 Temmuz 45 GAK 2046 plakalı aracımla Bursa'da bir ineğe çarptım."
)


class StubClient:
    """Stands in for LlmClient: returns a fixed answer, records the call."""

    def __init__(self, answer: ClaimExtraction) -> None:
        self.answer = answer
        self.settings = LlmSettings(api_key="not-used")
        self.calls: list[dict] = []

    def structured(self, **kwargs):
        self.calls.append(kwargs)
        return self.answer


def run(answer: ClaimExtraction, text: str = TEXT) -> ExtractionResult:
    return extract(
        text,
        datetime(2026, 7, 25, 14, 0),
        "email",
        message_id="GT-TEST",
        client=StubClient(answer),
    )


def test_prompt_file_is_loaded():
    """The prompt ships with the repo; an empty one would fail silently."""
    assert "# ROL" in SYSTEM_PROMPT
    assert "incident_location.city" in SYSTEM_PROMPT


def test_user_content_carries_date_channel_and_text():
    content = build_user_content("gövde", datetime(2026, 7, 25, 14, 0), "email")
    assert "2026-07-25T14:00:00" in content
    assert "Kanal: email" in content
    assert "gövde" in content


def test_quote_span_is_resolved():
    result = run(
        ClaimExtraction(
            reasoning="x",
            plate="45 GAK 2046",
            source_references={"plate": "45 GAK 2046 plakalı"},
        )
    )
    reference = result.extraction["source_references"]["plate"]
    assert TEXT[reference["start"] : reference["end"]] == "45 GAK 2046 plakalı"
    assert result.unverified_fields == []


def test_reflowed_quote_still_matches():
    """A model that turns a line break into a space keeps its evidence."""
    span = locate_quote("bildirmek istiyorum. 11 Temmuz", TEXT)
    assert span is not None
    assert TEXT[span[0] : span[1]].split() == ["bildirmek", "istiyorum.", "11", "Temmuz"]


def test_a_lowercased_quote_still_matches_and_keeps_its_offsets():
    """Models lowercase the first letter when they quote mid-sentence.

    Nothing is invented there, so the span still has to come back - and it has
    to index the original text, not a folded copy.
    """
    original = TEXT[TEXT.index("45 GAK") : TEXT.index("45 GAK") + 19]
    span = locate_quote(original.lower(), TEXT)

    assert span is not None
    assert TEXT[span[0] : span[1]] == original


def test_turkish_dotted_i_folds_the_turkish_way():
    """ "IZMIR".lower() is "izmir" in ASCII and "ızmır" in Turkish; only one of
    those matches the text."""
    text = "Olay İZMİR Bornova'da oldu."

    span = locate_quote("izmir bornova'da", text)

    assert span is not None
    assert text[span[0] : span[1]] == "İZMİR Bornova'da"


def test_a_quote_that_is_still_absent_is_still_unsupported():
    """Case tolerance forgives spelling, not invention."""
    assert locate_quote("bambaşka bir cümle", TEXT) is None


def test_invented_quote_demotes_the_field():
    """The hallucination defence: evidence that is not in the text is not evidence."""
    result = run(
        ClaimExtraction(
            reasoning="x",
            policy_no="POL-2020-57052",
            source_references={"policy_no": "Poliçe numaram POL-2020-57052"},
        )
    )
    reference = result.extraction["source_references"]["policy_no"]
    assert reference["start"] is None
    assert result.unverified_fields == ["policy_no"]
    assert "policy_no" in result.extraction["low_confidence_fields"]


def test_value_without_any_quote_is_flagged():
    """Silence is not evidence either."""
    result = run(ClaimExtraction(reasoning="x", estimated_amount=83397))
    assert result.unverified_fields == ["estimated_amount"]


def test_nested_field_is_reported_in_dotted_form():
    """A value that is nowhere in the text stays flagged, dotted name and all."""
    result = run(ClaimExtraction(reasoning="x", incident_location={"city": "Ankara"}))
    assert result.unverified_fields == ["incident_location.city"]


def test_value_present_in_the_text_is_its_own_evidence():
    """The model folds two fields into one quote; the second is still supported.

    Measured 2026-08-01: with "İzmir Buca'da" in the text, the quote lands under
    incident_location.city and district gets none — 21 of 39 flags came from
    that. The district name is right there in the source, so it counts.
    """
    result = run(ClaimExtraction(reasoning="x", incident_location={"city": "Bursa"}))
    reference = result.extraction["source_references"]["incident_location.city"]
    assert TEXT[reference["start"] : reference["end"]] == "Bursa"
    assert result.unverified_fields == []


def test_reasoning_stays_out_of_the_record():
    """It belongs in the audit trail, not on the operator's screen."""
    result = run(ClaimExtraction(reasoning="kısa muhakeme"))
    assert result.reasoning == "kısa muhakeme"
    assert "reasoning" not in result.extraction


def test_cheap_tier_is_the_default():
    """Measured 2026-08-02: gpt-4o-mini scored 99.4% over 100 records."""
    client = StubClient(ClaimExtraction(reasoning="x"))
    result = extract(TEXT, datetime(2026, 7, 25), "email", message_id="GT-TEST", client=client)
    assert client.calls[0]["tier"] is ModelTier.CHEAP
    assert result.model == "gpt-4o-mini"


def test_versioned_prompt_is_used_by_default():
    client = StubClient(ClaimExtraction(reasoning="x"))
    extract(TEXT, datetime(2026, 7, 25), "email", message_id="GT-TEST", client=client)
    assert client.calls[0]["system_prompt"] == SYSTEM_PROMPT


def test_prompt_can_be_overridden_for_eval():
    """Prompt variants are compared on one sample; the pipeline never does this."""
    client = StubClient(ClaimExtraction(reasoning="x"))
    extract(
        TEXT,
        datetime(2026, 7, 25),
        "email",
        message_id="GT-TEST",
        client=client,
        system_prompt="kısa deneme promptu",
    )
    assert client.calls[0]["system_prompt"] == "kısa deneme promptu"


def test_tier_can_be_overridden_for_eval():
    """Eval puts both tiers on the same sample; the pipeline never does."""
    client = StubClient(ClaimExtraction(reasoning="x"))
    result = extract(
        TEXT,
        datetime(2026, 7, 25),
        "email",
        message_id="GT-TEST",
        client=client,
        tier=ModelTier.STRONG,
    )
    assert client.calls[0]["tier"] is ModelTier.STRONG
    assert result.model == "gpt-4o"


def test_external_ref_reaches_the_client_factory(monkeypatch):
    """Offline (DEMO_OFFLINE) the factory picks the recorded answer by gt_id.

    extract() never reads external_ref itself; dropping it would still produce
    an extraction, just always the wildcard one, on every record.
    """
    seen: dict = {}

    def fake_factory(*, external_ref=None):
        seen["external_ref"] = external_ref
        return StubClient(ClaimExtraction(reasoning="x"))

    monkeypatch.setattr(extractor_module, "get_llm_client", fake_factory)

    extract(TEXT, datetime(2026, 7, 25), "email", message_id="1", external_ref="GT-000007")

    assert seen["external_ref"] == "GT-000007"


def test_without_an_external_ref_the_factory_gets_none(monkeypatch):
    """A message posted straight to /ingest has no gt_id."""
    seen: dict = {}

    def fake_factory(*, external_ref=None):
        seen["external_ref"] = external_ref
        return StubClient(ClaimExtraction(reasoning="x"))

    monkeypatch.setattr(extractor_module, "get_llm_client", fake_factory)

    extract(TEXT, datetime(2026, 7, 25), "email", message_id="1")

    assert seen["external_ref"] is None
