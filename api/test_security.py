# api/test_security.py
"""Unit tests for api/security.py: hashing, token encode/decode, expiry."""

from datetime import UTC, datetime, timedelta

import pytest
from jose import JWTError, jwt

from api.models.db import User
from api.security import (
    JWT_ALGORITHM,
    AuthSettings,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

SETTINGS = AuthSettings(secret="unit-test-secret", expire_hours=1)


def _user(email="operator@test.com", role="operator") -> User:
    return User(id=1, email=email, password_hash="unused", role=role)


# --- password hashing ---------------------------------------------------------


def test_hash_password_does_not_return_plaintext():
    hashed = hash_password("my-secret-password")
    assert hashed != "my-secret-password"


def test_verify_password_accepts_correct_password():
    hashed = hash_password("my-secret-password")
    assert verify_password("my-secret-password", hashed) is True


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("my-secret-password")
    assert verify_password("not-the-password", hashed) is False


def test_hash_password_is_salted_differently_each_time():
    """Two hashes of the same password must differ (random salt) — otherwise
    identical passwords would be visibly identical in the DB."""
    first = hash_password("same-password")
    second = hash_password("same-password")
    assert first != second


# --- create_access_token / decode_access_token --------------------------------


def test_create_access_token_round_trips_through_decode():
    user = _user(email="a@test.com", role="operator")
    token = create_access_token(user, settings=SETTINGS)

    payload = decode_access_token(token, settings=SETTINGS)

    assert payload["sub"] == "a@test.com"
    assert payload["role"] == "operator"


def test_create_access_token_includes_role_claim():
    user = _user(role="admin")
    token = create_access_token(user, settings=SETTINGS)

    payload = decode_access_token(token, settings=SETTINGS)

    assert payload["role"] == "admin"


def test_decode_access_token_rejects_wrong_secret():
    user = _user()
    token = create_access_token(user, settings=SETTINGS)
    wrong_settings = AuthSettings(secret="a-different-secret", expire_hours=1)

    with pytest.raises(JWTError):
        decode_access_token(token, settings=wrong_settings)


def test_decode_access_token_rejects_expired_token():
    user = _user()
    now = datetime.now(UTC)
    expired_payload = {
        "sub": user.email,
        "role": user.role,
        "iat": now - timedelta(hours=2),
        "exp": now - timedelta(hours=1),
    }
    expired_token = jwt.encode(expired_payload, SETTINGS.secret, algorithm=JWT_ALGORITHM)

    with pytest.raises(JWTError):
        decode_access_token(expired_token, settings=SETTINGS)


def test_decode_access_token_rejects_malformed_token():
    with pytest.raises(JWTError):
        decode_access_token("not-a-real-jwt", settings=SETTINGS)
