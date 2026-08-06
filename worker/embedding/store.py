# worker/embedding/store.py
"""Writes claim vectors into claim_embeddings.

The encoder knows nothing about the database and the pipeline knows nothing
about e5's prefixes. This module is the seam: it is the only place that holds
both a Session and an Encoder.

The model is loaded once per process. Loading costs about a second and a 470 MB
download, so a worker that built an Encoder per message would spend its life
doing that and nothing else.
"""

import time

from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.models.db import ClaimEmbedding
from worker.embedding.encoder import Encoder, resolve_model_name

_encoder: Encoder | None = None


def get_encoder() -> Encoder:
    """The process-wide encoder, built on first use.

    Deliberately lazy rather than a module-level constant: importing this module
    must stay free. Tests, the backfill script and anything that only needs
    store_embedding's signature should not pay for a model load.
    """
    global _encoder
    if _encoder is None:
        _encoder = Encoder()
    return _encoder


class EmbeddingResult(BaseModel):
    """What the audit trail records about one embedding."""

    dimensions: int
    text_length: int
    model: str
    duration_ms: int


def store_embedding(
    db: Session,
    claim_id: int,
    text: str,
    *,
    encoder: Encoder | None = None,
) -> EmbeddingResult:
    """Embed `text` and write the vector against `claim_id`.

    `text` is claim text being searched *through*, so it goes in as a passage -
    embed_passages applies e5's marker. A question searching *with* uses
    embed_query; mixing the two silently degrades retrieval (ADR-002).

    Replaces an existing row rather than failing: claim_id is the primary key of
    claim_embeddings, and a message reprocessed after a fix must not collide
    with its own earlier vector.

    `encoder` is injectable so tests can pass a stub and never load the model.
    """
    if not text or not text.strip():
        raise ValueError(f"claim_id={claim_id}: refusing to embed empty text")

    encoder = encoder or get_encoder()
    started = time.perf_counter()
    vector = encoder.embed_passages([text])[0]
    duration_ms = round((time.perf_counter() - started) * 1000)

    row = db.get(ClaimEmbedding, claim_id)
    if row is None:
        db.add(ClaimEmbedding(claim_id=claim_id, embedding=vector))
    else:
        row.embedding = vector

    return EmbeddingResult(
        dimensions=len(vector),
        text_length=len(text),
        model=resolve_model_name(),
        duration_ms=duration_ms,
    )
