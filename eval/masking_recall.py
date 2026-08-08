# eval/masking_recall.py
"""Masking recall, measured against the real values rather than inferred.

data/ground_truth_enriched.jsonl carries a `_personal` block per record - the
name that went into the text, its source, the phone, the TC - and
`expected.plate` carries the plate. So recall needs no regex of its own and no
judgement call: mask the raw text, then look for the real value in the result. If
it is still there, it leaked.

CLAUDE.md §7 asks for >= 97% and scopes it to the deterministic layer ("regex +
sözlük deterministik"). That layer is what this measures - worker/masking/
pipeline.py's mask_all, regex then dictionary. The LLM sanity pass
(worker/masking/sanity.py) is a separate layer and a separate question.

The split that matters is `name_source`. The dictionary in
worker/masking/name_dict.py is built from the same Faker locale the corpus draws
its names from, so recall on `faker` names measures the dictionary against
itself. The `holdout` names (data/dictionaries/holdout_*.txt, 109 + 77, verified
disjoint from Faker and barred from the dictionary by a governance rule) are the
only honest generalisation number here. Reporting the two together would hide
exactly the thing worth knowing.

Free and offline: no model, no database, no API key.

    python -m eval.masking_recall
    python -m eval.masking_recall --pinned    # the baseline 100 only
"""

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from worker.masking.pipeline import mask_all

REPO_ROOT = Path(__file__).resolve().parents[1]
TEXTS_PATH = REPO_ROOT / "data" / "texts.jsonl"
GROUND_TRUTH_PATH = REPO_ROOT / "data" / "ground_truth_enriched.jsonl"
BASELINE_IDS_PATH = Path(__file__).resolve().parent / "fixtures" / "baseline_100_ids.json"


@dataclass
class Tally:
    """One PII kind: how often it was in the text, and how often it survived."""

    present: int = 0
    leaked: int = 0
    examples: list[tuple[str, str]] = field(default_factory=list)

    @property
    def masked(self) -> int:
        return self.present - self.leaked

    @property
    def recall(self) -> float | None:
        return self.masked / self.present if self.present else None

    def record(self, gt_id: str, value: str, *, leaked: bool) -> None:
        self.present += 1
        if leaked:
            self.leaked += 1
            if len(self.examples) < 5:
                self.examples.append((gt_id, value))


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def pii_items(record: dict, truth: dict) -> list[tuple[str, str]]:
    """(kind, real value) pairs to look for, keyed by how they are reported.

    Names are checked per word as well as whole: masking works word by word, so a
    surname surviving while the first name is masked is a real half-leak and
    would be invisible in a whole-string check.
    """
    personal = truth.get("_personal") or {}
    expected = truth.get("expected") or {}
    items: list[tuple[str, str]] = []

    for kind, value in (
        ("tc", personal.get("tc")),
        ("phone", personal.get("phone")),
        ("plate", expected.get("plate")),
    ):
        if value:
            items.append((kind, str(value)))

    name = personal.get("name")
    if name:
        source = personal.get("name_source", "unknown")
        parts = name.split()
        if parts:
            items.append((f"name_first[{source}]", parts[0]))
        if len(parts) > 1:
            items.append((f"name_last[{source}]", parts[-1]))
    return items


def measure(gt_ids: set[str] | None = None) -> tuple[dict[str, Tally], int]:
    texts = read_jsonl(TEXTS_PATH)
    truth = {row["gt_id"]: row for row in read_jsonl(GROUND_TRUTH_PATH)}
    tallies: dict[str, Tally] = defaultdict(Tally)
    scanned = 0

    for row in texts:
        gt_id = row["gt_id"]
        if gt_ids is not None and gt_id not in gt_ids:
            continue
        raw = row["text"]
        masked, _ = mask_all(raw)
        scanned += 1
        for kind, value in pii_items(row, truth.get(gt_id, {})):
            # Only PII the text actually contains can be missed; a value the
            # generator recorded but never wrote is not a masking failure.
            if value not in raw:
                continue
            tallies[kind].record(gt_id, value, leaked=value in masked)
    return dict(tallies), scanned


def format_report(tallies: dict[str, Tally], scanned: int) -> str:
    lines = [f"records scanned: {scanned}", ""]
    lines.append(f"  {'pii kind':<24} {'masked':>12}   recall")

    def show(kind: str) -> str:
        t = tallies[kind]
        rate = "     -" if t.recall is None else f"{t.recall:6.1%}"
        return f"  {kind:<24} {t.masked:>5}/{t.present:<6} {rate}"

    regex_kinds = [k for k in ("tc", "phone", "plate") if k in tallies]
    name_kinds = sorted(k for k in tallies if k.startswith("name_"))

    lines.append("  -- regex layer " + "-" * 32)
    for kind in regex_kinds:
        lines.append(show(kind))
    lines.append("  -- dictionary layer " + "-" * 27)
    for kind in name_kinds:
        lines.append(show(kind))

    # The two numbers §7 has to be read against: the deterministic layer overall,
    # and the same layer on names it has never seen.
    def combine(kinds: list[str]) -> tuple[int, int]:
        return (
            sum(tallies[k].masked for k in kinds),
            sum(tallies[k].present for k in kinds),
        )

    holdout = [k for k in name_kinds if "[holdout]" in k]
    faker = [k for k in name_kinds if "[faker]" in k]

    lines.append("")
    lines.append("=" * 60)
    for label, kinds in (
        ("regex PII (tc/phone/plate)", regex_kinds),
        ("names, faker (circular - dictionary's own source)", faker),
        ("names, holdout (unseen - the honest number)", holdout),
        ("everything, deterministic layer", regex_kinds + name_kinds),
    ):
        masked, present = combine(kinds)
        rate = f"{masked / present:6.1%}" if present else "     -"
        lines.append(f"  {label:<50} {masked:>5}/{present:<6} {rate}")

    leaks = [(k, t) for k, t in sorted(tallies.items()) if t.leaked]
    if leaks:
        lines.append("")
        lines.append("leak examples:")
        for kind, tally in leaks:
            shown = ", ".join(f"{gid}:{value}" for gid, value in tally.examples)
            lines.append(f"  {kind:<24} {tally.leaked:>4} leaked   {shown}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.masking_recall", description=__doc__)
    parser.add_argument(
        "--pinned",
        action="store_true",
        help="only the pinned baseline sample, for comparability with the other runs",
    )
    args = parser.parse_args(argv)

    gt_ids = None
    if args.pinned:
        gt_ids = set(json.loads(BASELINE_IDS_PATH.read_text(encoding="utf-8"))["gt_ids"])

    tallies, scanned = measure(gt_ids)
    print(format_report(tallies, scanned))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
