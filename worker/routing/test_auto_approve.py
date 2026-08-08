# worker/routing/test_auto_approve.py
"""Tests for the auto-approval gate.

A pure function, so these are unit tests with no database and no network. The
pipeline side - that an approved claim actually lands on `approved` and that an
audit row is written either way - is covered in worker/test_pipeline.py.
"""

from worker.routing.auto_approve import (
    ADVISORY_RULES,
    REASON_BLOCKING_FLAGS,
    REASON_CRITICAL,
    REASON_DISABLED,
    REASON_NO_EXTRACTION,
    REASON_NOT_A_CLAIM,
    REASON_SANITY_FLAG,
    REASON_UNVERIFIED_FIELDS,
    evaluate,
    is_enabled,
    split_flags,
)


def _flag(rule: str, field: str = "plate") -> dict:
    return {"field": field, "rule": rule, "message": "test"}


def _evaluate(**kwargs):
    """A claim that passes everything, with individual facts overridden."""
    defaults = {
        "content_type": "claim",
        "urgency": "normal",
        "validation_flags": [],
        "unverified_fields": [],
        "has_sanity_flags": False,
        "extraction_present": True,
        "enabled": True,
    }
    return evaluate(**{**defaults, **kwargs})


# --- the feature flag ----------------------------------------------------


def test_the_gate_is_off_unless_it_is_switched_on(monkeypatch):
    """Opposite default to MASKING_SANITY_ENABLED: skipping that one removes a
    protection, enabling this one removes a human."""
    monkeypatch.delenv("AUTO_APPROVE_ENABLED", raising=False)

    assert is_enabled() is False


def test_the_flag_accepts_the_usual_spellings(monkeypatch):
    for value in ("true", "TRUE", "1", "yes", "on"):
        monkeypatch.setenv("AUTO_APPROVE_ENABLED", value)
        assert is_enabled() is True, value

    for value in ("false", "0", "no", "", "maybe"):
        monkeypatch.setenv("AUTO_APPROVE_ENABLED", value)
        assert is_enabled() is False, value


def test_a_disabled_gate_approves_nothing_however_clean(monkeypatch):
    decision = _evaluate(enabled=False)

    assert decision.approved is False
    assert decision.reasons == [REASON_DISABLED]


# --- the happy path ------------------------------------------------------


def test_a_clean_claim_is_approved():
    decision = _evaluate()

    assert decision.approved is True
    assert decision.reasons == []


def test_an_advisory_flag_alone_does_not_hold_a_claim_back():
    # POL-YYYY-NNNNN is a shape the generator invented; a real policy number
    # would be flagged for being correct.
    decision = _evaluate(validation_flags=[_flag("invalid_policy_no_format", "policy_no")])

    assert decision.approved is True
    assert decision.advisory_flags == ["invalid_policy_no_format"]
    assert decision.blocking_flags == []


# --- the four that are not thresholds ------------------------------------


def test_a_critical_claim_always_reaches_a_person():
    """Sorting an injury report to the front of the queue is the reason this
    system exists; one that skips the queue entirely defeats it."""
    decision = _evaluate(urgency="critical")

    assert decision.approved is False
    assert REASON_CRITICAL in decision.reasons


def test_a_possible_pii_leak_is_never_approved():
    decision = _evaluate(has_sanity_flags=True)

    assert decision.approved is False
    assert REASON_SANITY_FLAG in decision.reasons


def test_only_claims_are_approved():
    for content_type in ("info_request", "irrelevant", None):
        decision = _evaluate(content_type=content_type)

        assert decision.approved is False, content_type
        assert REASON_NOT_A_CLAIM in decision.reasons


def test_nothing_extracted_means_nothing_to_have_got_right():
    decision = _evaluate(extraction_present=False)

    assert decision.approved is False
    assert REASON_NO_EXTRACTION in decision.reasons


# --- the two flag-driven refusals ----------------------------------------


def test_a_blocking_validation_flag_holds_the_claim():
    decision = _evaluate(validation_flags=[_flag("invalid_plate_format")])

    assert decision.approved is False
    assert decision.reasons == [REASON_BLOCKING_FLAGS]
    assert decision.blocking_flags == ["invalid_plate_format"]


def test_an_unverified_field_holds_the_claim():
    """The failure auto-approval would be blamed for: every field well-formed,
    one of them invented. No validation rule can see it."""
    decision = _evaluate(unverified_fields=["estimated_amount"])

    assert decision.approved is False
    assert decision.reasons == [REASON_UNVERIFIED_FIELDS]


# --- reporting -----------------------------------------------------------


def test_every_applicable_reason_is_listed_not_just_the_first():
    decision = _evaluate(
        urgency="critical",
        has_sanity_flags=True,
        validation_flags=[_flag("future_incident_date", "incident_date")],
    )

    assert REASON_CRITICAL in decision.reasons
    assert REASON_SANITY_FLAG in decision.reasons
    assert REASON_BLOCKING_FLAGS in decision.reasons


def test_one_rule_firing_on_two_fields_is_one_reason():
    decision = _evaluate(
        validation_flags=[
            _flag("invalid_date_format", "incident_date"),
            _flag("invalid_date_format", "other_date"),
        ]
    )

    assert decision.blocking_flags == ["invalid_date_format"]


def test_a_flag_without_a_rule_is_ignored_rather_than_crashing():
    blocking, advisory = split_flags([{"field": "plate", "message": "test"}])

    assert blocking == []
    assert advisory == []


# --- the advisory set is a parameter, because moving a rule is a measurement --


def test_the_advisory_set_can_be_swept():
    """`advisory_rules` is injectable so an eval run can put candidate sets
    against ground truth and read a precision number off each one, rather than
    editing this module to try a variant."""
    flags = [_flag("invalid_plate_format")]

    strict = _evaluate(validation_flags=flags)
    lenient = _evaluate(validation_flags=flags, advisory_rules=frozenset({"invalid_plate_format"}))

    assert strict.approved is False
    assert lenient.approved is True


def test_the_shipped_advisory_set_stays_small():
    """A guard against the set quietly growing: every entry beyond the known
    synthetic-format noise is a claim about the system that needs a run behind
    it."""
    assert ADVISORY_RULES == frozenset({"invalid_policy_no_format"})
