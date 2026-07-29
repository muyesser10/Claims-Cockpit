"""
replay.py — Feed generated emails into the /ingest endpoint.

Reads emails.jsonl and posts each email to the API as if real claims were
arriving. Pairs each email with its received_at from the enriched ground
truth (needed for relative-date resolution). Supports --dry-run to preview
without a running API.

Usage:
    python replay/replay.py --dry-run
    python replay/replay.py --api-url http://localhost:8000
"""

import json
from pathlib import Path
from typing import Annotated

import httpx
import typer


def load_received_map(enriched_path: Path) -> dict[str, str]:
    """Build a gt_id -> received_at map from the enriched ground truth.

    emails.jsonl has no received_at; it lives in the enriched ground truth.
    replay pairs the two by gt_id so each POST carries the fixed timestamp
    needed for relative-date resolution downstream.
    """
    received_map = {}
    for line in enriched_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        received_map[record["gt_id"]] = record["received_at"]
    return received_map


app = typer.Typer()


@app.command()
def replay(
    emails: Annotated[Path, typer.Option(help="Emails JSONL to replay")] = Path(
        "data/emails.jsonl"
    ),
    enriched: Annotated[Path, typer.Option(help="Enriched ground truth JSONL")] = Path(
        "data/ground_truth_enriched.jsonl"
    ),
    api_url: Annotated[str, typer.Option(help="Base API URL")] = "http://localhost:8000",
    dry_run: Annotated[bool, typer.Option(help="Preview without sending")] = False,
):
    """Post each email to /ingest (or preview with --dry-run)."""
    received_map = load_received_map(enriched)

    sent = 0
    for line in emails.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        email = json.loads(line)

        payload = {
            "channel": email["channel"],
            "raw_text": email["text"],
            "external_ref": email["gt_id"],
            "received_at": received_map.get(email["gt_id"]),
        }

        if dry_run:
            typer.echo(f"[dry-run] {email['gt_id']} | received_at={payload['received_at']}")
            sent += 1
            continue

        response = httpx.post(f"{api_url}/ingest", json=payload, timeout=10.0)
        response.raise_for_status()
        typer.echo(f"POSTed {email['gt_id']} -> {response.json()}")
        sent += 1

    typer.echo(f"Done. {sent} emails {'previewed' if dry_run else 'sent'}.")


if __name__ == "__main__":
    app()
