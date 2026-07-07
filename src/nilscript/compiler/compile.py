"""compile_bizspec — the deterministic L2→L3 lowering (Wave 4 §10). Pure: same (spec, domain, registry)
always yields the same CompiledPlan. Every resolution reuses a gate already built and tested —
resolve_alias (D2), the registry SemVer pin, resolve_skill/resolve_skill_verb (D3), resolve_backend
(D8), check_dag (registry). An unresolvable reference is a REFUSAL (I2), never a guess."""

from __future__ import annotations

from nilscript.bizspec.models import BizSpec, ControlStep, UseStep
from nilscript.capability.models import TIER_ORDER, Capability
from nilscript.capability.registry import check_dag
from nilscript.capability.skills import resolve_skill, resolve_skill_verb
from nilscript.compiler.models import CompiledEnvelope, CompiledPlan, CompiledStep
from nilscript.domain.models import Domain
from nilscript.domain.resolve import resolve_alias, resolve_backend

# Reversibility, strongest first — the plan inherits the strongest (most-constraining) of its effects.
_REVERSIBILITY_ORDER = {"IRREVERSIBLE": 2, "COMPENSABLE": 1, "REVERSIBLE": 0}


class CompileRefusal(Exception):
    """A deterministic compile failure — the reference could not be resolved under the Domain/registry.
    Carries a stable `code` (branchable) and a human `detail`. Never a partial/guessed plan."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _major(version: str) -> int:
    return int(version.split(".")[0])


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


def _pin_capability(registry: list[Capability], capability_id: str, major: int) -> Capability:
    """The exact registered capability an import pins to: the highest minor/patch at the imported major.
    Refuses if the id is absent (CAPABILITY_NOT_REGISTERED) or has no version at that major
    (MAJOR_NOT_REGISTERED) — an import can never drift to a version that isn't there."""
    same_id = [c for c in registry if c.capability_id == capability_id]
    if not same_id:
        raise CompileRefusal("CAPABILITY_NOT_REGISTERED", f"{capability_id} is not in the registry")
    at_major = [c for c in same_id if _major(c.version) == major]
    if not at_major:
        raise CompileRefusal(
            "MAJOR_NOT_REGISTERED", f"{capability_id} has no version at major {major}"
        )
    return max(at_major, key=lambda c: _version_key(c.version))


def _compile_use(step: UseStep, domain: Domain, registry: list[Capability]) -> tuple[CompiledStep, Capability]:
    alias, _, skill_name = step.use.partition(".")
    imp = resolve_alias(domain, alias)
    if imp is None:
        raise CompileRefusal(
            "UNIMPORTED_ALIAS", f"{alias!r} is not imported by domain {domain.domain_id}"
        )
    cap = _pin_capability(registry, imp.capability, imp.major)

    skill = resolve_skill(cap, skill_name)
    if skill is None:
        raise CompileRefusal(
            "UNKNOWN_SKILL", f"{imp.capability}@{cap.version} exposes no skill {skill_name!r}"
        )
    verb = resolve_skill_verb(skill, via=step.via)
    if verb is None:
        detail = (
            f"via {step.via!r} is not a candidate of {skill_name}"
            if step.via is not None
            else f"{skill_name} resolves to multiple verbs; an explicit `via` is required"
        )
        raise CompileRefusal("UNRESOLVED_VERB", detail)

    backend = resolve_backend(domain, imp.capability)
    if backend is None:
        raise CompileRefusal(
            "UNBOUND_BACKEND", f"{imp.capability} has no backend bound in domain {domain.domain_id} (D8)"
        )

    compiled = CompiledStep(
        kind="effect",
        capability=imp.capability,
        version=cap.version,
        skill=skill_name,
        verb=verb,
        backend=backend,
        tier=skill.envelope.tier,
        args=dict(step.args),
        bind=step.bind,
    )
    return compiled, cap


def _compile_control(step: ControlStep) -> CompiledStep:
    return CompiledStep(
        kind="control",
        control=step.control,
        strategy=step.strategy,
        event=step.event,
        to=step.to,
    )


def _aggregate_envelope(used_skills: list, floor_tier: str | None) -> CompiledEnvelope:
    """The plan's blast radius (D5): strongest tier (respecting a policy floor), union of all effects,
    strongest reversibility. Empty of effects → LOW/REVERSIBLE (a control-only plan does nothing)."""
    tier = floor_tier or "LOW"
    reversibility = "REVERSIBLE"
    effects: set[str] = set()
    for env in used_skills:
        if TIER_ORDER[env.tier] > TIER_ORDER[tier]:
            tier = env.tier
        if _REVERSIBILITY_ORDER[env.reversibility] > _REVERSIBILITY_ORDER[reversibility]:
            reversibility = env.reversibility
        effects.update(env.effects)
    return CompiledEnvelope(tier=tier, reversibility=reversibility, effects=tuple(sorted(effects)))


def compile_bizspec(spec: BizSpec, domain: Domain, registry: list[Capability]) -> CompiledPlan:
    """Lower a BizSpec to a CompiledPlan under a Domain + registry. Deterministic; raises CompileRefusal
    on any unresolved reference (I2 — never a partial plan). Also validates that the capabilities the
    plan actually uses form no dependency cycle (a subset guard on top of the registry-level DAG gate)."""
    if spec.domain != domain.domain_id:
        raise CompileRefusal(
            "DOMAIN_MISMATCH", f"spec targets {spec.domain!r} but domain is {domain.domain_id!r}"
        )

    compiled_steps: list[CompiledStep] = []
    used_caps: list[Capability] = []
    used_envelopes = []
    for step in spec.steps:
        if isinstance(step, UseStep):
            compiled, cap = _compile_use(step, domain, registry)
            compiled_steps.append(compiled)
            used_caps.append(cap)
            skill = resolve_skill(cap, compiled.skill)  # already resolved in _compile_use; safe
            if skill is not None:
                used_envelopes.append(skill.envelope)
        else:
            compiled_steps.append(_compile_control(step))

    dag = check_dag(used_caps)
    if dag:
        raise CompileRefusal("DEPENDENCY_CYCLE", dag[0].detail)

    envelope = _aggregate_envelope(used_envelopes, spec.policies.tier_floor)
    return CompiledPlan(
        domain=domain.domain_id,
        intent=spec.intent,
        steps=tuple(compiled_steps),
        envelope=envelope,
    )
