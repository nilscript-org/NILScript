"""The L2→L3 compiler (Wave 4 §10): BizSpec + Domain + registry → CompiledPlan. Deterministic, and it
REFUSES (never guesses) on any unresolved reference. Exercises the happy path (resolution through the
Domain, SemVer pin, verb + backend resolution, aggregate envelope) and every refusal code.
"""

from __future__ import annotations

import pytest

from nilscript.bizspec import BizSpec, BizSpecPolicies, ControlStep, UseStep
from nilscript.capability import Capability, GovernanceEnvelope, Skill
from nilscript.compiler import CompileRefusal, compile_bizspec
from nilscript.domain import BackendBinding, CapabilityImport, Domain


def _skill(name, verbs, tier="MEDIUM", effects=("comms.send_email",), rev="COMPENSABLE") -> Skill:
    return Skill(
        name=name, intent={"en": name, "ar": name}, resolves_to=tuple(verbs),
        envelope=GovernanceEnvelope(tier=tier, reversibility=rev, effects=tuple(effects)),
    )


def _cap(cid, version="2.0", *, risk="MEDIUM", skills=()) -> Capability:
    return Capability(
        nil="capability/0.1", capability_id=cid, workspace="acme", version=version,
        domain="Ops", owner_role="Ops", intent={"en": cid, "ar": cid},
        risk=risk, strategy="AutoSmallOps", skills=tuple(skills),
        implemented_by={"default": f"{cid}Cycle"},
    )


def _domain(imports=(), bindings=()) -> Domain:
    return Domain(nil="domain/0.1", domain_id="Procurement", workspace="acme",
                  imports=tuple(imports), bindings=tuple(bindings))


COMMS = _cap("Communication", "2.3", risk="LOW", skills=[
    _skill("send", ["comms.send_email", "comms.send_whatsapp"]),  # ambiguous without via
    _skill("notify", ["comms.send_email"], tier="LOW", effects=("comms.send_email",)),
])
CRM = _cap("Crm", "1.0", skills=[_skill("createLead", ["crm.create_lead"], tier="HIGH",
                                        effects=("crm.create_lead",), rev="IRREVERSIBLE")])
REGISTRY = [COMMS, CRM]

DOMAIN = _domain(
    imports=[CapabilityImport(capability="Communication", major=2, alias="comms"),
             CapabilityImport(capability="Crm", major=1, alias="crm")],
    bindings=[BackendBinding(capability="Communication", backend="smtp"),
              BackendBinding(capability="Crm", backend="odoo")],
)


def _spec(steps, domain="Procurement", policies=None):
    return BizSpec(nil="bizspec/0.1", domain=domain, intent="x", steps=tuple(steps),
                   policies=policies or BizSpecPolicies())


# ── Happy path ──────────────────────────────────────────────────────────────────────────────────
def test_compiles_effects_and_control_into_a_plan() -> None:
    plan = compile_bizspec(_spec([
        UseStep(use="crm.createLead", args={"name": "$who"}, bind="lead"),
        ControlStep(control="approval", strategy="OwnerApprove"),
        UseStep(use="comms.send", via="comms.send_whatsapp", args={"to": "$who"}),
    ]), DOMAIN, REGISTRY)

    assert [s.kind for s in plan.steps] == ["effect", "control", "effect"]
    lead = plan.steps[0]
    assert (lead.capability, lead.version, lead.verb, lead.backend, lead.tier) == \
        ("Crm", "1.0", "crm.create_lead", "odoo", "HIGH")
    assert plan.steps[2].verb == "comms.send_whatsapp" and plan.steps[2].backend == "smtp"
    assert plan.steps[1].control == "approval"


def test_aggregate_envelope_is_strongest_tier_union_effects_strongest_reversibility() -> None:
    plan = compile_bizspec(_spec([
        UseStep(use="comms.notify"),                                   # LOW, COMPENSABLE
        UseStep(use="crm.createLead"),                                 # HIGH, IRREVERSIBLE
    ]), DOMAIN, REGISTRY)
    assert plan.envelope.tier == "HIGH"
    assert plan.envelope.reversibility == "IRREVERSIBLE"
    assert plan.envelope.effects == ("comms.send_email", "crm.create_lead")


def test_policy_tier_floor_raises_a_low_plan() -> None:
    plan = compile_bizspec(_spec([UseStep(use="comms.notify")],
                                 policies=BizSpecPolicies(tier_floor="HIGH")), DOMAIN, REGISTRY)
    assert plan.envelope.tier == "HIGH"  # floor lifts the LOW skill's tier


def test_deterministic_same_inputs_same_plan() -> None:
    steps = [UseStep(use="crm.createLead", args={"n": 1})]
    assert compile_bizspec(_spec(steps), DOMAIN, REGISTRY) == compile_bizspec(_spec(steps), DOMAIN, REGISTRY)


# ── Refusals (never a guess) ──────────────────────────────────────────────────────────────────────
def _refuse(steps, code, *, domain=None, registry=None):
    with pytest.raises(CompileRefusal) as ei:
        compile_bizspec(_spec(steps), domain or DOMAIN, registry or REGISTRY)
    assert ei.value.code == code


def test_refuse_domain_mismatch() -> None:
    with pytest.raises(CompileRefusal) as ei:
        compile_bizspec(_spec([UseStep(use="comms.notify")], domain="Finance"), DOMAIN, REGISTRY)
    assert ei.value.code == "DOMAIN_MISMATCH"


def test_refuse_unimported_alias() -> None:
    _refuse([UseStep(use="ghost.send")], "UNIMPORTED_ALIAS")


def test_refuse_capability_not_registered() -> None:
    d = _domain(imports=[CapabilityImport(capability="Missing", major=1, alias="m")],
                bindings=[BackendBinding(capability="Missing", backend="x")])
    _refuse([UseStep(use="m.doThing")], "CAPABILITY_NOT_REGISTERED", domain=d)


def test_refuse_major_not_registered() -> None:
    d = _domain(imports=[CapabilityImport(capability="Communication", major=9, alias="comms")],
                bindings=[BackendBinding(capability="Communication", backend="smtp")])
    _refuse([UseStep(use="comms.notify")], "MAJOR_NOT_REGISTERED", domain=d)


def test_refuse_unknown_skill() -> None:
    _refuse([UseStep(use="comms.teleport")], "UNKNOWN_SKILL")


def test_refuse_ambiguous_verb_without_via() -> None:
    _refuse([UseStep(use="comms.send")], "UNRESOLVED_VERB")  # send has two candidates


def test_refuse_unsanctioned_via() -> None:
    _refuse([UseStep(use="comms.send", via="comms.send_pigeon")], "UNRESOLVED_VERB")


def test_refuse_unbound_backend() -> None:
    d = _domain(imports=[CapabilityImport(capability="Communication", major=2, alias="comms")])  # no binding
    _refuse([UseStep(use="comms.notify")], "UNBOUND_BACKEND", domain=d)


def test_refuse_dependency_cycle_among_used_capabilities() -> None:
    a = _cap("Aa", "1.0", skills=[_skill("go", ["a.go"])])
    b = _cap("Bb", "1.0", skills=[_skill("go", ["b.go"])])
    a = a.model_copy(update={"requires": ("Bb",)})
    b = b.model_copy(update={"requires": ("Aa",)})
    d = _domain(
        imports=[CapabilityImport(capability="Aa", major=1, alias="a"),
                 CapabilityImport(capability="Bb", major=1, alias="b")],
        bindings=[BackendBinding(capability="Aa", backend="x"), BackendBinding(capability="Bb", backend="y")],
    )
    _refuse([UseStep(use="a.go"), UseStep(use="b.go")], "DEPENDENCY_CYCLE", domain=d, registry=[a, b])
