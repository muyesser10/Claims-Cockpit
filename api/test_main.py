# api/test_main.py
"""Tests for the app shell: /health and the demo_offline flag it reports."""

import pytest

from api.demo import is_demo_offline

# --- GET /health -------------------------------------------------------------


def test_health_needs_no_token(client):
    """Load balancers and the docker healthcheck cannot carry a JWT."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "api"


def test_health_reports_demo_offline_when_it_is_on(client, monkeypatch):
    monkeypatch.setenv("DEMO_OFFLINE", "true")

    assert client.get("/health").json()["demo_offline"] is True


def test_health_reports_demo_offline_when_it_is_off(client, monkeypatch):
    monkeypatch.delenv("DEMO_OFFLINE", raising=False)

    assert client.get("/health").json()["demo_offline"] is False


def test_health_reads_the_flag_per_request(client, monkeypatch):
    """Not captured at import time.

    The api process is long-lived and the flag is read from the environment,
    so a value frozen at import would keep reporting whatever the container
    started with.
    """
    monkeypatch.setenv("DEMO_OFFLINE", "true")
    assert client.get("/health").json()["demo_offline"] is True

    monkeypatch.setenv("DEMO_OFFLINE", "false")
    assert client.get("/health").json()["demo_offline"] is False


# --- api.demo.is_demo_offline ------------------------------------------------
#
# A deliberate copy of worker/llm/client.py's function (api/ cannot import
# worker/, see api/demo.py). These cover the same cases as
# worker/llm/test_offline.py so the two cannot drift apart unnoticed.


def test_unset_means_online(monkeypatch):
    monkeypatch.delenv("DEMO_OFFLINE", raising=False)
    assert is_demo_offline() is False


@pytest.mark.parametrize("value", ["true", "TRUE", " True ", "1", "yes"])
def test_truthy_values_turn_it_on(monkeypatch, value):
    monkeypatch.setenv("DEMO_OFFLINE", value)
    assert is_demo_offline() is True


@pytest.mark.parametrize("value", ["false", "0", "no", "", "off", "evet"])
def test_everything_else_stays_online(monkeypatch, value):
    monkeypatch.setenv("DEMO_OFFLINE", value)
    assert is_demo_offline() is False
