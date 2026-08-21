# worker/llm/test_offline.py
"""Tests for the DEMO_OFFLINE seam (S4-6).

Nothing here touches the network, and nothing here touches the real
demo/fixtures/ files except one test that deliberately loads them to prove the
committed set is usable.
"""

import json

import pytest
from prometheus_client import REGISTRY
from pydantic import BaseModel

from worker.llm.client import (
    OFFLINE_CHEAP_MODEL,
    OFFLINE_STRONG_MODEL,
    FixtureCompletions,
    FixtureLoadError,
    LlmClient,
    ModelTier,
    get_llm_client,
    is_demo_offline,
    load_fixtures,
)


class Answer(BaseModel):
    """A throwaway response model, standing in for ClaimExtraction."""

    value: str


def write_fixtures(directory, records: list[dict], name: str = "demo_test.jsonl") -> None:
    """Write a fixture file into a temp directory, one JSON object per line."""
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    (directory / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def entry(gt_id: str, value: str, response_model: str = "Answer") -> dict:
    return {
        "gt_id": gt_id,
        "response_model": response_model,
        "tier": "cheap",
        "payload": {"value": value},
    }


# --- is_demo_offline ---------------------------------------------------------


def test_unset_means_online(monkeypatch):
    monkeypatch.delenv("DEMO_OFFLINE", raising=False)
    assert is_demo_offline() is False


@pytest.mark.parametrize("value", ["true", "TRUE", " True ", "1", "yes"])
def test_truthy_values_turn_it_on(monkeypatch, value):
    monkeypatch.setenv("DEMO_OFFLINE", value)
    assert is_demo_offline() is True


@pytest.mark.parametrize("value", ["false", "0", "no", "", "off", "evet"])
def test_everything_else_stays_online(monkeypatch, value):
    """Only the three documented spellings switch it on.

    Anything unrecognised means online, deliberately: reaching OpenAI when the
    operator meant offline is a visible failure, while serving fixtures when
    they meant live is a silent one.
    """
    monkeypatch.setenv("DEMO_OFFLINE", value)
    assert is_demo_offline() is False


# --- get_llm_client ----------------------------------------------------------


def test_online_builds_a_normal_client(monkeypatch):
    monkeypatch.delenv("DEMO_OFFLINE", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")

    client = get_llm_client("GT-000001")

    assert isinstance(client, LlmClient)
    assert not isinstance(client.client, FixtureCompletions)
    assert client.settings.api_key == "sk-test-not-used"


def test_offline_needs_no_api_key(monkeypatch):
    """The whole point: a machine with no key still gets a working client."""
    monkeypatch.setenv("DEMO_OFFLINE", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    client = get_llm_client("GT-000001")

    assert isinstance(client.client, FixtureCompletions)
    assert client.client.external_ref == "GT-000001"


def test_offline_reports_a_model_name_that_is_not_a_real_model(monkeypatch):
    """This string reaches audit_trail; a recorded answer must not read as gpt-4o."""
    monkeypatch.setenv("DEMO_OFFLINE", "true")

    client = get_llm_client()

    assert client.settings.model_for(ModelTier.CHEAP) == OFFLINE_CHEAP_MODEL
    assert client.settings.model_for(ModelTier.STRONG) == OFFLINE_STRONG_MODEL
    assert "gpt" not in OFFLINE_CHEAP_MODEL


# --- fixture lookup ----------------------------------------------------------


def test_an_exact_gt_id_wins(tmp_path):
    write_fixtures(tmp_path, [entry("*", "wildcard"), entry("GT-000007", "exact")])

    result, completion = FixtureCompletions("GT-000007", directory=tmp_path).create_with_completion(
        response_model=Answer
    )

    assert result.value == "exact"
    assert completion is None


def test_an_unknown_gt_id_falls_back_to_the_wildcard(tmp_path):
    write_fixtures(tmp_path, [entry("*", "wildcard"), entry("GT-000007", "exact")])

    result, _ = FixtureCompletions("GT-999999", directory=tmp_path).create_with_completion(
        response_model=Answer
    )

    assert result.value == "wildcard"


def test_no_external_ref_falls_back_to_the_wildcard(tmp_path):
    """A question typed live at the demo has no gt_id."""
    write_fixtures(tmp_path, [entry("*", "wildcard")])

    result, _ = FixtureCompletions(directory=tmp_path).create_with_completion(response_model=Answer)

    assert result.value == "wildcard"


def test_the_payload_goes_through_the_real_schema(tmp_path):
    """Fixtures are parsed by the response model, not handed back as dicts."""
    write_fixtures(tmp_path, [entry("*", "wildcard")])

    result, _ = FixtureCompletions(directory=tmp_path).create_with_completion(response_model=Answer)

    assert isinstance(result, Answer)


def test_it_works_through_a_real_LlmClient(tmp_path, monkeypatch):
    """The seam is the injected client, so structured() still does its own job."""
    monkeypatch.setenv("DEMO_OFFLINE", "true")
    write_fixtures(tmp_path, [entry("*", "wildcard")])

    client = get_llm_client()
    client.client = FixtureCompletions(directory=tmp_path)

    result = client.structured(
        tier=ModelTier.CHEAP,
        response_model=Answer,
        system_prompt="prompt",
        user_content="content",
        message_id="GT-TEST",
    )

    assert result.value == "wildcard"


def test_an_offline_call_bills_no_tokens(tmp_path, monkeypatch):
    """A recorded answer cost nothing, and the cost panel must say so.

    FixtureCompletions returns completion=None, so there is no usage to read.
    The call is still counted — the demo does run the real pipeline — but no
    token series may appear for it, or a fully offline demo would report a bill.
    """
    monkeypatch.setenv("DEMO_OFFLINE", "true")
    write_fixtures(tmp_path, [entry("*", "wildcard")])

    client = get_llm_client()
    client.client = FixtureCompletions(directory=tmp_path)

    labels = {"model": OFFLINE_CHEAP_MODEL, "tier": "cheap", "outcome": "ok"}
    before = REGISTRY.get_sample_value("llm_calls_total", labels) or 0

    client.structured(
        tier=ModelTier.CHEAP,
        response_model=Answer,
        system_prompt="prompt",
        user_content="content",
        message_id="GT-TEST",
    )

    assert REGISTRY.get_sample_value("llm_calls_total", labels) == before + 1
    for kind in ("prompt", "completion"):
        assert (
            REGISTRY.get_sample_value(
                "llm_tokens_total",
                {"model": OFFLINE_CHEAP_MODEL, "tier": "cheap", "kind": kind},
            )
            is None
        )


# --- loading errors ----------------------------------------------------------


def test_loading_is_lazy(tmp_path):
    """Constructing the stub must not read anything.

    The fixture set is a demo feature; importing the module or building a
    client must never depend on it existing.
    """
    missing = tmp_path / "not-created"
    stub = FixtureCompletions(directory=missing)

    with pytest.raises(FixtureLoadError, match="fixture directory not found"):
        stub.create_with_completion(response_model=Answer)


def test_a_response_model_without_a_wildcard_is_refused(tmp_path):
    write_fixtures(tmp_path, [entry("GT-000007", "exact")])

    with pytest.raises(FixtureLoadError) as exc:
        load_fixtures(tmp_path)

    # The message has to name the model, or finding the gap means grepping.
    assert "Answer" in str(exc.value)
    assert "'*'" in str(exc.value)


def test_malformed_json_names_the_file_and_line(tmp_path):
    (tmp_path / "demo_broken.jsonl").write_text(
        json.dumps(entry("*", "ok")) + "\n{ not json\n", encoding="utf-8"
    )

    with pytest.raises(FixtureLoadError, match="demo_broken.jsonl:2"):
        load_fixtures(tmp_path)


def test_a_record_missing_a_required_key_is_refused(tmp_path):
    write_fixtures(tmp_path, [{"gt_id": "*", "tier": "cheap"}])

    with pytest.raises(FixtureLoadError, match="response_model, payload"):
        load_fixtures(tmp_path)


def test_a_duplicate_record_is_refused(tmp_path):
    """Two answers for one key is an editing accident, not a preference."""
    write_fixtures(tmp_path, [entry("*", "one"), entry("*", "two")])

    with pytest.raises(FixtureLoadError, match="duplicate"):
        load_fixtures(tmp_path)


def test_an_empty_directory_is_refused(tmp_path):
    with pytest.raises(FixtureLoadError, match="no demo_"):
        load_fixtures(tmp_path)


def test_a_response_model_with_no_fixtures_at_all_raises(tmp_path):
    """Unlike a missing gt_id, there is nothing to fall back to here."""
    write_fixtures(tmp_path, [entry("*", "ok", response_model="SomethingElse")])

    with pytest.raises(FixtureLoadError, match="no offline fixtures recorded for Answer"):
        FixtureCompletions(directory=tmp_path).create_with_completion(response_model=Answer)


def test_files_outside_the_demo_prefix_are_ignored(tmp_path):
    """The loader reads demo_*.jsonl only - eval fixtures must never leak in."""
    write_fixtures(tmp_path, [entry("*", "wildcard")])
    (tmp_path / "eval_something.jsonl").write_text(
        json.dumps(entry("*", "eval")) + "\n", encoding="utf-8"
    )

    result, _ = FixtureCompletions(directory=tmp_path).create_with_completion(response_model=Answer)

    assert result.value == "wildcard"


# --- the committed fixture set ----------------------------------------------


def test_the_real_fixture_set_loads_and_covers_both_models():
    """Guards the generated files: a broken one must fail in CI, not on stage."""
    index = load_fixtures()

    assert "ClaimExtraction" in index
    assert "SanityCheckResult" in index
    for name, by_gt_id in index.items():
        assert "*" in by_gt_id, f"{name} has no wildcard record"


def test_the_real_extraction_wildcard_invents_nothing():
    """The answer for an unrecorded message must not carry a plausible plate."""
    payload = load_fixtures()["ClaimExtraction"]["*"]

    for field in ("policy_no", "plate", "incident_date", "estimated_amount", "damage_type"):
        assert payload[field] is None
    assert payload["incident_location"] == {"city": None, "district": None}


def test_the_real_fixtures_carry_no_personal_block():
    """The ground truth's _personal block (name/phone/tc) must not be copied."""
    index = load_fixtures()

    for by_gt_id in index.values():
        for payload in by_gt_id.values():
            assert "_personal" not in payload
