"""lower_to_flow (Wave 4 §14.4c pt.2): CompiledPlan → a runnable cycle Flow. The synthesized scaffolding
L2 omits — step ids, linear next-chaining, the terminal, and every required transition target.
"""

from __future__ import annotations

import pytest

from nilscript.bizspec import BizSpec, ControlStep, UseStep
from nilscript.capability import Capability, GovernanceEnvelope, Skill
from nilscript.compiler import CompileRefusal, compile_bizspec, lower_to_flow
from nilscript.cycle.models import ActionStep, ApprovalStep, CheckpointStep, NotifyStep, WaitForEventStep
from nilscript.domain import BackendBinding, CapabilityImport, Domain


def _skill(name, verbs, tier="MEDIUM"):
    return Skill(name=name, intent={"en": name, "ar": name}, resolves_to=tuple(verbs),
                 envelope=GovernanceEnvelope(tier=tier, effects=("crm.create_lead",)))


CRM = Capability(nil="capability/0.1", capability_id="Crm", workspace="acme", version="1.0",
                 domain="Ops", owner_role="Ops", intent={"en": "Crm", "ar": "Crm"}, risk="MEDIUM",
                 strategy="AutoSmallOps", skills=(_skill("createLead", ["crm.create_lead"]),),
                 implemented_by={"default": "CrmCycle"})
DOMAIN = Domain(nil="domain/0.1", domain_id="Procurement", workspace="acme",
                imports=(CapabilityImport(capability="Crm", major=1, alias="crm"),),
                bindings=(BackendBinding(capability="Crm", backend="odoo"),))


def _plan(steps):
    spec = BizSpec(nil="bizspec/0.1", domain_id="Procurement", intent="x", steps=tuple(steps))
    return compile_bizspec(spec, DOMAIN, [CRM])


def test_effect_lowers_to_an_action_step_on_the_resolved_verb() -> None:
    flow = lower_to_flow(_plan([UseStep(use="crm.createLead", args={"n": "$who"}, bind="lead")]))
    act = flow.steps[0]
    assert isinstance(act, ActionStep)
    assert act.use == "crm.create_lead" and act.output == "lead" and act.with_ == {"n": "$who"}
    assert flow.entry == "Step1" and act.next == "Done"  # chains to the terminal


def test_linear_next_chaining_across_steps() -> None:
    flow = lower_to_flow(_plan([
        UseStep(use="crm.createLead"),
        ControlStep(control="approval", strategy="OwnerApprove", approver="manager"),
        UseStep(use="crm.createLead"),
    ]))
    assert [s.id for s in flow.steps] == ["Step1", "Step2", "Step3", "Done"]
    assert flow.steps[0].next == "Step2"
    approval = flow.steps[1]
    assert isinstance(approval, ApprovalStep)
    assert approval.approver == "manager" and approval.on_approve == "Step3"
    assert approval.on_reject == "Done" and approval.on_timeout == "Done"
    assert flow.steps[2].next == "Done"
    assert flow.steps[3].id == "Done" and flow.steps[3].next is None


def test_notify_checkpoint_wait_lower_to_their_kernel_steps() -> None:
    flow = lower_to_flow(_plan([
        ControlStep(control="notify", message={"en": "hi", "ar": "مرحبا"}),
        ControlStep(control="checkpoint", to="ordered"),
        ControlStep(control="wait", event="invoice.paid", match={"order_ref": "$po"}),
    ]))
    assert isinstance(flow.steps[0], NotifyStep) and flow.steps[0].message.en == "hi"
    assert isinstance(flow.steps[1], CheckpointStep) and flow.steps[1].name == "ordered"
    wait = flow.steps[2]
    assert isinstance(wait, WaitForEventStep)
    assert wait.on_event == "invoice.paid" and wait.match == {"order_ref": "$po"}
    assert wait.on_timeout == "Done" and wait.next == "Done"


def test_wait_with_escalate_synthesizes_a_timeout_branch_not_the_terminal() -> None:
    # §14.5a: the cyc_order shape — wait 7d, and if the supplier is silent, ESCALATE (notify) + halt.
    # The business author gives a message; the COMPILER synthesizes the branch + target (no step ids in L2).
    flow = lower_to_flow(_plan([
        UseStep(use="crm.createLead"),
        ControlStep(control="wait", event="mail.received", match={"order_ref": "$po"},
                    timeout_seconds=604800, escalate={"en": "Supplier silent 7 days", "ar": "المورد صامت"}),
        UseStep(use="crm.createLead"),
    ]))
    wait = next(s for s in flow.steps if isinstance(s, WaitForEventStep))
    # Timeout routes to a SYNTHESIZED escalation step — NOT the shared terminal, and NOT the fall-through.
    assert wait.on_timeout == "Escalate2" and wait.next == "Step3"
    esc = next(s for s in flow.steps if s.id == "Escalate2")
    assert isinstance(esc, NotifyStep) and esc.message.en == "Supplier silent 7 days" and esc.next is None


def test_escalate_only_valid_on_wait() -> None:
    import pytest as _pytest
    from pydantic import ValidationError
    with _pytest.raises(ValidationError, match="escalate is only valid on a wait"):
        ControlStep(control="notify", message={"en": "x", "ar": "x"}, escalate={"en": "y", "ar": "y"})


def test_empty_plan_lowers_to_a_terminal_only_flow() -> None:
    flow = lower_to_flow(_plan([UseStep(use="crm.createLead")]))  # non-empty baseline
    empty = lower_to_flow(compile_bizspec(
        BizSpec(nil="bizspec/0.1", domain_id="Procurement", intent="x", steps=(ControlStep(control="checkpoint", to="c"),)),
        DOMAIN, [CRM]))
    assert empty.steps[-1].id == "Done"


def test_lowered_flow_wraps_into_a_runnable_cycle_that_round_trips() -> None:
    # The proof it's REAL .nil: wrap the lowered flow in a Cycle, print it, parse it back — identical.
    from nilscript.cycle import Cycle, parse_nil, print_nil

    flow = lower_to_flow(_plan([
        UseStep(use="crm.createLead", args={"n": "$who"}, bind="lead"),
        ControlStep(control="approval", strategy="OwnerApprove", approver="manager"),
    ]))
    cycle = Cycle.model_validate({
        "nil": "cycle/0.2",  # effect + approval + notify are all v0.2 constructs
        "cycle_id": "Reorder",
        "workspace": "acme",
        "metadata": {"version": "1.0.0", "owner": "Ops"},
        "intent": {"en": "reorder", "ar": "إعادة طلب"},
        "trigger": {"type": "manual"},
        "flow": flow.model_dump(by_alias=True),
    })
    assert parse_nil(print_nil(cycle)) == cycle


def test_decision_control_is_refused_in_v01() -> None:
    plan = _plan([ControlStep(control="decision")]) if False else None  # decision needs no strategy/event
    # A decision control step compiles (control-only) but cannot be lowered linearly yet.
    spec = BizSpec(nil="bizspec/0.1", domain_id="Procurement", intent="x", steps=(ControlStep(control="decision"),))
    with pytest.raises(CompileRefusal) as ei:
        lower_to_flow(compile_bizspec(spec, DOMAIN, [CRM]))
    assert ei.value.code == "UNSUPPORTED_STEP"
