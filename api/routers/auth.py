# api/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.database import get_db
from api.models.db import User
from api.models.schemas import LoginRequest, TokenResponse
from api.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Exchange email+password for a JWT. No registration endpoint exists on
    purpose — accounts are provisioned out of band, see scripts/create_user.py.
    """
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz e-posta veya şifre",
        )

    token = create_access_token(user)
    return TokenResponse(access_token=token, token_type="bearer")
