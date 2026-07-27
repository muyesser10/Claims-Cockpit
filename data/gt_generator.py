import json
import random
from pathlib import Path
from typing import Annotated

import typer


def build_one(index: int) -> dict:
    """Build a single synthetic ground truth record.

    NOTE: Field names are provisional. The real schema is frozen in the
    Day 2 schema session (schemas/claim.json). Update field names to match
    the frozen schema afterwards.
    """
    channels = ["email", "transcript", "form"]
    urgencies = ["critical", "high", "normal"]

    channel = random.choices(channels, weights=[0.50, 0.30, 0.20])[0]
    urgency = random.choices(urgencies, weights=[0.08, 0.30, 0.62])[0]

    return {
        "gt_id": f"GT-{index:06d}",
        "channel": channel,
        "urgency": urgency,
    }


def write_jsonl(records: list[dict], output: Path) -> None:
    """Write records to a JSONL file, one JSON object per line."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for record in records:
            line = json.dumps(record, ensure_ascii=False)
            f.write(line + "\n")


app = typer.Typer()


@app.command()
def generate(
    count: Annotated[int, typer.Option(help="Number of records to generate")] = 100,
    seed: Annotated[int, typer.Option(help="Random seed for reproducibility")] = 42,
    output: Annotated[Path, typer.Option(help="Output JSONL file path")] = Path(
        "data/ground_truth.jsonl"
    ),
):
    """Generate `count` synthetic ground truth records into `output`."""
    random.seed(seed)

    records = []
    for i in range(count):
        record = build_one(i)
        records.append(record)

    write_jsonl(records, output)
    typer.echo(f"Wrote {len(records)} records to {output}")


if __name__ == "__main__":
    app()
