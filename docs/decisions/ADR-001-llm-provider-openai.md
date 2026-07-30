# ADR-001: LLM provider — OpenAI as the primary model

**Date:** 2026-07-28
**Status:** Accepted

## Context

The original plan (CLAUDE.md §2, .env.example) was a zero-cost triple router:
Groq (Llama 3.3 70B) → Gemini 2.0 Flash → Ollama (local), falling through on
429 or error. No code was ever written for it: `worker/llm_router` does not
exist and `prompts/` is empty. The decision was on paper only.

Meanwhile the DS/LLM design settled on a different shape. Extraction depends on
structured output — a Pydantic schema the model must fill in, validated and
retried automatically. That contract carries the hallucination defence: a
source quote per field, a per-field confidence score, and an explicit list of
fields left null. Three providers with three JSON dialects and a fallback chain
make that contract harder to guarantee and much harder to evaluate honestly —
an eval run where some calls silently fell through to a weaker model measures
nothing in particular. Open-weight models also hallucinate noticeably more on
this task, which is the failure mode the whole design is built to suppress.

## Decision

All LLM calls go to OpenAI through a single client (`worker/llm/client.py`),
in two tiers:

| Tier | Model | Used for |
| --- | --- | --- |
| cheap | gpt-4o-mini | classification, triage, RAG routing |
| strong | gpt-4o | extraction, Text-to-SQL, RAG answers |

Structured output uses `instructor` + Pydantic: the answer is validated against
the schema and re-asked on a validation error. `temperature` is 0 and eval runs
pin a `seed`, so weekly measurements stay comparable. Exact model versions are
pinned after the first eval baseline.

**The other providers stay configured but unused.** `GROQ_API_KEY`,
`GEMINI_API_KEY` and `OLLAMA_HOST` remain in `.env.example` under a "fallback"
heading, and the `ollama` service stays in `docker-compose.yml`. Nothing reads
them today. Keeping them means a fallback layer can be added later without
reopening this decision.

**Embeddings are not affected.** They stay local (sentence-transformers,
Turkish HF model, 384 dimensions) — free, offline, and the same model is used
in both eval and RAG. `VECTOR(384)` in the migration stays as is. Candidate
models are therefore constrained to 384-dim multilingual encoders; revisiting
the dimension means a migration and re-embedding everything, owned by
@bariss9. The model itself is picked later from 2-3 candidates measured on real
eval data (design doc §10).

## Alternatives considered

| Alternative | Pro | Con |
| --- | --- | --- |
| Free-tier triple router (Groq → Gemini → Ollama) | Zero cost; no vendor lock-in | Never implemented; three JSON dialects; a mid-run fallback makes eval numbers unreadable; Groq rate limits can hit during a demo |
| Ollama only (fully local) | Zero cost; offline; nothing leaves the machine | Turkish quality well below cloud models; markedly more hallucination; needs a GPU for acceptable latency; structured output unreliable |
| OpenAI primary, others kept as unused config (chosen) | Best Turkish quality; native structured output; predictable latency; one JSON dialect; fallback stays possible | Costs money; needs an API key; no offline demo until fixtures exist |

The privacy argument that favoured local models does not apply here: all data in
this project is synthetic (`data/gt_generator.py`), and PII is masked before any
text reaches the model.

## Consequences

**Easier**
- One provider, one JSON dialect — extraction and classification share a client.
- Validation and retry live in one place.
- Eval numbers are attributable to one model, not to a fallback chain.

**Harder**
- Running the pipeline costs money and requires `OPENAI_API_KEY`.
- The offline demo path (`DEMO_OFFLINE`, CLAUDE.md §8) no longer has a local
  model behind it. It needs recorded fixtures instead — Sprint 4 work.

**Still open — deliberately not done in this PR**
- A working fallback layer (OpenAI fails → Groq/Gemini) is **not implemented**.
  Only the configuration is preserved. Whether to build one is a separate
  decision; raised by @nursenakyga and @bariss9 and left open here.
- `CLAUDE.md` §2 still describes the triple router, and §4 still requires every
  call to go through `worker/llm_router`. Both need updating — CLAUDE.md is
  owned by @bariss9.
- `docker-compose.yml` still starts the `ollama` service, now unused. Removing
  it is @bariss9 / @nursenakyga's call.
