# ADR-004: Running on one provider, with the fallback left possible

**Date:** 2026-08-17
**Status:** Accepted

## Context

CLAUDE.md §2 describes a zero-cost triple router — Groq → Gemini → Ollama,
falling through on 429 or error. ADR-001 replaced it with a single OpenAI
client, kept the other providers configured, and deliberately did not settle
what happens next:

> A working fallback layer (OpenAI fails → Groq/Gemini) is **not implemented**.
> Only the configuration is preserved. Whether to build one is a separate
> decision; raised by @nursenakyga and @bariss9 and left open here.

Three weeks later nothing has been built, and `docs/STATUS.md` still lists
"çalışan fallback katmanı" among the things that have not been done yet — as
though it were work waiting for a free afternoon. It is not: nobody has
committed to it and nobody has ruled it out. This ADR does not change what the
code does. It changes an unowned to-do into a decision with a number attached.

Two things are known now that were not known when ADR-001 was written.

**The exposure has a number.** Measured 2026-08-17 over
`eval/fixtures/injury_phrasings.jsonl` (44 hard positives — the phrasings the
corpus does not contain): the pipeline reaches 86.4% critical recall with the
model and **20.5% (9/44) without it**. The deterministic layer catches a
canonical injury term and little else. So "OpenAI is unreachable" means four of
every five injury phrasings the system currently catches would be missed. That
is the risk this ADR is about, in the only units that matter.

**The demo-day failure mode has a different mitigation.** `DEMO_OFFLINE` (S4-6)
plays recorded fixtures through the real code path, so a network failure during
the final demo no longer needs a second provider behind it. When ADR-001 was
written that path did not exist, and "the demo dies without a fallback" was a
live argument. It no longer is.

## Decision

**We run on OpenAI alone and do not build the fallback now. The configuration
ADR-001 preserved stays preserved.**

Nothing is removed. `GROQ_API_KEY`, `GEMINI_API_KEY`, `OLLAMA_HOST` and the
`LLM_MODEL_*` variants stay in `.env.example` under the FALLBACK heading, and
the `ollama` service stays in `docker-compose.yml` behind its `fallback`
profile. The team holds one key, for OpenAI, and that is the whole of what runs.

What this ADR adds is not a code change but a closed question: the fallback is
*not pending work*. It is a measured, accepted risk with a stated trigger for
reopening.

What already stands between an outage and a lost claim, none of which is a
second provider:

- `instructor` re-asks when the answer does not fit the schema
  (`LLM_MAX_RETRIES`, default 2).
- The OpenAI SDK retries transient failures (`LLM_SDK_MAX_RETRIES`, default 1).
- `fallback_classification()` triages on injury terms alone when the
  classification call fails, and the message is **not** dead-lettered — a claim
  is never lost to an LLM outage, only triaged worse.
- `DEMO_OFFLINE` answers from recorded fixtures.

### Why not build it now

Two of ADR-001's three objections still hold in full. A mid-run fallback makes
an eval number unreadable — a run where some calls silently fell through to a
weaker model measures nothing in particular. And open-weight models hallucinate
more on this task, which is the failure mode the whole design exists to
suppress; on the injury path a weaker model does not trade a missed injury for
nothing, it trades it for a wrong one.

The third objection — three JSON dialects — has weakened. Groq, Gemini and
Ollama all now expose OpenAI-compatible endpoints, so a fallback could run
through the same SDK on a different `base_url` with no new dependency. The work
is smaller than ADR-001 assumed. That is worth recording, because it is the
argument someone will reach for when reopening this.

What decides it today is that no second key exists on the team. A fallback
written now could not be exercised even once, let alone scored on the injury
fixture — and shipping an untried failure path is exactly what ADR-001
criticised about the original router: "The decision was on paper only." A
fallback that has never fired successfully is not a fallback.

### Why not close the door either

Keeping the configuration costs five environment lines and a compose service
that is already behind a profile and never starts. Removing it would buy tidiness
and charge a future decision the price of rediscovering which models and hosts
were meant to go where. The door stays open at approximately no cost, so it
stays open.

## Accepted risk

Critical recall — CLAUDE.md §7's ≥97% target, the one metric whose failure mode
is a missed injury — depends on a single vendor being reachable.

| | with the model | deterministic only |
| --- | ---: | ---: |
| Critical recall, hard fixture (n=44) | 86.4% | 20.5% |

Bounded by three things. A claim carrying a canonical injury word still reaches
`critical` with no model at all, so the plainest cases survive. Nothing is
dropped: classification failure falls back to terms and the message stays in the
queue. And every claim still lands in front of a human, because the
auto-approval gate ships closed (`AUTO_APPROVE_ENABLED=false`).

**What reopens this:** a real deployment against non-synthetic traffic, or a
second provider key. The second is the cheap one — obtaining a Groq key is free
and the endpoint is OpenAI-compatible, so the work is a `base_url`, an error
classifier that separates availability failures from schema failures, and a
scored run of `python -m eval.injury_recall --live` against the fallback model
so the degradation is known rather than assumed.

## Alternatives considered

| Alternative | Pro | Con |
| --- | --- | --- |
| Run on OpenAI, keep the config, build nothing (chosen) | Every eval number attributable to one model; nothing untested ships; reopening stays cheap | Critical recall depends on one vendor: 86.4% → 20.5% if OpenAI is unreachable |
| Build OpenAI → Groq on availability errors | OpenAI-compatible endpoint, so no new dependency and one JSON dialect | No key on the team, so it could not be exercised or scored before shipping; a weaker model on the injury path trades a missed injury for a wrong one |
| Build the mechanism and leave it dormant | Proves the code path; adding a provider later is config only | A branch that never executes is a branch nobody trusts; it would still be unscored, and the first time it fires would be in front of a user |
| Remove the config and close the question | Tidier `.env.example`; one less dead service in compose | Charges a future decision the cost of rediscovering the model names and hosts, to save five lines |
| Revive Ollama as the second provider | Genuinely independent; no key needed; offline | Service is dead since ADR-001 and behind a compose profile; needs a model pull and is slow without a GPU; ADR-001 measured its Turkish quality as well below cloud |

## Consequences

**Easier**

- `docs/STATUS.md` stops carrying an item nobody owns. The question has an
  answer, a number, and a trigger.
- One provider means one JSON dialect, one retry policy, and every §7 number
  attributable to a single model rather than to a chain.

**Harder**

- The §7 critical-recall target rests on OpenAI's availability, and this ADR is
  the only place that says so with a figure.
- CLAUDE.md's "sıfır altyapı maliyeti" claim (§1) keeps its last hedge only on
  paper: the fallback config exists, but nothing local stands behind the
  running system.

**Follow-ups**

| Change | File | Owner |
| --- | --- | --- |
| Reword "çalışan fallback katmanı" from outstanding work to a decision, and record the accepted risk | `docs/STATUS.md` | @Cagri12345 |
| §2 describes a triple router as the architecture, and §4 requires every call to go through `worker/llm_router`, which does not exist. Both need to describe the single client — the fallback config can be mentioned as reserved | `CLAUDE.md` | @bariss9 |

`.env.example` and `docker-compose.yml` need **no** change: the configuration
and the profiled-out `ollama` service are deliberately retained.

@nursenakyga and @bariss9 raised the fallback question in ADR-001 and this
answers it without them, so it belongs in a standup before the follow-ups land.
