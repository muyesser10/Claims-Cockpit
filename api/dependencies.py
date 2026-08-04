# api/dependencies.py
"""FastAPI auth dependencies shared across routers (S3-8)."""

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from api.database import get_db
from api.models.db import User
from api.security import decode_access_token

# tokenUrl only documents where OpenAPI's "Authorize" button should ask for
# a token from — the actual issuing endpoint is api/routers/auth.py's login.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Decode the bearer token and load the User it names.

    A missing/invalid/expired token, or a token naming a user that no
    longer exists, is a 401 either way — the caller learns "you are not
    authenticated", not which specific reason applied.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise credentials_error from None

    email = payload.get("sub")
    if email is None:
        raise credentials_error

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_error
    return user


def require_role(*roles: str) -> Callable[..., User]:
    """Dependency factory: 403s unless the current user's role is in `roles`.

    Usage: Depends(require_role("operator", "admin")).
    """

    def _check_role(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bu işlem için yetkiniz yok",
            )
        return user

    return _check_role
