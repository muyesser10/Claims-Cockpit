# worker/rag/test_text_to_sql.py
"""Text-to-SQL tests.

Nothing here touches the network or a database. The LLM client takes an
injectable stub, so these run in CI with no API key and cost nothing - the same
arrangement as worker/llm/test_client.py.
"""

from worker.llm.client import LlmClient, LlmSettings, ModelTier
from worker.rag.schema import SqlQuery
from worker.rag.text_to_sql import build_retry_content, generate_sql


class _StubCompletion:
    """The raw completion object, carrying only the fields the client logs."""

    def __init__(self):
        self.usage = None
        self.system_fingerprint = "fp_test"


class _StubCompletions:
    """Hands back queued answers in order and records every request."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def create_with_completion(self, **kwargs):
        self.calls.append(kwargs)
        answer = self.answers.pop(0) if self.answers else self.answers
        return answer, _StubCompletion()


class _StubChat:
    def __init__(self, completions):
        self.completions = completions


class _StubClient:
    """Shaped like the instructor-patched OpenAI client, but inert."""

    def __init__(self, completions):
        self.chat = _StubChat(completions)


def make_client(*answers):
    """An LlmClient wired to canned answers, with no key and no network."""
    completions = _StubCompletions(answers)
    client = LlmClient(
        settings=LlmSettings(api_key="test-key"),
        client=_StubClient(completions),
    )
    return client, completions


def test_a_clean_query_comes_back_bounded():
    """The guard's LIMIT is applied to what the caller receives, not just checked."""
    client, _ = make_client(
        SqlQuery(
            reasoning="Sayım sorusu.",
            answerable=True,
            sql="SELECT COUNT(*) FROM claims_flat",
        )
    )
    result = generate_sql("Kaç ihbar var?", question_id="q1", client=client)

    assert result.answerable
    assert result.sql == "SELECT COUNT(*) FROM claims_flat LIMIT 100"
    assert result.guard_error is None
    assert result.attempts == 1


def test_a_refusal_is_passed_through():
    client, _ = make_client(
        SqlQuery(
            reasoning="Telefon şemada yok.",
            answerable=False,
            refusal_reason="Telefon numarası bu veritabanında tutulmuyor.",
        )
    )
    result = generate_sql("Telefonu ne?", question_id="q2", client=client)

    assert not result.answerable
    assert result.sql is None
    assert "Telefon" in result.refusal_reason


def test_a_refusal_that_also_carries_sql_drops_the_sql():
    """Self-contradiction: the decline is the safer half, so it wins."""
    client, _ = make_client(
        SqlQuery(
            reasoning="Cevaplanamaz.",
            answerable=False,
            refusal_reason="Şemada yok.",
            sql="SELECT * FROM users",
        )
    )
    result = generate_sql("Kullanıcılar?", question_id="q3", client=client)

    assert not result.answerable
    assert result.sql is None


def test_a_rejected_query_is_retried_once_with_the_reason():
    client, completions = make_client(
        SqlQuery(reasoning="İlk deneme.", answerable=True, sql="SELECT * FROM users"),
        SqlQuery(reasoning="Düzeltildi.", answerable=True, sql="SELECT COUNT(*) FROM claims_flat"),
    )
    result = generate_sql("Kaç ihbar var?", question_id="q4", client=client)

    assert result.attempts == 2
    assert result.sql == "SELECT COUNT(*) FROM claims_flat LIMIT 100"
    assert result.guard_error is None

    # The second request has to carry the failure, otherwise the model reruns
    # the same query having no idea which part was wrong.
    retry_content = completions.calls[1]["messages"][1]["content"]
    assert "users" in retry_content
    assert "not readable" in retry_content


def test_two_bad_answers_end_as_a_failure_not_a_refusal():
    """A botched query and a declined question must not look alike to a caller."""
    client, _ = make_client(
        SqlQuery(reasoning="Bir.", answerable=True, sql="DROP TABLE users"),
        SqlQuery(reasoning="İki.", answerable=True, sql="SELECT * FROM mask_mappings"),
    )
    result = generate_sql("Kaç ihbar var?", question_id="q5", client=client)

    assert result.answerable is True
    assert result.sql is None
    assert result.guard_error is not None
    assert result.refusal_reason is None
    assert result.attempts == 2


def test_self_correction_can_be_switched_off():
    client, completions = make_client(
        SqlQuery(reasoning="Bir.", answerable=True, sql="SELECT * FROM users")
    )
    result = generate_sql("Kaç?", question_id="q6", client=client, self_correct=False)

    assert result.attempts == 1
    assert len(completions.calls) == 1
    assert result.guard_error is not None


def test_answerable_with_no_sql_is_a_failure():
    client, _ = make_client(
        SqlQuery(reasoning="Bir.", answerable=True, sql=None),
        SqlQuery(reasoning="İki.", answerable=True, sql="   "),
    )
    result = generate_sql("Kaç?", question_id="q7", client=client)

    assert result.sql is None
    assert "no SQL" in result.guard_error


def test_the_cheap_tier_is_the_default():
    """ADR-001, update of 2026-08-04: the whole project runs on the cheap model."""
    client, completions = make_client(
        SqlQuery(reasoning="x", answerable=True, sql="SELECT 1 FROM claims_flat")
    )
    generate_sql("Kaç?", question_id="q8", client=client)

    assert completions.calls[0]["model"] == client.settings.model_for(ModelTier.CHEAP)


def test_the_versioned_prompt_carries_the_schema():
    client, completions = make_client(
        SqlQuery(reasoning="x", answerable=True, sql="SELECT 1 FROM claims_flat")
    )
    generate_sql("Kaç?", question_id="q9", client=client)

    system_prompt = completions.calls[0]["messages"][0]["content"]
    assert "claims_flat" in system_prompt
    assert "<<SCHEMA>>" not in system_prompt


def test_retry_content_names_the_question_and_the_error():
    content = build_retry_content("Kaç ihbar var?", "SELECT * FROM users", "table not readable")

    assert "Kaç ihbar var?" in content
    assert "SELECT * FROM users" in content
    assert "table not readable" in content
