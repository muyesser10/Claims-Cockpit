# api/routers/test_auth.py
"""Tests for POST /auth/login."""

from jose import jwt

from api.models.db import User
from api.security import JWT_ALGORITHM, hash_password, load_auth_settings


def _make_user(
    db_session, *, email="operator@test.com", password="correct-password", role="operator"
):
    user = User(email=email, password_hash=hash_password(password), role=role)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_login_with_correct_credentials_returns_token(client, db_session):
    _make_user(db_session, email="a@test.com", password="secret123", role="operator")

    response = client.post("/auth/login", json={"email": "a@test.com", "password": "secret123"})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]


def test_login_token_contains_email_and_role(client, db_session):
    _make_user(db_session, email="b@test.com", password="secret123", role="admin")

    response = client.post("/auth/login", json={"email": "b@test.com", "password": "secret123"})

    token = response.json()["access_token"]
    settings = load_auth_settings()
    payload = jwt.decode(token, settings.secret, algorithms=[JWT_ALGORITHM])
    assert payload["sub"] == "b@test.com"
    assert payload["role"] == "admin"
    assert "exp" in payload


def test_login_with_wrong_password_returns_401(client, db_session):
    _make_user(db_session, email="c@test.com", password="correct-password")

    response = client.post(
        "/auth/login", json={"email": "c@test.com", "password": "wrong-password"}
    )

    assert response.status_code == 401


def test_login_with_unknown_email_returns_401(client, db_session):
    response = client.post("/auth/login", json={"email": "nobody@test.com", "password": "whatever"})

    assert response.status_code == 401


def test_login_error_does_not_reveal_whether_email_exists(client, db_session):
    """Wrong password and unknown email must look identical to the caller —
    a different message/status for either would let an attacker enumerate
    valid accounts."""
    _make_user(db_session, email="d@test.com", password="correct-password")

    wrong_password = client.post(
        "/auth/login", json={"email": "d@test.com", "password": "wrong-password"}
    )
    unknown_email = client.post(
        "/auth/login", json={"email": "nobody@test.com", "password": "whatever"}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]
