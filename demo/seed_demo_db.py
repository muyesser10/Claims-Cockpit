# demo/seed_demo_db.py
"""Seed the demo database: the exact dataset the offline demo is built on.

Posts the first N records of data/texts.jsonl to /ingest and waits for the
worker to finish with them, then reports what actually landed.

WHY THE COUNT MATTERS
---------------------
demo/fixtures/demo_rag.jsonl carries recorded /soru answers whose numbers were
measured against **the first 60 records of data/texts.jsonl** and nothing else:
5 critical, 9 hail, İzmir 14 / Ankara 11 / Antalya 11 / İstanbul 10 / Bursa 8.
Those sentences are not trusted at runtime - worker/rag/sql_answer.py checks
every number in them against the rows the query actually returned. So a
different subset does not produce a wrong answer, it produces *no* answer: the
number check withholds the sentence and the operator sees a refusal. Safe, but
it empties the SQL half of the demo. Change --limit only if you also rebuild
the RAG fixtures (demo/fixtures/build_rag_fixtures.py) against the new data.

PREREQUISITES (this script starts nothing itself, on purpose)
-------------------------------------------------------------
    docker compose up -d --build          # db, redis, api, worker
    docker compose exec api alembic upgrade head
    DEMO_OFFLINE=true python -m demo.seed_demo_db

Runs on the **host**, not inside a container, for the same reason replay.py
does: .dockerignore excludes data/*.jsonl from the build context ("read by eval
and replay on the host, never inside a container"), so the corpora this script
reads are not in the worker or api image at all. It therefore needs the host's
Python environment (requirements.txt) and host-reachable addresses - the
defaults below assume compose's published ports.

DATABASE_URL is read from the environment, as everywhere else. The value in
.env points at `db:5432`, which only resolves inside the compose network, so
from the host pass a published one:

    DEMO_OFFLINE=true \
    DATABASE_URL=postgresql://claims:<parola>@localhost:5432/claims_cockpit \
    python -m demo.seed_demo_db

DEMO_OFFLINE
------------
Refuses to run unless DEMO_OFFLINE is on. Seeding 60 records with it off means
180 live OpenAI calls (three per message) and a bill, which is not something to
discover afterwards.

The check reads *this process's* environment, and the pipeline runs in the
worker container - so the two can disagree. The worker's setting is the one
that decides where extraction actually comes from:

    docker compose exec worker env | grep DEMO_OFFLINE

The guard here is a tripwire against the expensive mistake, not proof of what
the worker is doing.
"""

import json
import time
from pathlib import Path
from typing import Annotated

import httpx
import typer
from sqlalchemy import func, select

from api.database import SessionLocal
from api.models.db import Claim, ClaimEmbedding, RawMessage
from worker.llm.client import is_demo_offline

app = typer.Typer()

DEFAULT_LIMIT = 60

# raw_messages statuses a message can no longer move out of: the pipeline
# either finished it (classified is the last status step_classify sets) or gave
# up on it (dead_letter). Anything else means the worker is still working.
TERMINAL_STATUSES = ("classified", "dead_letter")


def load_received_map(enriched: Path) -> dict[str, str]:
    """gt_id -> received_at, from the enriched ground truth.

    The same mapping replay/replay.py builds, and read the same way. Not
    imported from there: `replay` is both a package and a `replay.py` inside
    it, so `import replay` resolves to one or the other depending on what is
    already on sys.path - which is fine when the script runs from /app and
    broken under pytest, whose prepend import mode puts `replay/` on the path
    while collecting that package's own tests. Six lines of JSON reading is a
    cheaper price than an import that works in one context and not the other.
    (A `replay/__init__.py` would settle it properly, but that tree belongs to
    the data engineer - CLAUDE.md §3.)
    """
    received_map = {}
    for line in enriched.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        received_map[record["gt_id"]] = record["received_at"]
    return received_map


def load_first(texts: Path, enriched: Path, limit: int) -> list[dict]:
    """The first `limit` records, in the payload shape /ingest expects.

    received_at is paired in from the enriched ground truth: the pipeline
    resolves relative dates ("dün") against it, so a missing timestamp changes
    what gets extracted.
    """
    received_map = load_received_map(enriched)

    records = []
    for line in texts.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        records.append(
            {
                "channel": record["channel"],
                "raw_text": record["text"],
                "external_ref": record["gt_id"],
                "received_at": received_map.get(record["gt_id"]),
            }
        )
        if len(records) >= limit:
            break
    return records


def _status_counts(db, refs: list[str]) -> dict[str, int]:
    """How the seeded messages are spread across raw_messages.status."""
    # Each poll starts a new transaction, or a long-running one would keep
    # showing the snapshot it opened with.
    db.rollback()
    rows = db.execute(
        select(RawMessage.status, func.count())
        .where(RawMessage.external_ref.in_(refs))
        .group_by(RawMessage.status)
    ).all()
    return {status: count for status, count in rows}


def wait_for_worker(refs: list[str], timeout: float, poll_interval: float) -> dict[str, int]:
    """Poll until every seeded message reaches a terminal status, or give up.

    Giving up is not an error: a message stuck in the queue is worth reporting
    and looking at, but it is not a reason to fail a seeding run that may have
    processed 59 of 60.
    """
    deadline = time.monotonic() + timeout
    db = SessionLocal()
    try:
        while True:
            counts = _status_counts(db, refs)
            done = sum(counts.get(status, 0) for status in TERMINAL_STATUSES)
            if done >= len(refs):
                return counts
            if time.monotonic() >= deadline:
                typer.echo(
                    f"UYARI: {timeout:.0f} sn içinde {done}/{len(refs)} kayıt tamamlandı. "
                    "Worker hâlâ çalışıyor olabilir; `docker compose logs -f worker` ile bakın."
                )
                return counts
            typer.echo(f"  bekleniyor... {done}/{len(refs)}")
            time.sleep(poll_interval)
    finally:
        db.close()


def verify(refs: list[str]) -> tuple[int, int]:
    """Claims and embeddings that belong to the seeded messages."""
    db = SessionLocal()
    try:
        claims = db.execute(
            select(func.count())
            .select_from(Claim)
            .join(RawMessage, RawMessage.id == Claim.raw_message_id)
            .where(RawMessage.external_ref.in_(refs))
        ).scalar_one()
        embeddings = db.execute(
            select(func.count())
            .select_from(ClaimEmbedding)
            .join(Claim, Claim.id == ClaimEmbedding.claim_id)
            .join(RawMessage, RawMessage.id == Claim.raw_message_id)
            .where(RawMessage.external_ref.in_(refs))
        ).scalar_one()
        return claims, embeddings
    finally:
        db.close()


@app.command()
def seed(
    texts: Annotated[Path, typer.Option(help="Texts JSONL to seed from")] = Path(
        "data/texts.jsonl"
    ),
    enriched: Annotated[Path, typer.Option(help="Enriched ground truth JSONL")] = Path(
        "data/ground_truth_enriched.jsonl"
    ),
    api_url: Annotated[str, typer.Option(help="Base API URL")] = "http://localhost:8000",
    limit: Annotated[int, typer.Option(help="How many records to seed")] = DEFAULT_LIMIT,
    wait_timeout: Annotated[
        float, typer.Option(help="Seconds to wait for the worker to drain")
    ] = 120.0,
    poll_interval: Annotated[float, typer.Option(help="Seconds between progress polls")] = 2.0,
):
    """Seed the demo database and report what the pipeline made of it."""
    if not is_demo_offline():
        raise typer.BadParameter(
            "DEMO_OFFLINE is not on. Seeding with it off makes three live OpenAI calls per "
            f"message ({limit} messages = {limit * 3} calls) and costs money. Set "
            "DEMO_OFFLINE=true in .env, restart the worker, and run this again.",
            param_hint="DEMO_OFFLINE",
        )

    records = load_first(texts, enriched, limit)
    if not records:
        raise typer.BadParameter(f"no records read from {texts}", param_hint="--texts")

    refs = [record["external_ref"] for record in records]
    typer.echo(f"=== {len(records)} kayıt {api_url}/ingest adresine gönderiliyor ===")

    for number, payload in enumerate(records, start=1):
        response = httpx.post(f"{api_url}/ingest", json=payload, timeout=10.0)
        response.raise_for_status()
        if number % 20 == 0:
            typer.echo(f"  {number}/{len(records)} gönderildi")

    typer.echo("=== worker bekleniyor ===")
    counts = wait_for_worker(refs, wait_timeout, poll_interval)

    claims, embeddings = verify(refs)
    typer.echo("=== sonuç ===")
    for status, count in sorted(counts.items()):
        typer.echo(f"  raw_messages.status={status}: {count}")
    typer.echo(f"  claims:           {claims}")
    typer.echo(f"  claim_embeddings: {embeddings}")

    if claims == len(records) and embeddings == claims:
        typer.echo("Demo veritabanı hazır.")
    else:
        typer.echo(
            "UYARI: beklenen sayıya ulaşılmadı. Eksik embedding RAG'in retrieval yolunu, "
            "eksik claim ise Pano/Kuyruk sayılarını etkiler."
        )


if __name__ == "__main__":
    app()
