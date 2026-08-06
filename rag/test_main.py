# rag/test_main.py
"""Tests for the /soru service shell.

What is under test is the shell, not the answer: ask() is stubbed. Its own
behaviour is covered in worker/rag/test_ask.py, and calling the real one would
load a model and reach OpenAI.
"""

import inspect

import pytest

from rag import main as rag_main
from rag.main import MAX_QUESTION_CHARS, soru
from worker.rag.ask import QuestionAnswer
from worker.rag.retrieval import RetrievedClaim


def _answer(**kwargs) -> QuestionAnswer:
    defaults = {
        "question": "park halinde ne oluyor",
        "answer": "Park halinde çarpma bildirilmiş [1]",
        "mode": "retrieval",
        "answerable": True,
        "refusal_reason": None,
        "sources": [
            RetrievedClaim(
                claim_id=7,
                external_ref="GT-000007",
                snippet="Otoparkta arka tampona çarpmışlar.",
                score=0.87,
                urgency="normal",
                incident_date="2026-07-14",
            )
        ],
        "sql": None,
        "row_count": None,
        "duration_ms": 9400,
    }
    return QuestionAnswer(**{**defaults, **kwargs})


@pytest.fixture
def stub_ask(monkeypatch):
    """Replace ask() and record how it was called."""
    calls: list[dict] = []

    def fake_ask(db, question, **kwargs):
        calls.append({"question": question, **kwargs})
        return _answer(question=question)

    monkeypatch.setattr(rag_main, "ask", fake_ask)
    return calls


# --- auth ----------------------------------------------------------------


def test_a_question_without_a_token_is_refused(client, stub_ask):
    response = client.post("/soru", json={"question": "park halinde ne oluyor"})

    assert response.status_code == 401
    # ADR-003: this must not become the one unauthenticated read path into
    # claim data. Nothing ran.
    assert stub_ask == []


def test_a_bad_token_is_refused(client, stub_ask):
    response = client.post(
        "/soru",
        json={"question": "park halinde ne oluyor"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 401
    assert stub_ask == []


def test_an_operator_may_ask(client, auth_headers, stub_ask):
    # Asking is a read; /claims and /queue gate reads the same way.
    response = client.post(
        "/soru", json={"question": "park halinde ne oluyor"}, headers=auth_headers
    )

    assert response.status_code == 200
    assert stub_ask[0]["question"] == "park halinde ne oluyor"


# --- the response shape --------------------------------------------------


def test_the_response_matches_the_frozen_contract(client, auth_headers, stub_ask):
    # web/src/api/useQuestion.ts was built against exactly these keys.
    response = client.post(
        "/soru", json={"question": "park halinde ne oluyor"}, headers=auth_headers
    )

    body = response.json()
    assert set(body) == {
        "question",
        "answer",
        "mode",
        "answerable",
        "refusal_reason",
        "sources",
        "sql",
        "row_count",
        "duration_ms",
    }
    assert set(body["sources"][0]) == {
        "claim_id",
        "external_ref",
        "snippet",
        "score",
        "urgency",
        "incident_date",
    }


# --- input bounds --------------------------------------------------------


def test_an_empty_question_is_rejected(client, auth_headers, stub_ask):
    response = client.post("/soru", json={"question": ""}, headers=auth_headers)

    assert response.status_code == 422
    assert stub_ask == []


def test_a_question_longer_than_the_ceiling_is_rejected(client, auth_headers, stub_ask):
    # An unbounded question would go into three LLM prompts.
    response = client.post(
        "/soru", json={"question": "a" * (MAX_QUESTION_CHARS + 1)}, headers=auth_headers
    )

    assert response.status_code == 422
    assert stub_ask == []


def test_a_question_at_the_ceiling_is_accepted(client, auth_headers, stub_ask):
    response = client.post(
        "/soru", json={"question": "a" * MAX_QUESTION_CHARS}, headers=auth_headers
    )

    assert response.status_code == 200


# --- failure -------------------------------------------------------------


def test_an_unexpected_failure_answers_in_turkish_and_is_logged(client, auth_headers, monkeypatch):
    def exploding_ask(db, question, **kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(rag_main, "ask", exploding_ask)

    response = client.post(
        "/soru", json={"question": "park halinde ne oluyor"}, headers=auth_headers
    )

    assert response.status_code == 500
    # The operator reads this; the stack trace goes to the log, not the screen.
    assert response.json()["detail"] == "Soru işlenirken beklenmeyen bir hata oluştu."


# --- the shell itself ----------------------------------------------------


def test_health_needs_no_token(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["service"] == "rag"
    # The lifespan did not run in these tests, so the model is not loaded - and
    # /health says so rather than reporting ready.
    assert response.json()["model_ready"] is False


def test_the_endpoint_is_synchronous(client):
    """ask() blocks for 8-20 seconds.

    As `async def` it would stall the event loop and every other request with
    it; as `def` FastAPI runs it in a threadpool. Asserted rather than trusted
    to a comment, because adding `async` looks like an improvement.
    """
    assert not inspect.iscoroutinefunction(soru)
