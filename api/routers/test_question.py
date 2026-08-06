# api/routers/test_question.py
"""Tests for the /soru proxy.

No rag service runs here: httpx is stubbed at the transport layer, so the real
client code - headers, timeout, status handling - is exercised against a fake
server rather than replaced.
"""

import httpx
import pytest

from api.routers import question as question_module
from api.routers.question import (
    RAG_TIMEOUT_DETAIL,
    RAG_UNREACHABLE_DETAIL,
    QuestionResponse,
    QuestionSource,
)

ANSWER_BODY = {
    "question": "park halinde ne oluyor",
    "answer": "Park halinde çarpma bildirilmiş [1]",
    "mode": "retrieval",
    "answerable": True,
    "refusal_reason": None,
    "sources": [
        {
            "claim_id": 7,
            "external_ref": "GT-000007",
            "snippet": "Otoparkta arka tampona çarpmışlar.",
            "score": 0.87,
            "urgency": "normal",
            "incident_date": "2026-07-14",
        }
    ],
    "sql": None,
    "row_count": None,
    "duration_ms": 9400,
}


@pytest.fixture
def rag_stub(monkeypatch):
    """Replace the transport under httpx and record what the proxy sent.

    Patching AsyncClient rather than the proxy's own code keeps the assertions
    honest: the request recorded here is the one that would have gone out.
    """
    sent: list[httpx.Request] = []
    behaviour = {"response": httpx.Response(200, json=ANSWER_BODY), "raises": None}

    class StubClient:
        def __init__(self, *args, **kwargs):
            self.timeout = kwargs.get("timeout")
            behaviour["timeout"] = self.timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, *, json, headers):
            request = httpx.Request("POST", url, json=json, headers=headers)
            sent.append(request)
            if behaviour["raises"] is not None:
                raise behaviour["raises"]
            return behaviour["response"]

    monkeypatch.setattr(question_module.httpx, "AsyncClient", StubClient)
    return {"sent": sent, "behaviour": behaviour}


# --- auth ----------------------------------------------------------------


def test_a_question_without_a_token_never_reaches_the_service(client, rag_stub):
    response = client.post("/soru", json={"question": "park halinde ne oluyor"})

    assert response.status_code == 401
    assert rag_stub["sent"] == []


def test_the_callers_token_is_forwarded(client, auth_headers, rag_stub):
    # ADR-003: without this the rag service becomes an unauthenticated read path
    # into claim data.
    client.post("/soru", json={"question": "park halinde ne oluyor"}, headers=auth_headers)

    assert rag_stub["sent"][0].headers["authorization"] == auth_headers["Authorization"]


# --- the happy path ------------------------------------------------------


def test_the_answer_is_passed_through(client, auth_headers, rag_stub):
    response = client.post(
        "/soru", json={"question": "park halinde ne oluyor"}, headers=auth_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "retrieval"
    assert body["sources"][0]["claim_id"] == 7
    assert body["duration_ms"] == 9400


def test_only_the_question_is_sent_on(client, auth_headers, rag_stub):
    client.post("/soru", json={"question": "park halinde ne oluyor"}, headers=auth_headers)

    assert rag_stub["sent"][0].url.path == "/soru"


def test_the_timeout_outlasts_a_slow_answer(client, auth_headers, rag_stub):
    # Three LLM calls with a 30s ceiling each; a 30s proxy timeout would cut off
    # answers that were still coming.
    client.post("/soru", json={"question": "park halinde ne oluyor"}, headers=auth_headers)

    assert rag_stub["behaviour"]["timeout"] >= 90


# --- failure -------------------------------------------------------------


def test_a_hung_service_becomes_a_504(client, auth_headers, rag_stub):
    rag_stub["behaviour"]["raises"] = httpx.TimeoutException("too slow")

    response = client.post(
        "/soru", json={"question": "park halinde ne oluyor"}, headers=auth_headers
    )

    assert response.status_code == 504
    assert response.json()["detail"] == RAG_TIMEOUT_DETAIL


def test_a_service_that_is_down_becomes_a_503(client, auth_headers, rag_stub):
    rag_stub["behaviour"]["raises"] = httpx.ConnectError("connection refused")

    response = client.post(
        "/soru", json={"question": "park halinde ne oluyor"}, headers=auth_headers
    )

    assert response.status_code == 503
    assert response.json()["detail"] == RAG_UNREACHABLE_DETAIL


def test_an_error_from_the_service_keeps_its_own_status(client, auth_headers, rag_stub):
    # A 401 there must not read as an outage here.
    rag_stub["behaviour"]["response"] = httpx.Response(401, json={"detail": "Bad token"})

    response = client.post(
        "/soru", json={"question": "park halinde ne oluyor"}, headers=auth_headers
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Bad token"


def test_a_validation_error_from_the_service_is_passed_on(client, auth_headers, rag_stub):
    # Length bounds live in the rag service; its 422 has to arrive intact.
    rag_stub["behaviour"]["response"] = httpx.Response(
        422, json={"detail": [{"loc": ["body", "question"], "msg": "too long"}]}
    )

    response = client.post("/soru", json={"question": "a" * 900}, headers=auth_headers)

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "too long"


def test_a_non_json_error_body_still_produces_a_message(client, auth_headers, rag_stub):
    rag_stub["behaviour"]["response"] = httpx.Response(502, text="<html>Bad Gateway</html>")

    response = client.post(
        "/soru", json={"question": "park halinde ne oluyor"}, headers=auth_headers
    )

    assert response.status_code == 502
    assert "Bad Gateway" in response.json()["detail"]


# --- the duplicated contract ---------------------------------------------


def test_the_proxy_models_match_the_rag_service_definitions():
    """The api cannot import worker/rag, so the contract is written twice.

    api/Dockerfile does not copy worker/, which is the point of ADR-003. This
    test is the seam that keeps the two copies honest: it runs in the dev
    checkout and in CI, where both packages exist. A field added on one side and
    not the other fails here rather than as a chip that quietly stops rendering.
    """
    from worker.rag.ask import QuestionAnswer
    from worker.rag.retrieval import RetrievedClaim

    assert set(QuestionResponse.model_fields) == set(QuestionAnswer.model_fields)
    assert set(QuestionSource.model_fields) == set(RetrievedClaim.model_fields)
