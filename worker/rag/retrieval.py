# worker/rag/retrieval.py
"""Vector search over claim text, and the snippet each hit is shown with.

Design doc §7.2. This module owns the retrieval half of /soru: it turns a
Turkish question into an ordered list of claims, each carrying the sentence
that earned it its place.

It holds a Session because the search happens in Postgres - pgvector orders the
rows, not Python. What it does not do is decide whether a question belongs on
this path at all; that is the router's job.
"""

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.db import Claim, ClaimEmbedding, RawMessage
from worker.embedding.encoder import Encoder
from worker.embedding.store import get_encoder
from worker.parser.sentence_splitter import split as split_sentences

DEFAULT_LIMIT = 5

# Used when a claim's text yields no sentences at all - a fragment with no
# terminator, which the splitter returns as one piece or not at all.
SNIPPET_FALLBACK_CHARS = 200


class RetrievedClaim(BaseModel):
    """One source chip in a /soru answer.

    This shape is a contract with the frontend (agreed with @nursenakyga before
    the endpoint existed, so the Soru screen could be built against a mock).
    Changing a field name here changes that screen.
    """

    claim_id: int
    external_ref: str | None
    snippet: str
    score: float
    urgency: str | None
    incident_date: str | None


def search(
    db: Session,
    question: str,
    *,
    limit: int = DEFAULT_LIMIT,
    urgency: str | None = None,
    status: str | None = None,
    encoder: Encoder | None = None,
) -> list[RetrievedClaim]:
    """The claims closest to `question`, nearest first.

    `urgency` and `status` narrow the search before ranking. Nothing calls them
    yet - the router will, for questions like "kritik ihbarlarda neler
    anlatılıyor". They filter rather than re-rank on purpose: a question that
    says "kritik" is stating a fact about what it wants, not a preference.

    No score threshold, deliberately. ADR-002 measured true-pair and impostor
    cosine ranges overlapping for both candidate models and concluded that
    anything built on it should rank, not threshold. A cutoff here would drop
    correct answers on some questions and let noise through on others, with no
    way to tell which from the outside.
    """
    encoder = encoder or get_encoder()
    question_vector = encoder.embed_query(question)

    distance = ClaimEmbedding.embedding.cosine_distance(question_vector).label("distance")
    stmt = (
        select(Claim, RawMessage.external_ref, distance)
        .join(ClaimEmbedding, ClaimEmbedding.claim_id == Claim.id)
        .join(RawMessage, RawMessage.id == Claim.raw_message_id)
        .order_by(distance)
        .limit(limit)
    )
    if urgency is not None:
        stmt = stmt.where(Claim.urgency == urgency)
    if status is not None:
        stmt = stmt.where(Claim.status == status)

    rows = db.execute(stmt).all()
    if not rows:
        return []

    texts = [(claim.data or {}).get("masked_text", "") for claim, _, _ in rows]
    snippets = pick_snippets(question_vector, texts, encoder)

    results = []
    for (claim, external_ref, dist), snippet in zip(rows, snippets, strict=True):
        extraction = (claim.data or {}).get("extraction") or {}
        results.append(
            RetrievedClaim(
                claim_id=claim.id,
                external_ref=external_ref,
                snippet=snippet,
                # cosine_distance is 0 for identical, 2 for opposite; the
                # frontend shows a similarity, so it is inverted here rather
                # than in five places downstream.
                score=round(1.0 - float(dist), 4),
                urgency=claim.urgency,
                incident_date=extraction.get("incident_date"),
            )
        )
    return results


def pick_snippets(
    question_vector: list[float],
    texts: list[str],
    encoder: Encoder,
) -> list[str]:
    """For each text, the sentence closest to the question.

    Every sentence of every hit is embedded in one batch rather than per text.
    The encoder batches internally (batch_size=64), and a call per claim would
    pay the fixed cost five times for no reason.

    Sentences go in as passages, not queries: this is the same asymmetric
    comparison as the search itself - a question against claim text - and e5's
    markers are not interchangeable (ADR-002).
    """
    per_text = [split_sentences(text) or ([text] if text else []) for text in texts]
    flat = [sentence for sentences in per_text for sentence in sentences]
    if not flat:
        return [text[:SNIPPET_FALLBACK_CHARS] for text in texts]

    vectors = encoder.embed_passages(flat)

    snippets = []
    offset = 0
    for text, sentences in zip(texts, per_text, strict=True):
        if not sentences:
            snippets.append(text[:SNIPPET_FALLBACK_CHARS])
            continue
        chunk = vectors[offset : offset + len(sentences)]
        offset += len(sentences)
        # Both sides are normalized, so a dot product is the cosine similarity.
        best = max(range(len(chunk)), key=lambda i: _dot(question_vector, chunk[i]))
        snippets.append(sentences[best])
    return snippets


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))
