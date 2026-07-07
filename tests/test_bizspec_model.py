"""The BizSpec IR (Wave 4 §11) — Language 2, the contract Hermes emits and the compiler consumes. The
model keeps effects (UseStep, a capability Skill) and control flow (ControlStep) distinct (D4), and
refuses a `use` that names a verb rather than a skill (verbs are private).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nilscript.bizspec import BizSpec, BizSpecPolicies, ControlStep, UseStep


def _spec(steps, *, domain="Procurement", intent="reorder low stock") -> BizSpec:
    return BizSpec(nil="bizspec/0.1", domain_id=domain, intent=intent, steps=tuple(steps))


# ── UseStep (effects) ─────────────────────────────────────────────────────────────────────────────
def test_use_step_names_a_skill() -> None:
    s = UseStep(use="Communication.send", args={"to": "$vendor"}, bind="msg")
    assert s.use == "Communication.send" and s.bind == "msg"


def test_use_step_rejects_a_bare_name() -> None:
    # Shape check only: a `use` must be dotted `Alias.skill`. Whether it names a REAL skill (vs a
    # private verb) is enforced at compile time by resolve_skill, not by the IR model.
    with pytest.raises(ValidationError, match="Alias.skill"):
        UseStep(use="send")


# ── ControlStep (control flow, D4) ────────────────────────────────────────────────────────────────
def test_approval_needs_a_strategy() -> None:
    with pytest.raises(ValidationError, match="approval control step needs a strategy"):
        ControlStep(control="approval")


def test_wait_needs_an_event() -> None:
    with pytest.raises(ValidationError, match="wait control step needs an event"):
        ControlStep(control="wait")


def test_valid_control_steps() -> None:
    assert ControlStep(control="approval", strategy="OwnerApprove").strategy == "OwnerApprove"
    assert ControlStep(control="wait", event="invoice.paid").event == "invoice.paid"
    assert ControlStep(control="checkpoint", to="ordered").to == "ordered"


# ── BizSpec ───────────────────────────────────────────────────────────────────────────────────────
def test_bizspec_mixes_effects_and_control() -> None:
    spec = _spec([
        UseStep(use="Inventory.check", args={"sku": "$sku"}),
        ControlStep(control="approval", strategy="OwnerApprove"),
        UseStep(use="Procurement.createPO", args={"sku": "$sku"}, bind="po"),
        UseStep(use="Communication.send", args={"to": "$vendor"}, via="email"),
    ])
    assert len(spec.steps) == 4
    assert isinstance(spec.steps[0], UseStep) and isinstance(spec.steps[1], ControlStep)
    assert spec.steps[3].via == "email"


def test_bizspec_requires_at_least_one_step() -> None:
    with pytest.raises(ValidationError, match="at least one step"):
        _spec([])


def test_bizspec_policies_default_and_set() -> None:
    assert _spec([UseStep(use="Inventory.check")]).policies == BizSpecPolicies()
    spec = BizSpec(
        nil="bizspec/0.1", domain_id="Finance", intent="pay",
        steps=(UseStep(use="Payments.pay"),),
        policies=BizSpecPolicies(tier_floor="HIGH", sod_preparer_not_approver=True),
    )
    assert spec.policies.tier_floor == "HIGH" and spec.policies.sod_preparer_not_approver
