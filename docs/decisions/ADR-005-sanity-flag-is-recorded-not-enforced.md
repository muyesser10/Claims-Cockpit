# ADR-005: The masking sanity flag is recorded, not enforced

**Date:** 2026-08-19
**Status:** Accepted

## Context

`worker/routing/auto_approve.py` shipped with four fixed rejections — not
thresholds, not tunable. One of them was the masking sanity flag: if the LLM
sanity pass suspected the masked text still held personal data, the claim went
to a human, full stop. The reasoning was written down and was reasonable at the
time: a suspicion of leaked PII is exactly the kind of thing a person should
look at.

It was reasonable because the flag had never been measured. It has been now.

**The flag does not separate anything.** Measured 2026-08-18 over a class-balanced
sample (`eval/sanity_recall.py`, n=80): 40 records with a real leak, 40 clean.

| | flagged | not flagged |
| --- | --- | --- |
| leaking (40) | 40 | 0 |
| clean (40) | 40 | 0 |

Recall 100%, and precision at chance. `masking_sanity_v2` was written to fix
this; it corrected the *kinds* it reported (address 20→10, phone 14→5) and
changed the decision on zero records — the same 80/80. On the real database the
pass flags **148 of 150** claims. This is not a defect in a prompt, it is what
`prompts/masking_sanity_v1.txt` rule 4 asks for: flagging on suspicion, because
"yanlış pozitif vermek, kaçırmaktan daha güvenlidir". A layer built to
over-report is a good tripwire and a useless gate.

**As a gate it therefore withheld everything.** The gate's measured coverage is
71/100 at 97.2% precision (`eval/results/gate_v3.json`, `classification_v3` +
`extraction_v1`). Honouring a flag that fires on 148 of 150 claims takes that to
roughly 1%. `eval/gate.py`'s own docstring already named this failure mode: a
gate that approves two claims in a hundred can hit any precision target you like
and has automated nothing. The §7 auto-approval row was being reported as a
counterfactual — the number the gate *would* reach if the flag were off — because
the real number was not worth reporting.

**And the human it routed to was not shown the flag.** Nothing in `web/src/` or
`api/` reads `masking_sanity_flags`; the Kuyruk detail panel gives the operator
no indication that masking was suspected of leaking. So the rule did not buy a
review, it bought a delay. The same argument had already been accepted twice:
`step_extract` and `step_embed` both stopped honouring the flag (see the comment
in `worker/pipeline.py`), on the grounds that by the time a flag exists the text
has already gone to the model and is already on screen — skipping work removed
the claim's fields without removing the leak. The gate was the last holdout, and
that comment named it as the deliberate home for the flag's remaining teeth.
That sentence was written before the flag was measured.

## Decision

The masking sanity flag no longer blocks auto-approval. It is recorded on the
decision as an **advisory flag**, so it reaches the audit row and the error
centre exactly as before, and it holds nothing back.

`evaluate(..., sanity_blocks=True)` restores the old gate, and `eval.gate.measure`
sweeps it. The counterfactual is kept measurable rather than deleted: the day the
flag discriminates again, reopening this decision is a run, not a rewrite. A run
that never measured the flag now raises rather than assuming `False` — the silent
assumption is how two committed §7 rows became unlabelled counterfactuals.

This does **not** open the gate. `AUTO_APPROVE_ENABLED` stays `false`. Measured
precision is 97.2% with a one-sided 95% lower bound of 91.4% at n=71, so §7's
≥95% target is met by the point estimate and cannot be demonstrated at this
sample width. Opening the gate is a separate decision needing a wider sample.

## Alternatives considered

| Alternative | Pro | Con |
| --- | --- | --- |
| Leave the fixed rejection | Keeps a PII suspicion in front of a human | The human is never shown it; coverage ~1%, so the gate is off in all but name and §7's row stays a counterfactual indefinitely |
| Move it into `ADVISORY_RULES` | Uses the existing sweep mechanism | Mechanically not possible — `has_sanity_flags` is a separate parameter, not a validation rule name flowing through `split_flags`. And the advisory set is a dead lever on this corpus: `strict`, `shipped` and `shipped+injury_keyword_mismatch` all measure 71/100 at 97.2%, because only one validation rule fires at all |
| Filter the flag by reported kind | Would keep some signal | Measured and rejected: all 354 real leaks in the corpus are names, and v2 showed the reported kinds move without the decision moving |
| Fix the prompt first | Addresses the cause, not the symptom | Two prompt versions, same 80/80. The cause is not the prompt — it is a name dictionary with stub surnames |
| Show the flag in the Kuyruk panel, keep it blocking | Would make "a human looks at it" true | Frontend work we do not own, and it does not fix coverage: 148 of 150 claims would still be withheld |

## Consequences

**Easier.** The §7 auto-approval row becomes a real measurement instead of a
counterfactual. The advisory-set sweep now measures something that can move.
The gate becomes a thing that can be opened on evidence rather than a rule that
guarantees it never will be.

**Harder — and this is the cost to state plainly.** There is now no second line
of defence against a masking miss. The sanity layer was never one in practice
(it flagged everything, so it distinguished nothing), but it was one on paper,
and this ADR removes the paper. The only real protection is the name dictionary,
whose surname list is still a stub — @muyesser10's `surname-dictionary` PR
(~360 surnames, 1554→1915) is the fix, and masking recall must be re-measured
against the holdout lists once it lands. Until then §7's masking recall row
(82.2%) is the honest statement of the exposure, and this ADR does not change
it in either direction.

**Unchanged.** `check_sanity` still runs, still writes `masking_sanity_flags` to
`claim.data` as kind+location (never raw text), still costs one cheap call per
message. The flag remains visible to the error centre. Nothing about what the
system *knows* changed here — only what it does with it.
