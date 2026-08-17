# ADR-004: No multi-provider LLM fallback

**Date:** 2026-08-17
**Status:** Accepted

## Context

CLAUDE.md §2 describes a zero-cost triple router — Groq → Gemini → Ollama,
falling through on 429 or error. ADR-001 replaced it with a single OpenAI
client but deliberately did not settle the question:

> A working fallback layer (OpenAI fails → Groq/Gemini) is **not implemented**.
> Only the configuration is preserved. Whether to build one is a separate
> decision; raised by @nursenakyga and @bariss9 and left open here.

Three weeks later nothing has been built. `GROQ_API_KEY`, `GEMINI_API_KEY` and
the five `LLM_MODEL_*` variants have sat in `.env.example` unread since
2026-07-28, and `docs/STATUS.md` still lists "çalışan fallback katmanı" as
outstanding work. An item that is neither built nor cancelled costs a little
attention every sprint and gets none of it.

Two things are known now that were not known when ADR-001 was written.

**The exposure has a number.** Measured 2026-08-17 over
`eval/fixtures/injury_phrasings.jsonl` (44 hard positives, the phrasings the
corpus does not contain): the pipeline reaches 86.4% critical recall with the
model and **20.5% (9/44) without it**. The deterministic layer catches a
canonical injury term and little else. So "OpenAI is unreachable" means four of
every five injury phrasings the system currently catches would be missed. That
is the risk this ADR is about, stated in the only units that matter.

**The demo-day failure mode has a different mitigation.** `DEMO_OFFLINE` (S4-6)
plays recorded fixtures through the real code path, so a network failure during
the final demo no longer needs a second provider behind it. When ADR-001 was
written that path did not exist, and "the demo dies without a fallback" was a
live argument. It no longer is.

## Decision

**There is no multi-provider fallback. OpenAI is the only provider.**

Groq, Gemini and Ollama are not used, and their configuration is removed rather
than kept as a standing promise. CLAUDE.md §2 and §4 are corrected to describe
what the code does — one client, one provider, no `worker/llm_router`.

What stays, because none of it is a second provider:

- `instructor` re-asks when the answer does not fit the schema
  (`LLM_MAX_RETRIES`, default 2).
- The OpenAI SDK retries transient failures (`LLM_SDK_MAX_RETRIES`, default 1).
- `fallback_classification()` triages on injury terms alone when the
  classification call fails, and the message is **not** dead-lettered — a
  claim is never lost to an LLM outage, only triaged worse.
- `DEMO_OFFLINE` answers from recorded fixtures.

### Why not build it anyway

ADR-001's three objections were never answered, and two still hold in full. A
mid-run fallback makes an eval number unreadable — a run where some calls
silently fell through to a weaker model measures nothing in particular. And
open-weight models hallucinate more on this task, which is the failure mode the
whole design exists to suppress; on the injury path a weaker model does not
trade a missed injury for nothing, it trades it for a wrong one.

The third objection — three JSON dialects — has weakened, because Groq, Gemini
and Ollama all now expose OpenAI-compatible endpoints and a fallback could run
through the same SDK on a different `base_url`. That makes the work smaller
than ADR-001 assumed. It does not make it worth doing.

The deciding argument is measurement. No second provider key exists on the
team, so a fallback written today could not be exercised even once, let alone
scored on the injury fixture. Shipping an untried failure path repeats exactly
what ADR-001 criticised about the original router: "The decision was on paper
only." A fallback that has never fired successfully is not a fallback.

## Accepted risk

Critical recall — CLAUDE.md §7's ≥97% target, the one metric whose failure mode
is a missed injury — depends on a single vendor being reachable.

| | with the model | deterministic only |
| --- | ---: | ---: |
| Critical recall, hard fixture (n=44) | 86.4% | 20.5% |

Bounded by three things. A claim carrying a canonical injury word still reaches
`critical` with no model at all, so the plainest cases survive. Nothing is
dropped: classification failure falls back to terms and the message stays in
the queue. And every claim still lands in front of a human, because the
auto-approval gate ships closed (`AUTO_APPROVE_ENABLED=false`).

**What reopens this decision:** a real deployment against non-synthetic traffic,
or a second provider key plus a scored run of `python -m eval.injury_recall
--live` against it. Reopening is cheap — the `.env` block and this ADR are the
only things that have to come back.

## Alternatives considered

| Alternative | Pro | Con |
| --- | --- | --- |
| No fallback (chosen) | One provider, one dialect; every eval number attributable to one model; nothing untested ships | Critical recall depends on one vendor: 86.4% → 20.5% if OpenAI is unreachable |
| OpenAI → Groq on availability errors | Free tier; OpenAI-compatible endpoint, so no new dependency and one JSON dialect | No key on the team, so it could not be exercised or scored; a weaker model on the injury path trades a missed injury for a wrong one |
| A second OpenAI model as the degradation path | Proves the mechanism with the key we already have | Not a fallback: if OpenAI is unreachable both tiers are unreachable together |
| Revive Ollama (ADR-001's local option) | Genuinely independent; no key needed; offline | Service is dead since ADR-001 and behind a compose profile; needs a model pull and is slow without a GPU; ADR-001 measured its Turkish quality as well below cloud |

## Consequences

**Easier**

- `docs/STATUS.md` loses an open item that was never going to be worked on.
- One provider means one JSON dialect, one retry policy, one place where the
  audit trail records a model name — and every §7 number stays attributable to
  a single model rather than to a chain.
- The `ollama` service and its image can leave `docker-compose.yml` for good,
  which is the largest image in the file.

**Harder**

- The §7 critical-recall target now rests on OpenAI's availability, and this
  ADR is the only place that says so.
- CLAUDE.md's "sıfır altyapı maliyeti" claim (§1) loses its last hedge. The
  project runs on a paid API and nothing local stands behind it.

**Follow-ups — shared files, not this PR**

| Change | File | Owner |
| --- | --- | --- |
| Remove the FALLBACK block (`GROQ_API_KEY`, `GEMINI_API_KEY`, `LLM_MODEL_*_GROQ`, `LLM_MODEL_GEMINI`, `LLM_MODEL_OLLAMA_*`) | `.env.example` | @Cagri12345, per §5 section ownership |
| Remove the `ollama` service and `OLLAMA_HOST` | `docker-compose.yml` | @bariss9 / @nursenakyga |
| §2: describe one OpenAI client, not a triple router. §4: drop "her LLM çağrısı `worker/llm_router` üzerinden" | `CLAUDE.md` | @bariss9 |
| Close "çalışan fallback katmanı"; record the accepted risk | `docs/STATUS.md` | @Cagri12345 |

@nursenakyga and @bariss9 raised the fallback question in ADR-001 and this
closes it without them, so it belongs in a standup before the follow-ups land.
