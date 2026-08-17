# eval/report.py
"""The CLAUDE.md §7 quality table, as one machine-readable file.

§7 lists eight targets. Seven are measured, each by a different module, over a
different sample, on a different day - and until now the only place they existed
together was a paragraph someone retyped by hand. This builds that table from
the runs themselves, so every number on the Metrikler screen can be traced back
to the file that produced it.

Every row carries its own provenance: sample size, source run, measurement date.
Deliberately per row and not once at the top - a single date would claim the
eight numbers were measured together, and they were not.

The output is committed. eval/results/ is gitignored, eval/reports/ is not: the
screen reads a reviewed snapshot, never whatever happens to sit on one laptop.

Free and offline. Every input is an existing run; nothing here calls a model.

    python -m eval.report
    python -m eval.report --out eval/reports/quality_report.json
"""

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from eval import classification, gate, metrics, runner

SCHEMA_VERSION = 1

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "eval" / "results"
REPORTS_DIR = REPO_ROOT / "eval" / "reports"

DEFAULT_EXTRACTION = RESULTS_DIR / "run_masked_baseline.json"
DEFAULT_GATE = RESULTS_DIR / "gate_post62.json"
DEFAULT_INJURY = RESULTS_DIR / "injury_recall.json"
DEFAULT_MASKING = RESULTS_DIR / "masking_recall.json"
DEFAULT_RAG = RESULTS_DIR / "rag.json"
DEFAULT_MANUAL = REPORTS_DIR / "manual_inputs.json"
DEFAULT_OUT = REPORTS_DIR / "quality_report.json"

# Display names for the breakdown rows. The source modules name their groups for
# a terminal reader in English; the screen these end up on is Turkish, and the
# naming belongs on this side so the UI can stay a dumb renderer.
CHANNEL_LABELS = {
    "email": "E-posta",
    "call_transcript": "Çağrı transkripti",
    "web_form": "Web formu",
}
URGENCY_LABELS = {"critical": "Kritik", "high": "Yüksek", "normal": "Normal"}
MASKING_GROUP_LABELS = {
    "regex": "Regex katmanı (TC / telefon / plaka)",
    "names_faker": "İsimler — sözlüğün kendi kaynağından (dairesel ölçüm)",
    "names_holdout": "İsimler — sözlük dışı (dürüst sayı)",
}
INJURY_GROUP_LABELS = {
    "non_canonical": "kanonik olmayan ifadeler",
    "ascii_fold": "Türkçe karakteri düşmüş ifadeler",
}
SPLIT_LABELS = {
    "holdout": "dokunulmamış vakalar (dürüst sayı)",
    "tune": "ayarlama yapılan vakalar",
}


@dataclass(frozen=True)
class Sample:
    """What the number was measured over. `n` is None when nothing was measured."""

    n: int | None
    unit: str
    description: str


@dataclass(frozen=True)
class Source:
    """Where the number came from, precise enough to re-derive it."""

    run: str
    measured_at: str | None
    model: str | None = None


@dataclass(frozen=True)
class Breakdown:
    """One component of a headline number.

    Two metrics need this for different reasons and get the same shape: masking
    recall splits by layer, critical recall by how the phrasing was written.
    """

    label: str
    value: float | None
    numerator: int | None = None
    denominator: int | None = None


@dataclass(frozen=True)
class Metric:
    """One §7 row."""

    key: str
    label: str
    value: float | None
    unit: str  # "ratio" or "seconds"
    target: float
    target_operator: str  # "gte" or "lte"
    sample: Sample
    source: Source | None = None
    numerator: int | None = None
    denominator: int | None = None
    breakdown: list[Breakdown] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        """pass / fail / unmeasured, computed and never hand-set.

        No "warn" tier on purpose. An intermediate grade would mean choosing,
        by hand and per metric, which number counts as close enough - and that
        judgement belongs in `notes`, where a reader can see it and disagree,
        not in a field that silently softens a miss.
        """
        if self.value is None:
            return "unmeasured"
        if self.target_operator == "gte":
            return "pass" if self.value >= self.target else "fail"
        return "pass" if self.value <= self.target else "fail"


def _pct(value: float | None, digits: int = 1) -> str:
    """Turkish-style percentage for the note text: sign first, comma decimal.

    The JSON carries raw ratios and the screen formats them, but `notes` are
    prose written here, and prose in a Turkish table reads %3,8 - not 3.8%.
    """
    if value is None:
        return "—"
    return f"%{value * 100:.{digits}f}".replace(".", ",")


def binomial_lower_bound(hits: int, total: int, *, alpha: float = 0.05) -> float | None:
    """One-sided Clopper-Pearson lower confidence bound for a proportion.

    Written out rather than imported: this is the only place in the repo that
    needs it, and eval otherwise runs without a scientific stack.

    It answers the question a precision target actually asks. "68 of 70 were
    right" is 97.1%, but the sample is small enough that the true rate could be
    well under the 95% §7 wants; this is how far under, at 95% confidence.
    """
    if total <= 0 or not 0 <= hits <= total:
        return None
    if hits == total:
        return alpha ** (1 / total)
    low, high = 0.0, hits / total
    for _ in range(200):
        mid = (low + high) / 2
        tail = sum(
            math.comb(total, i) * mid**i * (1 - mid) ** (total - i) for i in range(hits, total + 1)
        )
        if tail > alpha:
            high = mid
        else:
            low = mid
    return low


def _read_meta(path: Path) -> dict:
    """A run's meta block, or empty when the file is a bare list of records."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw.get("meta", {}) if isinstance(raw, dict) else {}


def _measured_at(meta: dict) -> str | None:
    """The date part of a run's timestamp. The clock time is noise here."""
    run_at = meta.get("run_at")
    return run_at[:10] if isinstance(run_at, str) and len(run_at) >= 10 else None


def extraction_metrics(path: Path) -> list[Metric]:
    """Required-field accuracy and hallucination rate, from one scored run."""
    meta = _read_meta(path)
    report = metrics.build_report(runner.read_results(path))
    source = Source(run=path.name, measured_at=_measured_at(meta), model=meta.get("model"))
    sample = Sample(n=report.records, unit="ihbar", description="sabitlenmiş baseline örneklemi")

    return [
        Metric(
            key="field_accuracy",
            label="Zorunlu alan doğruluğu",
            value=report.field_accuracy.rate,
            unit="ratio",
            numerator=report.field_accuracy.hits,
            denominator=report.field_accuracy.total,
            target=0.82,
            target_operator="gte",
            sample=sample,
            source=source,
            breakdown=[
                Breakdown(
                    label=CHANNEL_LABELS.get(channel, channel),
                    value=ratio.rate,
                    numerator=ratio.hits,
                    denominator=ratio.total,
                )
                for channel, ratio in report.per_channel.items()
            ],
            notes=[
                f"Gürültü tabanı ±{_pct(report.noise_floor, 2)} — iki özdeş koşu arasında bu kadar "
                "alan oynadı. Tek tekrarla ölçüldü, yani taban; sınır değil.",
            ],
        ),
        Metric(
            key="hallucination_rate",
            label="Halüsinasyon oranı",
            value=report.unsupported.rate,
            unit="ratio",
            numerator=report.unsupported.hits,
            denominator=report.unsupported.total,
            target=0.07,
            target_operator="lte",
            sample=sample,
            source=source,
            notes=[
                "Modelin doldurduğu alanlardan, verdiği kaynak alıntısı ham metinde "
                "bulunamayanların oranı.",
            ],
        ),
    ]


def gate_metrics(path: Path) -> list[Metric]:
    """Urgency macro-F1 and auto-approval precision, from one gate run."""
    meta = _read_meta(path)
    records = gate.read_run(path)
    source = Source(run=path.name, measured_at=_measured_at(meta), model=meta.get("model"))
    sample = Sample(n=len(records), unit="ihbar", description="sabitlenmiş baseline örneklemi")

    urgency = classification.build_report(records, "urgency")
    shipped = gate.measure(records)
    bound = binomial_lower_bound(shipped.correct, shipped.approved)

    precision_notes = [
        f"Kapsam {_pct(shipped.coverage)} — {shipped.approved}/{shipped.total} ihbar "
        "kapıdan geçti.",
    ]
    if bound is not None:
        precision_notes.append(
            f"Tek taraflı %95 güven alt sınırı {_pct(bound)}. Örneklem bu genişlikte olduğu "
            "sürece hedefin sağlandığı istatistiksel olarak gösterilemez, sadece ölçülür."
        )
    if shipped.wrong_ids:
        precision_notes.append(
            "Yanlış onaylananlar: "
            + ", ".join(shipped.wrong_ids)
            + ". Bunlardan counterparty_exists kaynaklı olanlar bilinen ground truth "
            "kusurudur (data/gt_generator.py etiketi metinden türetmiyor), gerçek model "
            "hatası değildir."
        )

    return [
        Metric(
            key="classification_f1",
            label="Sınıflandırma macro-F1 (aciliyet)",
            value=urgency.macro_f1,
            unit="ratio",
            target=0.85,
            target_operator="gte",
            sample=Sample(n=urgency.scored, unit="ihbar", description=sample.description),
            source=source,
            breakdown=[
                Breakdown(
                    label=URGENCY_LABELS.get(item.label, item.label),
                    value=item.f1,
                    numerator=item.true_positives,
                    denominator=item.support,
                )
                for item in urgency.classes
            ],
            notes=[
                "Aciliyet alanı üzerinden. Sınıf başına eşit ağırlıklı ortalama, yani az "
                "örnekli kritik sınıfı çoğunluk gizlemiyor.",
            ],
        ),
        Metric(
            key="auto_approve_precision",
            label="Otomatik onay precision",
            value=shipped.precision,
            unit="ratio",
            numerator=shipped.correct,
            denominator=shipped.approved,
            target=0.95,
            target_operator="gte",
            sample=sample,
            source=source,
            notes=precision_notes,
        ),
    ]


def critical_recall_metric(path: Path, *, measured_at: str | None = None) -> Metric:
    """Critical-urgency recall over phrasings the corpus does not contain.

    The headline is the hard number, not the corpus one. Measured over the
    corpus this metric reads 100%, but every critical record there carries one
    of four fixed phrases and all four contain a canonical injury term, so that
    100% describes a template rather than the system's reach. Putting it in the
    headline slot would be a false reassurance about the one §7 metric whose
    failure mode is a missed injury.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    outcomes = raw["outcomes"] if isinstance(raw, dict) else raw
    meta = raw.get("meta", {}) if isinstance(raw, dict) else {}

    positives = [row for row in outcomes if row["injury"]]
    controls = [row for row in outcomes if not row["injury"]]
    caught = sum(1 for row in positives if row.get("critical"))
    deterministic = sum(1 for row in positives if row.get("signals"))
    false_criticals = sum(1 for row in controls if row.get("critical"))

    def _ratio(rows: list[dict]) -> tuple[int, int]:
        return sum(1 for row in rows if row.get("critical")), len(rows)

    breakdown: list[Breakdown] = []

    # The two halves first, because they are what the headline has to be read
    # against. `tune` are the cases the prompt and the dictionary were written
    # while looking at, `holdout` were written before anything was run against
    # them, and only the second estimates reach rather than fit. Emitted only
    # when the run carries the split, so an older file still renders.
    for split in ("holdout", "tune"):
        rows = [row for row in positives if row.get("split") == split]
        if not rows:
            continue
        hits, total = _ratio(rows)
        breakdown.append(
            Breakdown(
                label=SPLIT_LABELS[split],
                value=hits / total,
                numerator=hits,
                denominator=total,
            )
        )

    breakdown.append(
        Breakdown(
            label="deterministik katman (LLM düştüğünde kalan)",
            value=deterministic / len(positives) if positives else None,
            numerator=deterministic,
            denominator=len(positives),
        )
    )
    # Fixed, not derived: the corpus has 38 injury records and the urgency
    # phrase caught all 38. It is carried here so the reader can see the
    # number §7 used to report beside the one that replaced it. Regenerating
    # the corpus invalidates it - eval/masking_recall.py's holdout split is
    # the model for measuring this properly, and this row should follow it.
    breakdown.append(
        Breakdown(
            label="korpus kalıbı (kanonik ifadeler)",
            value=1.0,
            numerator=38,
            denominator=38,
        )
    )
    for group in sorted({row["group"] for row in positives}):
        rows = [row for row in positives if row["group"] == group]
        hits, total = _ratio(rows)
        breakdown.append(
            Breakdown(
                label=f"pipeline, {INJURY_GROUP_LABELS.get(group, group)}",
                value=hits / total,
                numerator=hits,
                denominator=total,
            )
        )

    return Metric(
        key="critical_recall",
        label="Kritik aciliyet recall",
        value=caught / len(positives) if positives else None,
        unit="ratio",
        numerator=caught,
        denominator=len(positives),
        target=0.97,
        target_operator="gte",
        sample=Sample(
            n=len(positives),
            unit="ifade",
            description="korpusta bulunmayan yaralanma ifadeleri (elle yazılmış fixture)",
        ),
        source=Source(
            run=path.name,
            measured_at=measured_at or _measured_at(meta),
            model=meta.get("model"),
        ),
        breakdown=breakdown,
        notes=[
            "Manşet sayı korpusun değil, fixture'ın sayısıdır. Korpus üzerinden ölçüldüğünde "
            "bu metrik %100 verir; ama oradaki kritik kayıtların hepsi dört sabit cümleden "
            "birini taşıyor ve dördü de kanonik bir yaralanma terimi içeriyor — yani o %100 "
            "kalıbı ölçüyor, sistemin erişimini değil.",
            "Manşet iki yarının toplamıdır. Ayarlama yapılan yarıda ölçülen değer sistemin "
            "erişimini değil kuralların ne kadar iyi yazıldığını söyler; dokunulmamış yarı "
            "kırılımda ayrı bir satır olarak duruyor ve dürüst tahmin odur.",
            f"Deterministik katman bu ifadelerin {deterministic}/{len(positives)} tanesini "
            "yakalıyor; geri kalanı LLM taşıyor. Sağlayıcı fallback'i olmadığı sürece bu "
            "metrik tek bir servise bağlı.",
            f"Yaralanma içermeyen {len(controls)} kontrol ifadesinin {false_criticals} tanesi "
            "yanlışlıkla kritik işaretleniyor — recall'ın karşı tarafı. Beşi de deterministik "
            "katmandan geliyor; model tek bir yanlış kritik üretmedi.",
            f"Prompt: {meta.get('prompt', 'bilinmiyor')}, seed {meta.get('seed', '—')}, "
            f"{meta.get('tier', '—')} kademe. Aynı seed'le iki koşu 70 vakanın 1'inde ayrıştı, "
            "yani dokunulmamış yarıda bir puan gürültünün içindedir.",
            "Bilinen kaçak: 'Üç gün yoğun bakımda kaldı' — setteki en ağır ifade, model "
            "alıntı bile önermiyor. Bilerek düzeltilmedi: dokunulmamış yarıya karşı ayar "
            "yapmak o yarıyı dokunulmuş hale getirir.",
        ],
    )


def masking_recall_metric(path: Path, *, measured_at: str | None = None) -> Metric:
    """Deterministic-layer masking recall, split by name source."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    groups = raw["groups"]
    overall = groups["deterministic"]
    holdout = groups["names_holdout"]

    return Metric(
        key="masking_recall",
        label="Maskeleme recall",
        value=overall["recall"],
        unit="ratio",
        numerator=overall["masked"],
        denominator=overall["present"],
        target=0.97,
        target_operator="gte",
        sample=Sample(
            n=raw["records_scanned"],
            unit="metin",
            description="sabitlenmiş baseline örneklemi" if raw.get("pinned") else "tüm korpus",
        ),
        source=Source(run=path.name, measured_at=measured_at),
        breakdown=[
            Breakdown(
                label=MASKING_GROUP_LABELS[name],
                value=groups[name]["recall"],
                numerator=groups[name]["masked"],
                denominator=groups[name]["present"],
            )
            for name in ("regex", "names_faker", "names_holdout")
        ],
        notes=[
            "§7'nin kapsamı deterministik katman (regex + sözlük). LLM sanity taraması ayrı "
            "bir katman ve ayrı bir soru.",
            f"Sözlükte bulunmayan isimlerde recall {_pct(holdout['recall'])} "
            f"({holdout['masked']}/{holdout['present']}). Faker isimlerindeki yüksek sayı "
            "dairesel: sözlük korpusun isim havuzunun kendisinden üretilmiş.",
        ],
    )


def manual_metrics(manual: dict) -> list[Metric]:
    """Metrics no eval run can produce, read from a reviewed file.

    p95 is the only one today. §7 asks for end-to-end latency and eval measures
    one pipeline step, so the number has to come from audit_trail - a database
    the eval package deliberately does not talk to.
    """
    entry = manual.get("p95_latency") or {}
    value = entry.get("value_seconds")

    return [
        Metric(
            key="p95_latency",
            label="p95 uçtan uca gecikme",
            value=value,
            unit="seconds",
            target=60.0,
            target_operator="lte",
            sample=Sample(
                n=entry.get("sample_n"),
                unit="ihbar",
                description=entry.get("sample_description", ""),
            ),
            source=Source(
                run=entry.get("source", "audit_trail"), measured_at=entry.get("measured_at")
            ),
            notes=[
                "Diğer metriklerden farklı olarak bir eval koşusundan değil, veritabanındaki "
                "denetim izinden elle alındı — kaynağı eval/reports/manual_inputs.json.",
                *entry.get("notes", []),
            ],
        )
    ]


def rag_metric(path: Path) -> Metric:
    """§7's eighth row. Empty until eval/rag.py has been run.

    Stays in the table either way: an unmeasured target and a met one are
    different things, and only one of them should be invisible.
    """
    if not path.exists():
        return Metric(
            key="rag_accuracy",
            label="RAG doğruluğu",
            value=None,
            unit="ratio",
            target=0.65,
            target_operator="gte",
            sample=Sample(n=None, unit="soru", description=""),
            source=None,
            notes=[
                "Henüz ölçülmedi. `python -m eval.rag` ile ölçülür; veritabanı ve API "
                "anahtarı ister.",
            ],
        )

    raw = json.loads(path.read_text(encoding="utf-8"))
    outcomes = raw["outcomes"]
    meta = raw.get("meta", {})
    passed = sum(1 for row in outcomes if row["passed"])

    by_category: dict[str, tuple[int, int]] = {}
    for row in outcomes:
        hits, total = by_category.get(row["category"], (0, 0))
        by_category[row["category"]] = (hits + int(row["passed"]), total + 1)

    return Metric(
        key="rag_accuracy",
        label="RAG doğruluğu",
        value=passed / len(outcomes) if outcomes else None,
        unit="ratio",
        numerator=passed,
        denominator=len(outcomes),
        target=0.65,
        target_operator="gte",
        sample=Sample(
            n=len(outcomes),
            unit="soru",
            description="elle yazılmış değerlendirme seti, canlı veritabanına karşı",
        ),
        source=Source(run=path.name, measured_at=_measured_at(meta)),
        breakdown=[
            Breakdown(
                label=RAG_CATEGORY_LABELS.get(name, name),
                value=hits / total if total else None,
                numerator=hits,
                denominator=total,
            )
            for name, (hits, total) in by_category.items()
        ],
        notes=[
            "Her sorunun cevap anahtarı kendisiyle geliyor: sayısal sorular aynı "
            "veritabanına karşı koşan bir referans sorguyla, erişim soruları bulunması "
            "gereken ihbar listesiyle, reddetme soruları da cevaplanmaması gerektiğiyle "
            "doğrulanıyor. Anahtar elle yazılmadığı için eskimiyor.",
            "Sorular canlı veritabanının içeriğinden türetildi, korpustan değil — RAG "
            "korpusu değil veritabanını okuyor.",
        ],
    )


RAG_CATEGORY_LABELS = {
    "sql": "Sayısal sorular (SQL yolu)",
    "retrieval": "İçerik soruları (arama yolu)",
    "refusal": "Reddedilmesi gerekenler",
}


def build(
    *,
    extraction: Path = DEFAULT_EXTRACTION,
    gate_run: Path = DEFAULT_GATE,
    injury: Path = DEFAULT_INJURY,
    masking: Path = DEFAULT_MASKING,
    manual: Path = DEFAULT_MANUAL,
    rag: Path = DEFAULT_RAG,
) -> dict:
    """The whole §7 table, in the order §7 lists it."""
    manual_data = json.loads(manual.read_text(encoding="utf-8")) if manual.exists() else {}
    provenance = manual_data.get("provenance", {})

    rows: list[Metric] = [
        *extraction_metrics(extraction),
        *gate_metrics(gate_run),
        critical_recall_metric(injury, measured_at=provenance.get(injury.name)),
        masking_recall_metric(masking, measured_at=provenance.get(masking.name)),
        *manual_metrics(manual_data),
        rag_metric(rag),
    ]

    # Keyed by status, but spelled out: "pass" is a Python keyword and this
    # summary crosses into a Pydantic model on the API side, where a field
    # called `pass` would need an alias to exist at all.
    summary_keys = {"pass": "passed", "fail": "failed", "unmeasured": "unmeasured"}
    counts: dict[str, int] = {name: 0 for name in summary_keys.values()}
    for row in rows:
        counts[summary_keys[row.status]] += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {"total": len(rows), **counts},
        "metrics": [{**asdict(row), "status": row.status} for row in rows],
    }


def format_report(payload: dict) -> str:
    """The same table as text, for whoever regenerated the file."""
    summary = payload["summary"]
    lines = [
        f"generated {payload['generated_at'][:19]}",
        f"  {summary['passed']} pass, {summary['failed']} fail, "
        f"{summary['unmeasured']} unmeasured of {summary['total']}",
        "",
        f"  {'metric':<34} {'value':>10}  {'target':>9}  status   source",
    ]
    for row in payload["metrics"]:
        if row["value"] is None:
            value = "-"
        elif row["unit"] == "seconds":
            value = f"{row['value']:.2f} sn"
        else:
            value = f"{row['value']:.2%}"
        # ASCII on purpose: this goes to a Windows console, where cp1254 cannot
        # encode the maths signs. The JSON keeps the raw operator either way.
        operator = ">=" if row["target_operator"] == "gte" else "<="
        target = (
            f"{operator} {row['target']:.0f} sn"
            if row["unit"] == "seconds"
            else f"{operator} {row['target']:.0%}"
        )
        source = (row["source"] or {}).get("run", "-")
        lines.append(f"  {row['key']:<34} {value:>10}  {target:>9}  {row['status']:<8} {source}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.report", description=__doc__)
    parser.add_argument("--extraction", type=Path, default=DEFAULT_EXTRACTION)
    parser.add_argument("--gate", type=Path, default=DEFAULT_GATE, dest="gate_run")
    parser.add_argument("--injury", type=Path, default=DEFAULT_INJURY)
    parser.add_argument("--masking", type=Path, default=DEFAULT_MASKING)
    parser.add_argument("--manual", type=Path, default=DEFAULT_MANUAL)
    parser.add_argument("--rag", type=Path, default=DEFAULT_RAG)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    payload = build(
        extraction=args.extraction,
        gate_run=args.gate_run,
        injury=args.injury,
        masking=args.masking,
        manual=args.manual,
        rag=args.rag,
    )
    print(format_report(payload))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
