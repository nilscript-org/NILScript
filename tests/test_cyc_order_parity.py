"""Wave 4 §14.5b — the parity proof. Expresses the LIVE cyc_order (pulled from the control plane; see
docs/WAVE-4-CYC-ORDER-MIGRATION.md) on the new Domain/Skill/BizSpec/compiler stack and asserts the
compiled+lowered flow reproduces its execution SEMANTICS: the same effect verbs in the same order, the
same two human gates, the same event-wait with its 7-day escalation. This is the milestone — the new
architecture can represent a real production cycle with no runtime concepts in the business layer.

Live cyc_order pipeline (wosool/0.1):
  step_1 action  resource.read
  step_2 await_approval
  step_3 wait    mail.received {order_ref:$po}  7d  on_timeout->step_5  next->step_4
  step_4 action  procurement.create_purchase_invoice
  step_5 notify  escalate (the timeout branch)
  step_6 await_approval
  step_7 action  commerce.record_payment
  step_8 notify
"""

from __future__ import annotations

from nilscript.bizspec import BizSpec, ControlStep, UseStep
from nilscript.capability import Capability, GovernanceEnvelope, Skill
from nilscript.compiler import compile_bizspec, lower_to_flow
from nilscript.cycle.models import ActionStep, ApprovalStep, NotifyStep, WaitForEventStep
from nilscript.domain import BackendBinding, CapabilityImport, Domain


def _skill(name, verb, tier):
    return Skill(name=name, intent={"en": name, "ar": name}, resolves_to=(verb,),
                 envelope=GovernanceEnvelope(tier=tier, reversibility="IRREVERSIBLE", effects=(verb,)))


def _cap(cid, version, risk, skill):
    return Capability(nil="capability/0.1", capability_id=cid, workspace="ws_acme", version=version,
                      domain="Procurement", owner_role="Procurement", intent={"en": cid, "ar": cid},
                      risk=risk, strategy="OwnerApprove", skills=(skill,),
                      implemented_by={"default": f"{cid}Cycle"})


# The three capabilities cyc_order's verbs live under, each exposing one Skill.
REGISTRY = [
    _cap("Resource", "1.0", "LOW", _skill("read", "resource.read", "LOW")),
    _cap("Procurement", "1.0", "HIGH", _skill("createPurchaseInvoice", "procurement.create_purchase_invoice", "HIGH")),
    _cap("Commerce", "1.0", "HIGH", _skill("recordPayment", "commerce.record_payment", "HIGH")),
]

# The Procurement Domain: imports the three capabilities, binds each to Odoo (D8 — explicit, was implicit).
DOMAIN = Domain(nil="domain/0.1", domain_id="Procurement", workspace="ws_acme",
                imports=(CapabilityImport(capability="Resource", major=1, alias="resource"),
                         CapabilityImport(capability="Procurement", major=1, alias="proc"),
                         CapabilityImport(capability="Commerce", major=1, alias="commerce")),
                bindings=(BackendBinding(capability="Resource", backend="odoo"),
                          BackendBinding(capability="Procurement", backend="odoo"),
                          BackendBinding(capability="Commerce", backend="odoo")))

# cyc_order expressed as a BizSpec — business language only, no step ids, no routing.
CYC_ORDER = BizSpec(nil="bizspec/0.1", domain_id="Procurement", intent="procure to pay", steps=(
    UseStep(use="resource.read", bind="po"),
    ControlStep(control="approval", strategy="OwnerApprove"),
    ControlStep(control="wait", event="mail.received", match={"order_ref": "$po"},
                timeout_seconds=604800,
                escalate={"en": "Escalate: supplier silent 7 days", "ar": "تصعيد: لا رد من المورد خلال ٧ أيام"}),
    UseStep(use="proc.createPurchaseInvoice"),
    ControlStep(control="approval", strategy="OwnerApprove"),
    UseStep(use="commerce.recordPayment"),
    ControlStep(control="notify", message={"en": "Update GIT + notify logistics", "ar": "تحديث البضاعة بالطريق"}),
))


def _flow():
    return lower_to_flow(compile_bizspec(CYC_ORDER, DOMAIN, REGISTRY))


def test_parity_effect_verbs_match_in_order() -> None:
    verbs = [s.use for s in _flow().steps if isinstance(s, ActionStep)]
    assert verbs == ["resource.read", "procurement.create_purchase_invoice", "commerce.record_payment"]


def test_parity_two_human_gates() -> None:
    assert sum(isinstance(s, ApprovalStep) for s in _flow().steps) == 2


def test_parity_event_wait_with_correlation_and_escalation() -> None:
    flow = _flow()
    wait = next(s for s in flow.steps if isinstance(s, WaitForEventStep))
    assert wait.on_event == "mail.received"
    assert wait.match == {"order_ref": "$po"}
    assert wait.timeout_seconds == 604800
    # The 7-day supplier-silence branch: timeout routes to a distinct escalation notify (emit + halt).
    esc = next(s for s in flow.steps if s.id == wait.on_timeout)
    assert isinstance(esc, NotifyStep) and esc.next is None
    assert "supplier silent" in esc.message.en


def test_parity_governance_envelope_is_high_irreversible() -> None:
    # The strongest tier across the effects (Procurement/Commerce are HIGH), matching the live cycle's
    # human-gated, irreversible character.
    plan = compile_bizspec(CYC_ORDER, DOMAIN, REGISTRY)
    assert plan.envelope.tier == "HIGH"
    assert plan.envelope.reversibility == "IRREVERSIBLE"
    assert plan.envelope.effects == (
        "commerce.record_payment", "procurement.create_purchase_invoice", "resource.read",
    )


def test_parity_backends_are_explicitly_bound_D8() -> None:
    # An IMPROVEMENT over the live cycle, not a break: every effect now carries its governed backend
    # (was implicit newest-declarer-wins). Odoo on all three.
    plan = compile_bizspec(CYC_ORDER, DOMAIN, REGISTRY)
    assert {s.backend for s in plan.steps if s.kind == "effect"} == {"odoo"}


def test_parity_lowered_flow_is_runnable_nil() -> None:
    from nilscript.cycle import Cycle, parse_nil, print_nil

    cycle = Cycle.model_validate({
        "nil": "cycle/0.3",  # wait_for_event is a v0.3 construct
        "cycle_id": "CycOrder", "workspace": "ws_acme",
        "metadata": {"version": "1.0.0", "owner": "Procurement"},
        "intent": {"en": "procure to pay", "ar": "الشراء حتى الدفع"},
        "trigger": {"type": "manual"},
        "flow": _flow().model_dump(by_alias=True),
    })
    assert parse_nil(print_nil(cycle)) == cycle


def test_parity_backend_bindings_resolved_D8() -> None:
    # Verify backend bindings are extracted from the Domain and included in CompiledPlan (D8)
    plan = compile_bizspec(CYC_ORDER, DOMAIN, REGISTRY)
    assert "Resource" in plan.backend_bindings
    assert "Procurement" in plan.backend_bindings
    assert "Commerce" in plan.backend_bindings
    assert plan.backend_bindings == {"Resource": "odoo", "Procurement": "odoo", "Commerce": "odoo"}
