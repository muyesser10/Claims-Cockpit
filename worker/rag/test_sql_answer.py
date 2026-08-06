# worker/rag/test_sql_answer.py
"""Tests for the SQL path's answer layer: row rendering, number verification,
and the masking round trip.

Nothing here reaches the network or a database: the LLM client is a stub that
returns a prepared SqlNarration and records how it was called. run_query is not
covered here - executing SQL needs a real Postgres, and that lives in
test_retrieval_integration.py's territory.
"""

from decimal import Decimal
from types import SimpleNamespace

from worker.llm.client import ModelTier
from worker.rag.sql_answer import (
    EMPTY_RESULT_REFUSAL,
    NARRATE_ROW_LIMIT,
    ROWS_PLACEHOLDER,
    UNVERIFIED_NUMBER_REFUSAL,
    SqlNarration,
    narrate,
    parse_number,
    render_rows,
    unverified_numbers,
)

STUB_MODEL = "gpt-4o-mini-stub"


class StubClient:
    """Returns a prepared narration and records the call."""

    def __init__(self, reply: SqlNarration) -> None:
        self.reply = reply
        self.calls: list[dict] = []
        self.settings = SimpleNamespace(model_for=lambda tier: STUB_MODEL)

    def structured(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


def _reply(**kwargs) -> SqlNarration:
    defaults = {
        "reasoning": "test",
        "answerable": True,
        "answer": "Toplam 12 ihbar var.",
        "refusal_reason": None,
    }
    return SqlNarration(**{**defaults, **kwargs})


# --- render_rows ---------------------------------------------------------


def test_render_rows_writes_one_line_per_row():
    rendered = render_rows([{"city": "Ankara", "n": 3}, {"city": "Izmir", "n": 1}])

    assert rendered == "1. city: Ankara, n: 3\n2. city: Izmir, n: 1"


def test_render_rows_spells_out_null():
    # An empty cell reads like a rendering bug; "yok" is a fact the model can use.
    assert render_rows([{"injury": None}]) == "1. injury: yok"


def test_render_rows_caps_and_says_how_many_are_hidden():
    rows = [{"id": index} for index in range(NARRATE_ROW_LIMIT + 5)]

    lines = render_rows(rows).splitlines()

    assert len(lines) == NARRATE_ROW_LIMIT + 1
    assert lines[-1] == "... (5 satır daha gösterilmedi)"


def test_render_rows_honours_an_explicit_limit():
    assert render_rows([{"id": 1}, {"id": 2}], limit=1).splitlines()[0] == "1. id: 1"


# --- parse_number --------------------------------------------------------


def test_parse_number_reads_a_plain_integer():
    assert parse_number("12") == Decimal(12)


def test_parse_number_reads_a_turkish_decimal_comma():
    assert parse_number("12,5") == Decimal("12.5")


def test_parse_number_reads_a_lone_dot_with_three_digits_as_grouping():
    # 12.500 is twelve and a half thousand in Turkish, not twelve and a half.
    assert parse_number("12.500") == Decimal(12500)


def test_parse_number_reads_a_lone_dot_with_two_digits_as_a_decimal():
    # This is how Postgres renders a numeric column.
    assert parse_number("12500.00") == Decimal(12500)


def test_parse_number_reads_repeated_dots_as_grouping():
    assert parse_number("1.234.567") == Decimal(1234567)


def test_parse_number_reads_mixed_separators():
    assert parse_number("12.500,75") == Decimal("12500.75")


def test_parse_number_returns_none_when_it_cannot_read_the_token():
    assert parse_number("1.2.3,4,5") is None


# --- unverified_numbers --------------------------------------------------


def test_number_present_in_the_rows_passes():
    assert unverified_numbers("Toplam 47 kayıt var.", "1. n: 47", 1) == []


def test_invented_number_is_reported():
    assert unverified_numbers("Toplam 1.247 kayıt var.", "1. n: 12", 1) == ["1.247"]


def test_formatting_difference_still_passes():
    # Postgres renders 12500.00; the model writes it the Turkish way.
    assert unverified_numbers("Tutar 12.500 TL.", "1. amount: 12500.00", 1) == []


def test_a_year_inside_a_date_passes_on_the_literal_match():
    # Parsing "2026-08-03" as a number would be wrong, but the digits are there.
    assert unverified_numbers("2026 yılında oldu.", "1. incident_date: 2026-08-03", 1) == []


def test_row_count_passes_even_when_no_column_holds_it():
    assert unverified_numbers("5 kayıt bulundu.", "1. city: Ankara", 5) == []


def test_an_answer_without_numbers_has_nothing_to_verify():
    assert unverified_numbers("Kayıtlar İstanbul kaynaklı.", "1. city: İstanbul", 1) == []


def test_every_invented_number_is_reported_not_just_the_first():
    assert unverified_numbers("7 ve 9 kayıt.", "1. n: 12", 1) == ["7", "9"]


# --- narrate -------------------------------------------------------------


def test_empty_result_refuses_without_calling_the_model():
    client = StubClient(_reply())

    result = narrate("kaç ihbar var", [], question_id="q1", client=client)

    assert result.answerable is False
    assert result.refusal_reason == EMPTY_RESULT_REFUSAL
    assert result.row_count == 0
    assert result.model == "none"
    assert client.calls == []


def test_rows_are_injected_into_the_prompt():
    client = StubClient(_reply(answer="Ankara'da 3 kayıt var."))

    narrate("hangi ilde", [{"city": "Ankara", "n": 3}], question_id="q1", client=client)

    prompt = client.calls[0]["system_prompt"]
    assert ROWS_PLACEHOLDER not in prompt
    assert "city: Ankara, n: 3" in prompt


def test_the_sql_is_not_shown_to_the_model():
    # A WHERE clause can carry personal data straight out of the question, which
    # would walk past the masking below. Only the question goes in the message.
    client = StubClient(_reply())

    narrate("kaç ihbar var", [{"n": 12}], question_id="q1", client=client)

    assert client.calls[0]["user_content"] == "SORU: kaç ihbar var"


def test_personal_data_in_the_rows_never_reaches_the_model():
    client = StubClient(_reply(answer="Kayıt bulundu."))

    narrate(
        "plakası ne",
        [{"plate": "34 ABC 123", "policy_no": "POL-2026-00001"}],
        question_id="q1",
        client=client,
    )

    prompt = client.calls[0]["system_prompt"]
    assert "34 ABC 123" not in prompt
    assert "[PLATE_1]" in prompt


def test_the_answer_comes_back_unmasked():
    # The operator sees real values, the model never did.
    client = StubClient(_reply(answer="[PLATE_1] plakalı araç kayıtlı."))

    result = narrate("plakası ne", [{"plate": "34 ABC 123"}], question_id="q1", client=client)

    assert result.answer == "34 ABC 123 plakalı araç kayıtlı."


def test_an_answer_whose_numbers_check_out_is_returned():
    client = StubClient(_reply(answer="Toplam 12 ihbar var."))

    result = narrate("kaç ihbar var", [{"n": 12}], question_id="q1", client=client)

    assert result.answerable is True
    assert result.answer == "Toplam 12 ihbar var."
    assert result.unverified_numbers == []
    assert result.row_count == 1
    assert result.model == STUB_MODEL


def test_an_invented_number_withholds_the_whole_answer():
    client = StubClient(_reply(answer="Toplam 1.247 ihbar var."))

    result = narrate("kaç ihbar var", [{"n": 12}], question_id="q1", client=client)

    assert result.answerable is False
    assert result.answer is None
    assert result.refusal_reason == UNVERIFIED_NUMBER_REFUSAL
    # Kept, not dropped: this is what the error centre reads.
    assert result.unverified_numbers == ["1.247"]


def test_a_refusal_from_the_model_is_passed_through():
    client = StubClient(
        _reply(answerable=False, answer=None, refusal_reason="Sonuç soruyu karşılamıyor.")
    )

    result = narrate("kaç ihbar var", [{"n": 12}], question_id="q1", client=client)

    assert result.answerable is False
    assert result.refusal_reason == "Sonuç soruyu karşılamıyor."
    assert result.unverified_numbers == []


def test_answerable_true_with_no_answer_is_treated_as_a_refusal():
    client = StubClient(_reply(answerable=True, answer=None))

    result = narrate("kaç ihbar var", [{"n": 12}], question_id="q1", client=client)

    assert result.answerable is False


def test_the_call_carries_the_tier_and_seed_it_was_given():
    client = StubClient(_reply(answer="Toplam 12 ihbar var."))

    narrate(
        "kaç ihbar var",
        [{"n": 12}],
        question_id="q1",
        client=client,
        tier=ModelTier.STRONG,
        seed=7,
    )

    call = client.calls[0]
    assert call["tier"] is ModelTier.STRONG
    assert call["seed"] == 7
    assert call["message_id"] == "q1"
