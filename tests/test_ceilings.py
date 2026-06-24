"""Approval ceilings — the minimal slice of parametric policy: a numeric arg over a per-merchant cap
floors the proposal's tier to HIGH so it parks for a human DECIDE. Not a policy engine; a guard the
adapter declares per money-moving verb (e.g. refunds/payouts above SAR 500 always need approval)."""

from nilscript.sdk.ceilings import exceeds_ceiling, floor_tier

CEILINGS = {"commerce.refund": {"amount": 500}, "commerce.payout": {"amount": 1000}}


def test_over_cap_returns_breached_arg():
    assert exceeds_ceiling("commerce.refund", {"amount": 750}, CEILINGS) == "amount"


def test_at_or_under_cap_passes():
    assert exceeds_ceiling("commerce.refund", {"amount": 500}, CEILINGS) is None
    assert exceeds_ceiling("commerce.refund", {"amount": 12}, CEILINGS) is None


def test_string_amount_is_coerced():
    assert exceeds_ceiling("commerce.refund", {"amount": "750.00"}, CEILINGS) == "amount"


def test_unconfigured_verb_or_missing_arg_passes():
    assert exceeds_ceiling("crm.update_contact", {"amount": 9999}, CEILINGS) is None
    assert exceeds_ceiling("commerce.refund", {}, CEILINGS) is None


def test_non_numeric_value_does_not_falsely_breach():
    assert exceeds_ceiling("commerce.refund", {"amount": "lots"}, CEILINGS) is None


def test_floor_tier_only_raises_never_lowers():
    assert floor_tier("LOW") == "HIGH"
    assert floor_tier("MEDIUM") == "HIGH"
    assert floor_tier("CRITICAL") == "CRITICAL"  # never demote a stricter tier
    assert floor_tier("HIGH") == "HIGH"
