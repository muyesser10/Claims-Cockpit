# scripts/backfill_embeddings.py
"""Embed claims that have no vector yet (ADR-003).

step_embed only runs for messages that arrive after it ships. Everything already
in the database stays invisible to RAG retrieval until this has been run once:

    python -m scripts.backfill_embeddings
    python -m scripts.backfill_embeddings --dry-run
    python -m scripts.backfill_embeddings --force     # re-embed everything

--force exists for a model change. ADR-002 says switching the encoder costs one
config line; it also costs a full re-embed, because vectors from two models are
not comparable and pgvector will rank them against each other regardless.

Claims flagged by masking sanity are skipped here for the same reason
step_embed skips them: one rule, applied the same way in both places. Without
that, this script would quietly fill in exactly what the pipeline refused.
"""

from typing import Annotated

import typer
from sqlalchemy import select

from api.database import SessionLocal
from api.models.db import Claim, ClaimEmbedding
from worker.embedding.store import get_encoder, store_embedding

app = typer.Typer()

# Commit in batches: a crash halfway through should not throw away the work
# already done, and holding a thousand vectors in one transaction buys nothing.
COMMIT_EVERY = 50


@app.command()
def backfill(
    dry_run: Annotated[
        bool, typer.Option(help="Report what would be embedded, write nothing")
    ] = False,
    force: Annotated[bool, typer.Option(help="Re-embed claims that already have a vector")] = False,
    limit: Annotated[int | None, typer.Option(help="Stop after this many claims")] = None,
) -> None:
    db = SessionLocal()
    try:
        stmt = select(Claim).order_by(Claim.id)
        if not force:
            stmt = stmt.outerjoin(ClaimEmbedding).where(ClaimEmbedding.claim_id.is_(None))
        if limit is not None:
            stmt = stmt.limit(limit)
        claims = db.execute(stmt).scalars().all()

        typer.echo(f"{len(claims)} claims to embed" + (" (dry run)" if dry_run else ""))
        if dry_run or not claims:
            return

        # Load the model once, before the loop - not per claim.
        encoder = get_encoder()
        embedded = skipped = failed = 0

        for i, claim in enumerate(claims, start=1):
            data = claim.data or {}
            if data.get("masking_sanity_flags"):
                skipped += 1
                continue
            text = data.get("masked_text")
            if not text:
                typer.echo(f"  claim {claim.id}: no masked_text, skipping")
                skipped += 1
                continue
            try:
                store_embedding(db, claim.id, text, encoder=encoder)
                embedded += 1
            except Exception as exc:
                typer.echo(f"  claim {claim.id}: FAILED - {exc}")
                failed += 1

            if i % COMMIT_EVERY == 0:
                db.commit()
                typer.echo(f"  ... {i}/{len(claims)}")

        db.commit()
        typer.echo(f"done: {embedded} embedded, {skipped} skipped, {failed} failed")
    finally:
        db.close()


if __name__ == "__main__":
    app()
