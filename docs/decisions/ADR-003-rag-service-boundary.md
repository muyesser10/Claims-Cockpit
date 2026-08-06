# ADR-003: `/soru` runs in its own `rag` service

**Date:** 2026-08-05
**Status:** Accepted (2026-08-06, @bariss9 — the owner of `docker-compose.yml`
and the api service this splits work away from)

## Context

Sprint 3's `/soru` endpoint (design doc §7) answers a Turkish question two ways:
a Text-to-SQL path for counts and aggregates, and a retrieval path for questions
over free text. The retrieval path has to embed the question itself, and ADR-002
put embeddings in a local `sentence-transformers` model — which pulls torch.

That collides with where the endpoint would naturally live. `api/` is a thin
FastAPI service: it does not import anything under `worker/`, and `api/Dockerfile`
does not even copy that directory. As of the torch split, the api image installs
`requirements.txt` alone and comes to 507 MB of dependencies; `requirements-worker.txt`,
which carries `sentence-transformers`, is installed only by the worker image
(measured: 34 MB of wheels against 306 MB).

So an endpoint that both serves HTTP and embeds text does not fit either service
as they stand. Something has to move: torch into the api image, the endpoint out
of it, or the embeddings off this machine entirely.

One more constraint shapes the answer. A RAG reply takes 8-20 seconds — a local
model plus an LLM call. Whatever carries it has to hold an HTTP request open that
long without blocking the pipeline that drains `claims:incoming`.

## Decision

`/soru` runs in a new compose service, `rag`, built from the **worker image** with
a different command: uvicorn serving a small FastAPI app. It imports `worker.rag.*`
and `worker.embedding.*` directly, since it ships the same code.

`api` gains a thin `/soru` route that proxies to it. The web app keeps talking to
one origin through the existing `/api/...` proxy and never learns this split
exists.

The pipeline worker stays a separate container from `rag`, even though they share
an image. A question arriving while the queue is draining must not wait behind
a claim being extracted, and a crash in one must not take the other down.

## Alternatives considered

| Alternative | Pro | Con |
| --- | --- | --- |
| Separate `rag` service (chosen) | api stays 507 MB; torch lives in one image; ADR-002 stands untouched; question handling cannot stall the pipeline | A service to add to `docker-compose.yml` (shared file, CLAUDE.md §5) and a proxy hop to maintain |
| Put `worker/` and torch into the api image | Simplest: one service, no proxy, no compose change | Takes the api image from 507 MB to roughly the worker's 2.21 GB, undoing half of the build work just merged; also loads a 470 MB model into the process serving `/queue` |
| Dispatch questions over Redis, like `claims:incoming` | Consistent with the existing queue; no new service | A synchronous 8-20 s HTTP request served through a queue needs a reply channel, a correlation id and timeout handling — the most code of the four, for a request that is not batch work |
| Move embeddings to OpenAI (`text-embedding-3-small`) | No torch anywhere; api stays thin with no new service | Reverses ADR-002 one day after it was measured; 1536 dimensions against `VECTOR(384)` means a migration and re-embedding everything (@bariss9's work); gives up free and offline, and sends claim text to a third party on every question |

## Consequences

**Easier**
- The api image stays small, and the reasons it is small stay true.
- torch, the e5 model and its 470 MB download exist in exactly one image.
- RAG can be restarted, scaled or switched off without touching ingest, the queue
  or the pipeline. `DEMO_OFFLINE` (Sprint 4) gets a clean seam.
- `worker/rag/*` keeps its current shape: pure modules that know nothing about
  HTTP, with the service as a thin shell over them.

**Harder**
- `docker-compose.yml` gains a service. Shared file — @bariss9 merges it the same
  day (CLAUDE.md §5), and the api needs `RAG_SERVICE_URL` in `.env.example`.
- One more hop to debug: a failing question can now be the proxy, the service or
  the model. The audit trail entry has to name which.
- The proxy has to pass the caller's JWT through, or `/soru` ends up as the one
  unauthenticated read path into claim data. It must not repeat `/ingest`'s
  deliberate exemption by accident. Raised again by @bariss9 as the condition of
  accepting this ADR, and now held by tests rather than by intent: the proxy
  forwards the caller's header (`test_the_callers_token_is_forwarded`), a request
  without one is refused before it reaches the network
  (`test_a_question_without_a_token_never_reaches_the_service`), and the rag
  service verifies for itself so neither hop is the only door
  (`rag/test_main.py::test_a_question_without_a_token_is_refused`).
- Two containers now load code from `worker/`, so a change there redeploys both.

**Open**
- Whether `rag` also serves the eval runs, or eval keeps calling the modules
  in-process. In-process is simpler and has no network in the loop; deciding it
  now would be premature.
