# ADR-002: Embedding model — multilingual-e5-small

**Date:** 2026-08-04
**Status:** Accepted

## Context

ADR-001 kept embeddings local and deferred the model itself: "picked later from
2-3 candidates measured on real eval data". This closes that.

Constraints already fixed elsewhere and not reopened here:

- local, free, offline (ADR-001)
- 384 dimensions — `VECTOR(384)` in the migration and `api/models/db.py:69`.
  Changing it means a migration and re-embedding everything, owned by @bariss9.
- Turkish text, so a multilingual encoder.

384 plus multilingual is a narrow shelf. Most Turkish-specific sentence encoders
are BERT-base derivatives at 768 dimensions and do not fit. Two candidates were
measured:

- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` — the model
  CLAUDE.md §2 names, trained for paraphrase similarity
- `intfloat/multilingual-e5-small` — trained for retrieval, expects instruction
  prefixes

Two consumers, unequal in size. RAG (Sprint 3) is the large one: retrieval over
claim text. Eval is the small one: cosine scoring of `damage_description`, which
is free text and cannot be compared for equality.

## What was measured, and the trap that came first

Worth recording before the numbers. The first attempt ranked all 1000
ground-truth descriptions and scored *both* candidates at p@5 = 1.000. The corpus
carries only **61 distinct** `damage_description` strings across those 1000
records — `data/dictionaries/` is a small phrase set, and the most common string
appears 32 times. A description's nearest neighbours were its own duplicates, so
the measurement was string identity, not meaning. Everything below is over the 61
distinct strings.

1. **Same-type retrieval** — for each distinct description, do its nearest
   neighbours carry the same `damage_type`? The RAG question.
2. **True pairs against hard negatives** — the 15 records where extraction did
   not copy the ground-truth description verbatim, scored against the other
   distinct descriptions of the same damage type. The eval question.

| | MiniLM-L12-v2 | e5-small |
| --- | ---: | ---: |
| same-type p@1 | 0.541 | 0.525 |
| same-type p@3 | 0.475 | 0.508 |
| chance | 0.119 | 0.119 |
| true pair cosine, mean | 0.809 | 0.949 |
| same-type impostor, mean | 0.571 | 0.876 |
| true pair beats impostor | 88.9% | **95.0%** |
| encode rate | 203/s | 220/s |

n = 61 descriptions, 15 pairs. Both clear chance by roughly four times on
retrieval and are level with each other there. The difference is in ranking a
true pair above an impostor.

## Decision

`intfloat/multilingual-e5-small`, 384 dimensions, loaded locally through
`sentence-transformers`.

It does not lose the retrieval measurement, it wins the pair measurement, and it
is the candidate trained for the job the larger consumer needs.

**Its prefixes are part of this decision, not an implementation detail.** e5 was
trained with `query: ` and `passage: ` markers, and text embedded without them is
silently worse — the failure leaves no trace in any output. `worker/embedding/`
applies the prefix in one place; callers never hand raw text to the encoder.

## Alternatives considered

| Alternative | Pro | Con |
| --- | --- | --- |
| paraphrase-multilingual-MiniLM-L12-v2 | Named in CLAUDE.md §2; far wider cosine spread (0.24 against 0.07), so scores are easier to read by eye | Ranks a true pair above an impostor less reliably (88.9% against 95.0%); trained for paraphrase, not retrieval |
| multilingual-e5-small (chosen) | Best on the pair measurement; trained for retrieval; level on p@1/p@3 | Prefix requirement is a silent footgun; compressed cosine range makes absolute thresholds hard to read |
| A Turkish-specific encoder | Trained on the actual language | Those surveyed are 768-dim BERT derivatives; they do not fit `VECTOR(384)` without a migration |
| Defer again until the RAG question set exists | Would decide on the real task | Blocks eval free-text scoring and all of Sprint 3 RAG, and the question set is itself weeks out |

## Consequences

**Easier**
- Embedding is free and offline: no key, no rate limit, no per-claim cost.
- One model in both eval and RAG, so a similarity number means the same thing in
  both places.
- `VECTOR(384)` stands. No migration.

**Harder**
- `sentence-transformers` pulls `torch`. Putting it in `requirements.txt` grows
  the worker image substantially — a shared cost the backend pair should hear
  about before it lands (CLAUDE.md §6).
- The prefix rule has to survive every future caller, which is why it lives in
  the module rather than in a docstring.

**Weak evidence, recorded as such on purpose**
- n = 61 distinct descriptions and 15 true pairs. This is the best measurement
  the corpus supports, not a confident one.
- Neither candidate produced a clean threshold: true-pair and impostor cosine
  ranges overlap for both. Anything built on this should rank, not threshold.
- `damage_type` is a noisy proximity label — "ön tampon hasar gördü" appears
  under both `collision` and `animal` — so p@1 near 0.53 understates both models.
- The real test is the 40-question RAG set. If it contradicts this, revisit; the
  cost of changing course is one config line, since nothing else depends on the
  choice.

**Also learned here, and not about embeddings**
- 1000 records carry 61 distinct damage descriptions. RAG cannot be honestly
  demonstrated on this corpus: retrieval over 61 strings will look perfect and
  prove nothing. The RAG question set has to be designed knowing that, and
  @muyesser10 should hear it.
