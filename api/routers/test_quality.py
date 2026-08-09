# api/routers/test_quality.py
"""Tests for GET /istatistik/kalite.

The endpoint serves a committed file, so what is worth testing is the wiring:
that it is behind auth like the rest of /istatistik, that the shipped report
actually validates against the response model, and that a missing or broken
file fails loudly instead of rendering as an empty table.
"""

import json

import pytest

from api.routers import quality


@pytest.fixture(autouse=True)
def _clear_report_cache():
    """The loader caches for the life of the process; tests need it not to."""
    quality._load_report.cache_clear()
    yield
    quality._load_report.cache_clear()


def test_get_kalite_without_auth_returns_401(client):
    response = client.get("/istatistik/kalite")
    assert response.status_code == 401


def test_get_kalite_with_auth_succeeds(client, auth_headers):
    response = client.get("/istatistik/kalite", headers=auth_headers)
    assert response.status_code == 200


def test_the_committed_report_validates_against_the_response_model(client, auth_headers):
    """Guards the contract between eval/report.py and this API.

    eval/report.py builds the file from dataclasses and nothing forces the two
    shapes to agree; if they drift, this is where it shows rather than on the
    screen.
    """
    payload = client.get("/istatistik/kalite", headers=auth_headers).json()

    assert payload["schema_version"] == 1
    assert len(payload["metrics"]) == payload["summary"]["total"]


def test_every_row_carries_a_target_and_a_verdict(client, auth_headers):
    payload = client.get("/istatistik/kalite", headers=auth_headers).json()

    for row in payload["metrics"]:
        assert row["target_operator"] in {"gte", "lte"}
        assert row["status"] in {"pass", "fail", "unmeasured"}


def test_a_missing_report_is_an_error_not_an_empty_table(
    client, auth_headers, tmp_path, monkeypatch
):
    """ "Nothing measured yet" and "I cannot find the measurements" differ."""
    monkeypatch.setattr(quality, "REPORT_PATH", tmp_path / "absent.json")
    quality._load_report.cache_clear()

    response = client.get("/istatistik/kalite", headers=auth_headers)

    assert response.status_code == 503


def test_a_corrupt_report_fails_loudly_rather_than_half_rendering(
    client, auth_headers, tmp_path, monkeypatch
):
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    monkeypatch.setattr(quality, "REPORT_PATH", broken)
    quality._load_report.cache_clear()

    response = client.get("/istatistik/kalite", headers=auth_headers)

    assert response.status_code == 503
