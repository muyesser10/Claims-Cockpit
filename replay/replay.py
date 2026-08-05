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


def load_scenario(path: Path) -> dict:
    """Load a scenario definition (phases with filters and timing) from YAML."""
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_records(texts_path: Path, enriched_path: Path) -> list[dict]:
    """Merge texts with their labels into one list for scenario filtering.

    Each record carries what a phase filter needs: the text/channel to post,
    plus damage_type and city from the enriched ground truth.
    """
    labels = {}
    for line in enriched_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        exp = rec["expected"]
        labels[rec["gt_id"]] = {
            "received_at": rec["received_at"],
            "damage_type": exp["damage_type"],
            "city": exp["incident_location"]["city"],
        }

    records = []
    for line in texts_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        t = json.loads(line)
        label = labels.get(t["gt_id"], {})
        records.append(
            {
                "gt_id": t["gt_id"],
                "channel": t["channel"],
                "text": t["text"],
                "received_at": label.get("received_at"),
                "damage_type": label.get("damage_type"),
                "city": label.get("city"),
            }
        )
    return records


def match_filter(record: dict, filt: dict) -> bool:
    """Check whether a record satisfies a phase filter.

    Supported keys: damage_type (must equal), city (must equal),
    exclude_damage_type (must NOT equal). Absent keys are ignored.
    """
    if "damage_type" in filt and record["damage_type"] != filt["damage_type"]:
        return False
    if "exclude_damage_type" in filt and record["damage_type"] == filt["exclude_damage_type"]:
        return False
    if "city" in filt and record["city"] != filt["city"]:
        return False
    return True


def run_scenario(
    scenario: dict,
    records: list[dict],
    api_url: str,
    dry_run: bool,
) -> int:
    """Run a scenario: for each phase, post matching records at its cadence.

    Phases run in order. Within a phase, up to `count` records matching the
    filter are posted, waiting `interval_seconds` between each — this is what
    creates the demo choreography (calm normal flow, then a rapid surge).
    """
    import time

    sent = 0
    used_ids = set()  # don't reuse a record across phases

    typer.echo(f"=== Senaryo: {scenario['name']} ===")
    for phase in scenario["phases"]:
        name = phase["name"]
        filt = phase.get("filter", {})
        count = phase["count"]
        interval = phase.get("interval_seconds", 0)

        matching = [r for r in records if r["gt_id"] not in used_ids and match_filter(r, filt)]
        selected = matching[:count]

        typer.echo(f"--- Faz: {name} ({len(selected)}/{count} kayıt) ---")
        for i, record in enumerate(selected):
            used_ids.add(record["gt_id"])
            payload = {
                "channel": record["channel"],
                "raw_text": record["text"],
                "external_ref": record["gt_id"],
                "received_at": record["received_at"],
            }
            if dry_run:
                typer.echo(
                    f"[dry-run] {name} | {record['gt_id']} "
                    f"| {record['damage_type']} | {record['city']}"
                )
            else:
                response = httpx.post(f"{api_url}/ingest", json=payload, timeout=10.0)
                response.raise_for_status()
                typer.echo(f"POSTed {record['gt_id']} ({name})")
            sent += 1
            # Wait between records (skip after the last one in a phase).
            if interval and i < len(selected) - 1:
                time.sleep(interval)

    typer.echo(f"Bitti. {sent} kayıt {'önizlendi' if dry_run else 'gönderildi'}.")
    return sent


app = typer.Typer()


@app.command()
def replay(
    texts: Annotated[Path, typer.Option(help="Texts JSONL to replay")] = Path("data/texts.jsonl"),
    enriched: Annotated[Path, typer.Option(help="Enriched ground truth JSONL")] = Path(
        "data/ground_truth_enriched.jsonl"
    ),
    api_url: Annotated[str, typer.Option(help="Base API URL")] = "http://localhost:8000",
    dry_run: Annotated[bool, typer.Option(help="Preview without sending")] = False,
    scenario: Annotated[
        Path | None, typer.Option(help="Scenario YAML for choreographed replay")
    ] = None,
):
    """Post each record to /ingest (or preview with --dry-run).

    With --scenario, run a choreographed scenario instead of a flat replay.
    """
    # Scenario mode: choreographed replay from a YAML definition.
    if scenario is not None:
        scenario_def = load_scenario(scenario)
        records = load_records(texts, enriched)
        run_scenario(scenario_def, records, api_url, dry_run)
        return

    received_map = load_received_map(enriched)
    sent = 0
    for line in texts.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        payload = {
            "channel": record["channel"],
            "raw_text": record["text"],
            "external_ref": record["gt_id"],
            "received_at": received_map.get(record["gt_id"]),
        }
        if dry_run:
            typer.echo(f"[dry-run] {record['gt_id']} | received_at={payload['received_at']}")
            sent += 1
            continue
        response = httpx.post(f"{api_url}/ingest", json=payload, timeout=10.0)
        response.raise_for_status()
        typer.echo(f"POSTed {record['gt_id']} -> {response.json()}")
        sent += 1
    typer.echo(f"Done. {sent} records {'previewed' if dry_run else 'sent'}.")


if __name__ == "__main__":
    app()
