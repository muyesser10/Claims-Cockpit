# rag/readonly.py
"""The second database connection: the one generated SQL runs on.

api/database.py's session stays exactly where it was — auth reads `users`,
retrieval reads `claims`/`claim_embeddings`/`raw_messages`, and ask() writes the
audit row with it. Only worker/rag/sql_answer.py's run_query uses this one, and
it connects as `rag_readonly`: SELECT on claims_flat and audit_trail, nothing
else (migrations/init/01-create-readonly-role.sh).

That split is the whole point. worker/rag/sql_guard.py already refuses anything
that is not a bounded SELECT over ALLOWED_TABLES, but a parser can be wrong
about a dialect corner and a role holding no other privilege cannot be. The two
agree on the same table list deliberately: if one of them is bypassed, the other
still holds. In particular the raw `claims` table - whose `data` column carries
the *unmasked* extraction - is unreachable on this connection.
"""

import os

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

log = structlog.get_logger(__name__)

_readonly_url = os.environ.get("RAG_READONLY_DATABASE_URL")

if not _readonly_url:
    # Loud, not silent. Falling back keeps a developer without the role running,
    # but losing the isolation must never be something that happens quietly
    # because a variable was forgotten.
    log.warning(
        "rag_readonly_url_not_set",
        message=(
            "RAG_READONLY_DATABASE_URL not set, falling back to DATABASE_URL — "
            "read isolation is NOT enforced"
        ),
    )
    _readonly_url = os.environ["DATABASE_URL"]

# Same rewrite as api/database.py: psycopg v3, synchronous.
READONLY_DATABASE_URL = _readonly_url.replace("postgresql://", "postgresql+psycopg://")

engine = create_engine(READONLY_DATABASE_URL, pool_pre_ping=True)
ReadOnlySessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_readonly_db():
    """FastAPI dependency: one read-only session per request."""
    db: Session = ReadOnlySessionLocal()
    try:
        yield db
    finally:
        db.close()
