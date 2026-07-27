# api/database.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

DATABASE_URL = os.environ["DATABASE_URL"].replace(
    "postgresql://", "postgresql+psycopg://"
)

# Synchronous engine (psycopg v3). Not async.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI dependency: one DB session per request."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()