# worker/routing/auto_approve.py
"""Decides whether a claim may skip the human queue.

CLAUDE.md §2's state machine ends `validated → (auto_approved | in_human_review)`.
Only the second half was ever built: every claim went to a human, which is safe
but is not the system the design describes, and it left §7's "auto-approval
precision ≥ 95%" measuring a feature that did not exist.

A pure function over plain values rather than over a Claim. Two reasons: the
pipeline is not the only caller - an eval run has to be able to apply candidate
gates to ground-truth records without a database - and `advisory_rules` is a
parameter precisely so that sweeping it is a measurement, not a code change.

The gate ships closed. AUTO_APPROVE_ENABLED defaults to false, because a 95%
precision target cannot be met by a threshold nobody has measured, and the
corpus needed to measure it (data/ground_truth_enriched.jsonl) is right there.
Turning it on is a decision to be made from a number.
"""

import os

from pydantic import BaseModel

_ENV_TRUE_VALUES = {"1", "true", "yes", "on"}

# Validation rules that do not, on their own, need a human.
#
# Provisional and deliberately small: this set is what the measurement is for.
# `invalid_policy_no_format` is here because the flag is known noise rather than
# a finding - STATUS records that POL-YYYY-NNNNN is a synthetic shape the
# generator invented, so a claim carrying a real-world policy number would be
# flagged for being correct. Every other rule stays blocking until a precision
# number says otherwise; moving one out of blocking is a claim about the system
# that has to be backed by a run.
ADVISORY_RULES = frozenset({"invalid_policy_no_format"})

# Why a claim was held back. Machine-readable rather than prose: these land in
# the audit trail and are what the precision measurement groups by.
REASON_DISABLED = "auto_approve_disabled"
REASON_NOT_A_CLAIM = "not_a_claim"
REASON_CRITICAL = "critical_urgency"
REASON_SANITY_FLAG = "masking_sanity_flag"
REASON_NO_EXTRACTION = "no_extraction"
REASON_BLOCKING_FLAGS = "blocking_validation_flags"
REASON_UNVERIFIED_FIELDS = "unverified_fields"


class AutoApproveDecision(BaseModel):
    """The verdict, and enough of its reasoning to audit and to measure."""

    approved: bool
    # Empty when approved. Every applicable reason is listed, not just the first:
    # "this one was critical" and "this one was critical and had three blocking
    # flags" are different claims about how far the system was from approving it.
    reasons: list[str]
    blocking_flags: list[str]
    advisory_flags: list[str]


def is_enabled() -> bool:
    """Whether the gate may approve anything at all.

    Defaults to **off**, the opposite of MASKING_SANITY_ENABLED. That one
    defaults on because skipping it removes a protection; this one defaults off
    because enabling it removes a human.
    """
    value = os.environ.get("AUTO_APPROVE_ENABLED", "false").strip().lower()
    return value in _ENV_TRUE_VALUES


def split_flags(
    validation_flags: list[dict],
    advisory_rules: frozenset[str] = ADVISORY_RULES,
) -> tuple[list[str], list[str]]:
    """Separate the validation flags that block approval from those that do not.

    Reads the `rule` key, not `message`: the message is Turkish prose written for
    an operator and would tie this decision to how a sentence is phrased.
    Duplicates collapse - a rule firing on two fields is one reason.
    """
    blocking: list[str] = []
    advisory: list[str] = []
    for flag in validation_flags:
        rule = flag.get("rule")
        if rule is None:
            continue
        target = advisory if rule in advisory_rules else blocking
        if rule not in target:
            target.append(rule)
    return blocking, advisory


def evaluate(
    *,
    content_type: str | None,
    urgency: str | None,
    validation_flags: list[dict],
    unverified_fields: list[str],
    has_sanity_flags: bool,
    extraction_present: bool,
    enabled: bool | None = None,
    advisory_rules: frozenset[str] = ADVISORY_RULES,
) -> AutoApproveDecision:
    """Decide whether this claim may be approved without a human reading it.

    Four of the conditions are not thresholds and are not meant to become
    tunable:

    - A critical claim always reaches a person. Sorting an injury report to the
      front of the queue is the reason this system exists (CLAUDE.md §1); an
      injury report that skips the queue entirely defeats it, and §7 asks for
      ≥97% critical recall on exactly that case.
    - A masking-sanity flag means the text may still hold personal data. It is
      already enough to skip extraction; it is more than enough to require a
      human.
    - Only claims are approved. "Approving" an info_request means nothing, and
      archiving an irrelevant message is a separate decision nobody has taken.
    - Nothing was extracted, so there is nothing to have got right.

    `unverified_fields` blocks as well, and it is the one worth explaining. It
    holds the fields whose supporting quote could not be found in the source
    text - the hallucination check from design doc §3. A claim can carry no
    validation flag at all and still be wrong in exactly this way: every field
    well-formed, one of them invented. Approving it unread is the failure mode
    auto-approval would be blamed for.
    """
    enabled = is_enabled() if enabled is None else enabled
    blocking, advisory = split_flags(validation_flags, advisory_rules)

    reasons: list[str] = []
    if not enabled:
        reasons.append(REASON_DISABLED)
    if content_type != "claim":
        reasons.append(REASON_NOT_A_CLAIM)
    if urgency == "critical":
        reasons.append(REASON_CRITICAL)
    if has_sanity_flags:
        reasons.append(REASON_SANITY_FLAG)
    if not extraction_present:
        reasons.append(REASON_NO_EXTRACTION)
    if blocking:
        reasons.append(REASON_BLOCKING_FLAGS)
    if unverified_fields:
        reasons.append(REASON_UNVERIFIED_FIELDS)

    return AutoApproveDecision(
        approved=not reasons,
        reasons=reasons,
        blocking_flags=blocking,
        advisory_flags=advisory,
    )
