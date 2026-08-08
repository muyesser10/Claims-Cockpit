# worker/rag/test_ask.py
"""Tests for the /soru orchestration.

The LLM client is stubbed but the modules around it are real: the router, the
SQL guard, the citation check and the number check all run. Only the two steps
that need a database - retrieval's vector search and the SQL execution - are
replaced, so what is under test is the order of the steps and what happens when
one of them fails.
"""

import pytest
from sqlalchemy.exc import OperationalError

from worker.llm.client import ModelTier, get_llm_client
from worker.rag import ask as ask_module
from worker.rag.answer import RagAnswer
from worker.rag.ask import (
    AUDIT_STEP,
    EXECUTION_FAILED_REFUSAL,
    GENERATION_FAILED_REFUSAL,
    ask,
    normalize_question,
)
from worker.rag.retrieval import RetrievedClaim
from worker.rag.router import QuestionRoute, Route
from worker.rag.schema import SqlQuery
from worker.rag.sql_answer import SqlNarration
from worker.rag.sql_guard import check

STUB_MODEL = "gpt-4o-mini-stub"

COUNT_SQL = "SELECT COUNT(*) AS n FROM claims_flat"


class StubClient:
    """Answers each step with a prepared reply, keyed by the schema it asks for.

    One client serves the whole flow, the same way ask() threads one real client
    through it, so a test can assert on how many calls a question cost.
    """

    def __init__(self, **replies) -> None:
        self.replies = replies
        self.calls: list[dict] = []
        self.settings = _StubSettings()

    def structured(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies[kwargs["response_model"].__name__]


class _StubSettings:
    def model_for(self, tier) -> str:
        return STUB_MODEL


class FakeSession:
    """Records what the audit write did without touching a database."""

    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _route(**kwargs) -> QuestionRoute:
    defaults = {"reasoning": "test", "route": "retrieval", "urgency": None, "status": None}
    return QuestionRoute(**{**defaults, **kwargs})


def _sql_query(**kwargs) -> SqlQuery:
    defaults = {"reasoning": "test", "answerable": True, "sql": COUNT_SQL, "refusal_reason": None}
    return SqlQuery(**{**defaults, **kwargs})


def _narration(**kwargs) -> SqlNarration:
    defaults = {
        "reasoning": "test",
        "answerable": True,
        "answer": "Toplam 12 ihbar var.",
        "refusal_reason": None,
    }
    return SqlNarration(**{**defaults, **kwargs})


def _rag_answer(**kwargs) -> RagAnswer:
    defaults = {
        "reasoning": "test",
        "answerable": True,
        "answer": "Park halinde çarpma bildirilmiş [1]",
        "refusal_reason": None,
        "used_sources": [1],
    }
    return RagAnswer(**{**defaults, **kwargs})


def _source(claim_id: int = 7) -> RetrievedClaim:
    return RetrievedClaim(
        claim_id=claim_id,
        external_ref=f"GT-{claim_id:06d}",
        snippet="Otoparkta park halindeyken arka tampona çarpmışlar.",
        score=0.87,
        urgency="normal",
        incident_date="2026-07-14",
    )


@pytest.fixture
def db() -> FakeSession:
    return FakeSession()


def _stub_search(monkeypatch, sources: list[RetrievedClaim]) -> list[dict]:
    """Replace the vector search and record how it was called."""
    calls: list[dict] = []

    def fake_search(_db, question, **kwargs):
        calls.append({"question": question, **kwargs})
        return sources

    monkeypatch.setattr(ask_module, "search", fake_search)
    return calls


def _stub_run_query(monkeypatch, rows: list[dict] | None = None, raises: Exception | None = None):
    def fake_run_query(_db, sql):
        if raises is not None:
            raise raises
        return rows or []

    monkeypatch.setattr(ask_module, "run_query", fake_run_query)


# --- the retrieval path --------------------------------------------------


def test_retrieval_question_comes_back_with_its_sources(db, monkeypatch):
    _stub_search(monkeypatch, [_source()])
    client = StubClient(QuestionRoute=_route(), RagAnswer=_rag_answer())

    result = ask(db, "park halinde ne oluyor", question_id="q1", client=client)

    assert result.mode == "retrieval"
    assert result.answerable is True
    assert [source.claim_id for source in result.sources] == [7]
    assert result.sql is None
    assert result.row_count is None


def test_a_filter_in_the_question_makes_it_hybrid_and_narrows_the_search(db, monkeypatch):
    calls = _stub_search(monkeypatch, [_source()])
    client = StubClient(QuestionRoute=_route(urgency="critical"), RagAnswer=_rag_answer())

    result = ask(db, "kritik ihbarlarda neler anlatılıyor", question_id="q1", client=client)

    assert result.mode == "hybrid"
    assert calls[0]["urgency"] == "critical"
    assert calls[0]["status"] is None


def test_an_uncited_answer_is_withheld_by_the_answer_layer(db, monkeypatch):
    # Nothing in ask() enforces this; the test is here to prove the wiring does
    # not route around answer.py's citation check.
    _stub_search(monkeypatch, [_source()])
    client = StubClient(QuestionRoute=_route(), RagAnswer=_rag_answer(used_sources=[9]))

    result = ask(db, "park halinde ne oluyor", question_id="q1", client=client)

    assert result.answerable is False
    assert result.answer is None
    assert result.sources == []


def test_no_matching_claims_refuses_without_asking_the_model(db, monkeypatch):
    _stub_search(monkeypatch, [])
    client = StubClient(QuestionRoute=_route(), RagAnswer=_rag_answer())

    result = ask(db, "hiç eşleşmeyen soru", question_id="q1", client=client)

    assert result.answerable is False
    assert result.refusal_reason is not None
    # Only the router was asked; there was nothing to answer from.
    assert [call["response_model"].__name__ for call in client.calls] == ["QuestionRoute"]


# --- the SQL path --------------------------------------------------------


def test_sql_question_returns_the_query_and_the_row_count(db, monkeypatch):
    _stub_run_query(monkeypatch, rows=[{"n": 12}])
    client = StubClient(
        QuestionRoute=_route(route="sql"),
        SqlQuery=_sql_query(),
        SqlNarration=_narration(),
    )

    result = ask(db, "kaç ihbar var", question_id="q1", client=client)

    assert result.mode == "sql"
    assert result.answerable is True
    assert result.answer == "Toplam 12 ihbar var."
    # The guard's output, not the model's text: it added the bound.
    assert result.sql == "SELECT COUNT(*) AS n FROM claims_flat LIMIT 100"
    assert result.row_count == 1
    assert result.sources == []


def test_a_model_refusal_on_the_sql_path_keeps_its_own_reason(db, monkeypatch):
    _stub_run_query(monkeypatch, rows=[])
    client = StubClient(
        QuestionRoute=_route(route="sql"),
        SqlQuery=_sql_query(answerable=False, sql=None, refusal_reason="Şemada bu bilgi yok."),
    )

    result = ask(db, "sürücünün kan grubu ne", question_id="q1", client=client)

    assert result.answerable is False
    assert result.refusal_reason == "Şemada bu bilgi yok."
    assert result.sql is None


def test_a_query_the_guard_rejects_never_runs(db, monkeypatch):
    def explode(_db, _sql):
        raise AssertionError("rejected SQL must not reach the database")

    monkeypatch.setattr(ask_module, "run_query", explode)
    client = StubClient(
        QuestionRoute=_route(route="sql"),
        SqlQuery=_sql_query(sql="DROP TABLE claims"),
    )

    result = ask(db, "tabloyu sil", question_id="q1", client=client)

    assert result.answerable is False
    assert result.refusal_reason == GENERATION_FAILED_REFUSAL
    assert result.sql is None


def test_a_query_that_cannot_run_refuses_and_rolls_back(db, monkeypatch):
    # This is the claims_flat blocker: until the view exists every SQL question
    # lands here, and it has to read as a refusal rather than a 500.
    _stub_run_query(
        monkeypatch,
        raises=OperationalError("SELECT 1", {}, Exception('relation "claims_flat" does not exist')),
    )
    client = StubClient(QuestionRoute=_route(route="sql"), SqlQuery=_sql_query())

    result = ask(db, "kaç ihbar var", question_id="q1", client=client)

    assert result.answerable is False
    assert result.refusal_reason == EXECUTION_FAILED_REFUSAL
    # The query is still shown: an operator can read it even when it did not run.
    assert result.sql == "SELECT COUNT(*) AS n FROM claims_flat LIMIT 100"
    assert db.rollbacks == 1


def test_an_invented_number_is_withheld_by_the_narrator(db, monkeypatch):
    _stub_run_query(monkeypatch, rows=[{"n": 12}])
    client = StubClient(
        QuestionRoute=_route(route="sql"),
        SqlQuery=_sql_query(),
        SqlNarration=_narration(answer="Toplam 1.247 ihbar var."),
    )

    result = ask(db, "kaç ihbar var", question_id="q1", client=client)

    assert result.answerable is False
    assert result.answer is None
    # Still reported as a SQL answer that ran: the row count is real.
    assert result.row_count == 1


# --- which session the query runs on -------------------------------------


def _stub_run_query_recording(monkeypatch, rows: list[dict] | None = None) -> list:
    """Record the session run_query was handed."""
    sessions: list = []

    def fake_run_query(db, sql):
        sessions.append(db)
        return rows or []

    monkeypatch.setattr(ask_module, "run_query", fake_run_query)
    return sessions


def test_without_sql_db_the_query_runs_on_the_caller_session(db, monkeypatch):
    """The regression guard for eval and every pre-existing caller.

    ask() grew a `sql_db` parameter so the rag service can run generated SQL as
    rag_readonly. Callers that do not pass one - eval/, the tests above - must
    keep the single-session behaviour they had.
    """
    sessions = _stub_run_query_recording(monkeypatch, rows=[{"n": 12}])
    client = StubClient(
        QuestionRoute=_route(route="sql"),
        SqlQuery=_sql_query(),
        SqlNarration=_narration(),
    )

    result = ask(db, "kaç ihbar var", question_id="q1", client=client)

    assert sessions == [db]
    assert result.answerable is True
    # And the audit row still lands on that same session.
    assert db.commits == 1


def test_sql_db_takes_over_the_query_but_not_the_audit_write(db, monkeypatch):
    sql_db = FakeSession()
    sessions = _stub_run_query_recording(monkeypatch, rows=[{"n": 12}])
    client = StubClient(
        QuestionRoute=_route(route="sql"),
        SqlQuery=_sql_query(),
        SqlNarration=_narration(),
    )

    ask(db, "kaç ihbar var", question_id="q1", client=client, sql_db=sql_db)

    assert sessions == [sql_db]
    # The audit row is a write: it stays on the caller's session, which is the
    # one still allowed to write.
    assert len(db.added) == 1
    assert db.commits == 1
    assert sql_db.added == []
    assert sql_db.commits == 0


def test_a_failed_query_rolls_back_the_session_it_ran_on(db, monkeypatch):
    sql_db = FakeSession()

    def failing_run_query(_db, _sql):
        raise OperationalError("SELECT 1", {}, Exception("permission denied for table claims"))

    monkeypatch.setattr(ask_module, "run_query", failing_run_query)
    client = StubClient(QuestionRoute=_route(route="sql"), SqlQuery=_sql_query())

    result = ask(db, "kaç ihbar var", question_id="q1", client=client, sql_db=sql_db)

    assert result.refusal_reason == EXECUTION_FAILED_REFUSAL
    assert sql_db.rollbacks == 1
    # The api's session was never poisoned, so it was never rolled back - and
    # the audit row still got written.
    assert db.rollbacks == 0
    assert db.commits == 1


def test_the_retrieval_path_ignores_sql_db(db, monkeypatch):
    """Only generated SQL moves. The vector search reads tables the read-only
    role cannot see, so it must stay on the caller's session."""
    sql_db = FakeSession()
    searched: list = []

    def fake_search(search_db, _question, **_kwargs):
        searched.append(search_db)
        return [_source()]

    monkeypatch.setattr(ask_module, "search", fake_search)
    client = StubClient(QuestionRoute=_route(), RagAnswer=_rag_answer())

    ask(db, "park halinde ne oluyor", question_id="q1", client=client, sql_db=sql_db)

    assert searched == [db]
    assert sql_db.added == []
    assert sql_db.rollbacks == 0


# --- the audit row -------------------------------------------------------


def test_every_question_writes_one_audit_row(db, monkeypatch):
    _stub_search(monkeypatch, [_source()])
    client = StubClient(QuestionRoute=_route(), RagAnswer=_rag_answer())

    ask(db, "park halinde ne oluyor", question_id="q1", client=client)

    assert len(db.added) == 1
    assert db.commits == 1
    row = db.added[0]
    assert row.step == AUDIT_STEP
    # A question is not about one claim.
    assert row.claim_id is None
    assert row.detail["question_id"] == "q1"
    assert row.detail["route"] == "retrieval"
    assert row.detail["mode"] == "retrieval"
    assert row.detail["outcome"] == "answered"


def test_the_audit_row_records_why_a_sql_question_failed(db, monkeypatch):
    _stub_run_query(
        monkeypatch,
        raises=OperationalError("SELECT 1", {}, Exception('relation "claims_flat" does not exist')),
    )
    client = StubClient(QuestionRoute=_route(route="sql"), SqlQuery=_sql_query())

    ask(db, "kaç ihbar var", question_id="q1", client=client)

    detail = db.added[0].detail
    assert detail["outcome"] == "execution_failed"
    assert "claims_flat" in detail["error"]


def test_eval_runs_can_turn_the_audit_row_off(db, monkeypatch):
    _stub_search(monkeypatch, [_source()])
    client = StubClient(QuestionRoute=_route(), RagAnswer=_rag_answer())

    ask(db, "park halinde ne oluyor", question_id="q1", client=client, audit=False)

    assert db.added == []
    assert db.commits == 0


def test_a_failing_audit_write_does_not_cost_the_answer(db, monkeypatch):
    _stub_search(monkeypatch, [_source()])

    def failing_commit():
        raise OperationalError("INSERT", {}, Exception("audit table gone"))

    db.commit = failing_commit
    client = StubClient(QuestionRoute=_route(), RagAnswer=_rag_answer())

    result = ask(db, "park halinde ne oluyor", question_id="q1", client=client)

    assert result.answerable is True
    assert db.rollbacks == 1


# --- odds and ends -------------------------------------------------------


def test_a_question_without_an_id_gets_one(db, monkeypatch):
    _stub_search(monkeypatch, [_source()])
    client = StubClient(QuestionRoute=_route(), RagAnswer=_rag_answer())

    ask(db, "park halinde ne oluyor", client=client)

    assert db.added[0].detail["question_id"]
    # The same id threads through every step of the question.
    assert {call["message_id"] for call in client.calls} == {db.added[0].detail["question_id"]}


def test_duration_covers_the_whole_question_not_one_step(db, monkeypatch):
    _stub_search(monkeypatch, [_source()])
    client = StubClient(QuestionRoute=_route(), RagAnswer=_rag_answer())

    result = ask(db, "park halinde ne oluyor", question_id="q1", client=client)

    assert result.duration_ms >= 0
    assert db.added[0].duration_ms == result.duration_ms


# --- DEMO_OFFLINE (S4-6) -------------------------------------------------
#
# These go through the real get_llm_client() and the committed demo/fixtures/
# set, not StubClient: what is under test is whether a demo question finds its
# recorded answer, which a stub would answer by construction.

DEMO_SQL_QUESTIONS = [
    "Kaç tane kritik ihbar var?",
    "Hangi şehirlerde en çok hasar bildirimi var?",
    "Kaç tane dolu hasarı bildirildi?",
]

DEMO_RETRIEVAL_QUESTIONS = [
    "Camı kırılan bir araç var mı?",
    "Yaralanmalı bir kaza var mı, ne olmuş?",
]


@pytest.fixture
def demo_offline(monkeypatch):
    monkeypatch.setenv("DEMO_OFFLINE", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _recorded(question: str, response_model):
    """What the offline client answers for `question` and this model."""
    client = get_llm_client(external_ref=normalize_question(question))
    return client.structured(
        tier=ModelTier.CHEAP,
        response_model=response_model,
        system_prompt="prompt",
        user_content=f"SORU: {question}",
        message_id="q1",
    )


def test_normalize_question_strips_and_lowercases():
    assert normalize_question("  Kaç Tane Kritik İhbar Var?  ") == "kaç tane kritik i̇hbar var?"
    assert normalize_question("abc") == "abc"
    assert normalize_question("") == ""


def test_normalize_question_is_what_the_fixtures_were_keyed_with():
    """The builder calls this same function; a change here invalidates the set."""
    assert normalize_question("Kaç tane kritik ihbar var?") == "kaç tane kritik ihbar var?"


@pytest.mark.parametrize("question", DEMO_SQL_QUESTIONS)
def test_a_demo_sql_question_is_routed_to_sql(question, demo_offline):
    assert _recorded(question, QuestionRoute).route is Route.SQL


@pytest.mark.parametrize("question", DEMO_RETRIEVAL_QUESTIONS)
def test_a_demo_retrieval_question_is_routed_to_retrieval(question, demo_offline):
    assert _recorded(question, QuestionRoute).route is Route.RETRIEVAL


@pytest.mark.parametrize("question", DEMO_SQL_QUESTIONS + DEMO_RETRIEVAL_QUESTIONS)
def test_case_and_padding_do_not_lose_the_recorded_answer(question, demo_offline):
    """A question typed live arrives with a stray space or a capital."""
    typed = f"  {question.capitalize()}  "

    assert _recorded(typed, QuestionRoute).route is _recorded(question, QuestionRoute).route


@pytest.mark.parametrize("question", DEMO_SQL_QUESTIONS)
def test_recorded_sql_passes_the_real_guard(question, demo_offline):
    """The canned query is vetted, not trusted - guard bounds it like any other."""
    reply = _recorded(question, SqlQuery)

    assert reply.answerable is True
    safe_sql = check(reply.sql)
    assert "claims_flat" in safe_sql
    assert "LIMIT 100" in safe_sql


def test_the_injury_question_carries_the_critical_filter(demo_offline):
    """Without it the nearest hits are not injury records - see the builder."""
    route = _recorded("Yaralanmalı bir kaza var mı, ne olmuş?", QuestionRoute)

    assert route.urgency == "critical"


def test_an_unknown_question_falls_back_to_the_wildcard(demo_offline):
    route = _recorded("Bugün hava nasıl?", QuestionRoute)
    reply = _recorded("Bugün hava nasıl?", RagAnswer)

    # Retrieval, never SQL: a canned query would answer a different question.
    assert route.route is Route.RETRIEVAL
    assert reply.answerable is False
    assert "bu demo için hazırlanmamış" in reply.refusal_reason


class RecordingSession(FakeSession):
    """A session that records what run_query actually sent to the database."""

    def __init__(self) -> None:
        super().__init__()
        self.statements: list[str] = []

    def execute(self, statement):
        self.statements.append(str(statement))
        return _EmptyResult()


class _EmptyResult:
    def mappings(self):
        return []


def test_offline_sql_reaches_the_database_layer_unmocked(db, demo_offline, monkeypatch):
    """run_query is not stubbed here: the recorded SQL has to travel the real
    path, guard included, and arrive at the session as the guard rewrote it.

    This is the half of Cagri's condition that the fixtures must not shortcut -
    the query really runs, so the numbers on screen come from the database and
    not from the fixture.
    """
    sql_db = RecordingSession()

    ask(db, "Kaç tane kritik ihbar var?", question_id="q1", sql_db=sql_db)

    executed = [s for s in sql_db.statements if "claims_flat" in s]
    assert len(executed) == 1
    assert executed[0] == (
        "SELECT COUNT(*) AS kritik_ihbar_sayisi FROM claims_flat "
        "WHERE urgency = 'critical' LIMIT 100"
    )
    # And the statement timeout still went out ahead of it.
    assert any("statement_timeout" in s for s in sql_db.statements)


def test_offline_retrieval_answer_cites_a_real_source(db, demo_offline, monkeypatch):
    """The recorded answer's citation is checked against what retrieval found."""
    _stub_search(monkeypatch, [_source(claim_id=53)])

    result = ask(db, "Camı kırılan bir araç var mı?", question_id="q1")

    assert result.answerable is True
    assert result.mode == "retrieval"
    assert [source.claim_id for source in result.sources] == [53]
    assert "[1]" in result.answer


def test_offline_unknown_question_refuses_without_crashing(db, demo_offline, monkeypatch):
    _stub_search(monkeypatch, [_source()])

    result = ask(db, "Bugün hava nasıl?", question_id="q1")

    assert result.answerable is False
    assert "bu demo için hazırlanmamış" in result.refusal_reason
    assert result.sources == []
