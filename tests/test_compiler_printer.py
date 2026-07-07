"""render_plan (Wave 4 §14.4c pt.1) — the deterministic review text of a CompiledPlan. Reuses the
compiler fixtures via a compiled plan built from the same Domain/registry as test_compiler.
"""

from __future__ import annotations

from nilscript.bizspec import BizSpec, ControlStep, UseStep
from nilscript.capability import Capability, GovernanceEnvelope, Skill
from nilscript.compiler import compile_bizspec, render_plan
from nilscript.domain import BackendBinding, CapabilityImport, Domain


def _skill(name, verbs, tier="MEDIUM", effects=("comms.send_email",), rev="COMPENSABLE"):
    return Skill(name=name, intent={"en": name, "ar": name}, resolves_to=tuple(verbs),
                 envelope=GovernanceEnvelope(tier=tier, reversibility=rev, effects=tuple(effects)))


def _cap(cid, version, *, risk="MEDIUM", skills=()):
    return Capability(nil="capability/0.1", capability_id=cid, workspace="acme", version=version,
                      domain="Ops", owner_role="Ops", intent={"en": cid, "ar": cid}, risk=risk,
                      strategy="AutoSmallOps", skills=tuple(skills), implemented_by={"default": f"{cid}Cycle"})


CRM = _cap("Crm", "1.0", skills=[_skill("createLead", ["crm.create_lead"], tier="HIGH",
                                        effects=("crm.create_lead",), rev="IRREVERSIBLE")])
COMMS = _cap("Communication", "2.3", risk="LOW",
             skills=[_skill("notify", ["comms.send_email"], tier="LOW")])
REGISTRY = [CRM, COMMS]
DOMAIN = Domain(nil="domain/0.1", domain_id="Procurement", workspace="acme",
                imports=(CapabilityImport(capability="Crm", major=1, alias="crm"),
                         CapabilityImport(capability="Communication", major=2, alias="comms")),
                bindings=(BackendBinding(capability="Crm", backend="odoo"),
                          BackendBinding(capability="Communication", backend="smtp")))


def _plan():
    spec = BizSpec(nil="bizspec/0.1", domain="Procurement", intent="reorder low stock", steps=(
        UseStep(use="crm.createLead", args={"name": "$who", "src": "web"}, bind="lead"),
        ControlStep(control="approval", strategy="OwnerApprove"),
        UseStep(use="comms.notify"),
    ))
    return compile_bizspec(spec, DOMAIN, REGISTRY)


def test_render_shows_header_envelope_and_resolved_steps() -> None:
    text = render_plan(_plan())
    assert "plan in Procurement" in text
    assert 'intent "reorder low stock"' in text
    # Aggregate envelope: HIGH (from createLead), IRREVERSIBLE, union of effects.
    assert "governance HIGH IRREVERSIBLE [comms.send_email, crm.create_lead]" in text
    # A resolved effect line shows capability@version, skill->verb, backend, tier, bind.
    assert "effect Crm@1.0 createLead -> crm.create_lead via odoo (HIGH) bind lead" in text
    # Args render with sorted keys (deterministic).
    assert "args {name: $who, src: web}" in text
    # Control flow renders as itself, not a capability.
    assert "control approval OwnerApprove" in text


def test_render_is_deterministic() -> None:
    assert render_plan(_plan()) == render_plan(_plan())
