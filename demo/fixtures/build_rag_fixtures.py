# demo/fixtures/build_rag_fixtures.py
"""Recorded /soru answers for DEMO_OFFLINE.

Unlike the other three builders, this one has no ground truth to read: questions
are not part of the corpus. The five demo questions and their answers are
curated here, and every number in them was measured against a real database
before it was written down - see the DATASET note below.

What is faked and what is not
-----------------------------
Faked (recorded here):   which path a question takes (QuestionRoute), the SQL
                         that answers it (SqlQuery), and the Turkish sentence
                         (SqlNarration / RagAnswer).
Real, offline included:  worker/rag/sql_guard.py vets the recorded SQL, the
                         query runs against the real database, sql_answer's
                         number check runs over the real rows, retrieval runs
                         over real pgvector + the local e5 model, and answer.py
                         validates the recorded citations against the sources
                         retrieval actually found.

That is the arrangement agreed with @Cagri12345: canned queries, real execution,
real verification.

DATASET
-------
The numbers below were measured on 2026-08-08 against the first 60 records of
data/texts.jsonl, pushed through the pipeline. They are pinned to that dataset:
count 5 critical, 9 hail, İzmir 14 / Ankara 11 / Antalya 11 / İstanbul 10 /
Bursa 8. Against a different dataset the sentences do not become wrong - the
number check withholds them and the operator gets a refusal instead. That is
the safe direction, but it does mean the demo database has to be the seeded one.

    python demo/fixtures/build_rag_fixtures.py
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from worker.rag.answer import RagAnswer  # noqa: E402
from worker.rag.ask import normalize_question  # noqa: E402
from worker.rag.router import QuestionRoute  # noqa: E402
from worker.rag.schema import SqlQuery  # noqa: E402
from worker.rag.sql_answer import SqlNarration  # noqa: E402

OUTPUT = Path(__file__).resolve().parent / "demo_rag.jsonl"

TIER = "cheap"
WILDCARD_GT_ID = "*"

OFFLINE_NOTE = "Çevrimdışı demo: kayıtlı cevap."

# --- the five demo questions -------------------------------------------------
#
# Each entry carries the payloads for the models its route actually reaches:
# the SQL path uses QuestionRoute + SqlQuery + SqlNarration, the retrieval path
# QuestionRoute + RagAnswer. Recording only what a route needs keeps a wrong
# entry from quietly standing in for a missing one.

QUESTIONS: list[dict] = [
    {
        "question": "Kaç tane kritik ihbar var?",
        "route": {
            "reasoning": f"{OFFLINE_NOTE} Sayım isteniyor, SQL yolu.",
            "route": "sql",
            "urgency": None,
            "status": None,
        },
        "sql": {
            "reasoning": f"{OFFLINE_NOTE} urgency alanı üzerinde sayım.",
            "answerable": True,
            "sql": (
                "SELECT count(*) AS kritik_ihbar_sayisi FROM claims_flat WHERE urgency = 'critical'"
            ),
            "refusal_reason": None,
        },
        # Measured: 1 row, kritik_ihbar_sayisi = 5.
        "narration": {
            "reasoning": f"{OFFLINE_NOTE} Sorgu tek satır döndürdü.",
            "answerable": True,
            "answer": "Kritik aciliyetli 5 ihbar var.",
            "refusal_reason": None,
        },
    },
    {
        "question": "Hangi şehirlerde en çok hasar bildirimi var?",
        "route": {
            "reasoning": f"{OFFLINE_NOTE} Gruplama ve sıralama isteniyor, SQL yolu.",
            "route": "sql",
            "urgency": None,
            "status": None,
        },
        "sql": {
            "reasoning": f"{OFFLINE_NOTE} city alanına göre gruplama.",
            "answerable": True,
            "sql": (
                "SELECT city, count(*) AS ihbar_sayisi FROM claims_flat "
                "WHERE city IS NOT NULL GROUP BY city ORDER BY ihbar_sayisi DESC, city"
            ),
            "refusal_reason": None,
        },
        # Measured: İzmir 14, Ankara 11, Antalya 11, İstanbul 10, Bursa 8.
        "narration": {
            "reasoning": f"{OFFLINE_NOTE} Sorgu şehir kırılımını döndürdü.",
            "answerable": True,
            "answer": (
                "En çok ihbar İzmir'den geldi (14 kayıt). Ankara ve Antalya 11'er, "
                "İstanbul 10 ve Bursa 8 kayıtla onu izliyor."
            ),
            "refusal_reason": None,
        },
    },
    {
        "question": "Kaç tane dolu hasarı bildirildi?",
        "route": {
            "reasoning": f"{OFFLINE_NOTE} Sayım isteniyor, SQL yolu.",
            "route": "sql",
            "urgency": None,
            "status": None,
        },
        "sql": {
            "reasoning": f"{OFFLINE_NOTE} damage_type = 'hail' üzerinde sayım.",
            "answerable": True,
            "sql": (
                "SELECT count(*) AS dolu_hasari_sayisi FROM claims_flat WHERE damage_type = 'hail'"
            ),
            "refusal_reason": None,
        },
        # Measured: 1 row, dolu_hasari_sayisi = 9.
        "narration": {
            "reasoning": f"{OFFLINE_NOTE} Sorgu tek satır döndürdü.",
            "answerable": True,
            "answer": "Dolu nedeniyle 9 hasar bildirimi yapılmış.",
            "refusal_reason": None,
        },
    },
    {
        "question": "Camı kırılan bir araç var mı?",
        "route": {
            "reasoning": f"{OFFLINE_NOTE} İhbar içeriği soruluyor, retrieval yolu.",
            "route": "retrieval",
            "urgency": None,
            "status": None,
        },
        # Measured: the nearest hit is a glass-breaking theft in İstanbul
        # Üsküdar, 13 Temmuz (claim 53 / GT-000052, score 0.8411).
        "answer": {
            "reasoning": f"{OFFLINE_NOTE} En yakın kayıt cam kırılması içeriyor.",
            "answerable": True,
            "answer": (
                "Evet, camı kırılarak içindeki eşyaların çalındığı bir araç kaydı var; "
                "olay İstanbul Üsküdar'da gerçekleşmiş [1]."
            ),
            "refusal_reason": None,
            "used_sources": [1],
        },
    },
    {
        "question": "Yaralanmalı bir kaza var mı, ne olmuş?",
        # urgency=critical is what makes this one work. Without the filter the
        # two nearest hits are an animal collision and a door collision, and the
        # injury records sit at positions 3 and 4 - a recorded answer citing [1]
        # would then point at the wrong claim. With it, position 1 is an injury
        # record and the route also becomes `hybrid`, which is the mode the
        # Soru screen shows for a filtered search.
        "route": {
            "reasoning": f"{OFFLINE_NOTE} İçerik sorusu, kritik aciliyet filtresiyle.",
            "route": "retrieval",
            "urgency": "critical",
            "status": None,
        },
        # Measured with that filter: nearest hit is claim 60 / GT-000059,
        # "Kazada yaralanan oldu, durum ciddiydi." (score 0.8513).
        "answer": {
            "reasoning": f"{OFFLINE_NOTE} En yakın kritik kayıt yaralanma bildiriyor.",
            "answerable": True,
            "answer": (
                "Evet, yaralanmalı bir kaza kaydı var: kazada yaralanan olmuş ve durum "
                "ciddi olarak bildirilmiş [1]."
            ),
            "refusal_reason": None,
            "used_sources": [1],
        },
    },
]

# --- wildcards ---------------------------------------------------------------
#
# Required for every response model (worker/llm/client.py refuses a set without
# them). The route wildcard sends an unknown question down retrieval: a canned
# SQL query for a question nobody recorded would run and return a real number
# answering something else entirely, which is the worst outcome available.
# Retrieval at least searches the real corpus, and the answer wildcard then
# declines honestly.

WILDCARD_UNKNOWN = (
    "Bu soru bu demo için hazırlanmamış, offline modda yalnızca senaryo "
    "sorularına cevap verilebilir."
)

WILDCARDS: dict[str, dict] = {
    "QuestionRoute": {
        "reasoning": "Çevrimdışı demo: kayıtlı olmayan soru, güvenli varsayılan.",
        "route": "retrieval",
        "urgency": None,
        "status": None,
    },
    "RagAnswer": {
        "reasoning": "Çevrimdışı demo: bu soru için kayıtlı cevap yok.",
        "answerable": False,
        "answer": None,
        "refusal_reason": WILDCARD_UNKNOWN,
        "used_sources": [],
    },
    # Unreachable in practice - the route wildcard never picks sql - but the
    # loader requires one per model, and an unreachable record that declines is
    # the right thing to put there.
    "SqlQuery": {
        "reasoning": "Çevrimdışı demo: bu soru için kayıtlı sorgu yok.",
        "answerable": False,
        "sql": None,
        "refusal_reason": WILDCARD_UNKNOWN,
    },
    "SqlNarration": {
        "reasoning": "Çevrimdışı demo: bu soru için kayıtlı cevap yok.",
        "answerable": False,
        "answer": None,
        "refusal_reason": WILDCARD_UNKNOWN,
    },
}

MODELS = {
    "QuestionRoute": QuestionRoute,
    "SqlQuery": SqlQuery,
    "SqlNarration": SqlNarration,
    "RagAnswer": RagAnswer,
}

# Which entry key carries which response model's payload.
PAYLOAD_KEYS = {
    "route": "QuestionRoute",
    "sql": "SqlQuery",
    "narration": "SqlNarration",
    "answer": "RagAnswer",
}


def record(key: str, response_model: str, payload: dict) -> dict:
    """Validate against the real schema, then shape the fixture line."""
    MODELS[response_model](**payload)
    return {
        "gt_id": key,
        "response_model": response_model,
        "tier": TIER,
        "payload": payload,
    }


def main() -> None:
    lines: list[str] = []

    for entry in QUESTIONS:
        # The same normalizer ask() applies at runtime, so the key here and the
        # key looked up there cannot drift.
        key = normalize_question(entry["question"])
        for payload_key, response_model in PAYLOAD_KEYS.items():
            payload = entry.get(payload_key)
            if payload is None:
                continue
            lines.append(json.dumps(record(key, response_model, payload), ensure_ascii=False))

    for response_model, payload in WILDCARDS.items():
        lines.append(
            json.dumps(record(WILDCARD_GT_ID, response_model, payload), ensure_ascii=False)
        )

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{OUTPUT.name}: {len(QUESTIONS)} questions, {len(lines)} records")


if __name__ == "__main__":
    main()
