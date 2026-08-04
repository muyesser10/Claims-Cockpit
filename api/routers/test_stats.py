# api/routers/test_stats.py
"""Auth-gating tests for GET /istatistik/ozet (S3-8).

No endpoint-behavior tests existed for this router before S3-8; this file
only covers what S3-8 added — everything else is unchanged.
"""


def test_get_ozet_without_auth_returns_401(client):
    response = client.get("/istatistik/ozet")
    assert response.status_code == 401


def test_get_ozet_with_auth_succeeds(client, auth_headers):
    response = client.get("/istatistik/ozet", headers=auth_headers)
    assert response.status_code == 200
