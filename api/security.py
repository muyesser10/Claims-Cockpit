# api/security.py
"""JWT auth: settings, password hashing, token encode/decode (S3-8).

Same env-driven settings pattern as worker/llm/client.py's LlmSettings —
read once from the environment, fail loud and readable if something
required is missing, instead of a confusing error deep inside a request.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from jose import jwt
from passlib.context import CryptContext

from api.models.db import User

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEFAULT_JWT_EXPIRE_HOURS = 8
JWT_ALGORITHM = "HS256"


@dataclass(frozen=True)
class AuthSettings:
    """Everything token creation/verification needs, read once from the environment."""

    secret: str
    expire_hours: int = DEFAULT_JWT_EXPIRE_HOURS


def load_auth_settings() -> AuthSettings:
    """Build settings from environment variables.

    Raises when the secret is missing, so the failure happens at startup
    with a readable message instead of a confusing 500 on the first login.
    """
    secret = os.environ.get("JWT_SECRET", "").strip()
    if not secret:
        raise RuntimeError("JWT_SECRET is not set. Copy .env.example to .env and fill it in.")

    return AuthSettings(
        secret=secret,
        expire_hours=int(os.environ.get("JWT_EXPIRE_HOURS", DEFAULT_JWT_EXPIRE_HOURS)),
    )


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pwd_context.verify(password, hashed)


def create_access_token(user: User, *, settings: AuthSettings | None = None) -> str:
    """Encode a JWT for `user`. sub=email (unique, so it doubles as the
    lookup key in get_current_user), role is included as its own claim so
    require_role() never has to hit the DB just to check it.
    """
    settings = settings or load_auth_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user.email,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(hours=settings.expire_hours),
    }
    return jwt.encode(payload, settings.secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, *, settings: AuthSettings | None = None) -> dict:
    """Decode and verify a JWT.

    Raises jose.JWTError (expired, bad signature, malformed) on any failure —
    callers (api/dependencies.py) turn that into a 401, never a 500.
    """
    settings = settings or load_auth_settings()
    return jwt.decode(token, settings.secret, algorithms=[JWT_ALGORITHM])
