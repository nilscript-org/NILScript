"""V7 — implements-conformance (CAPABILITY-SHIFT plan §A4-V7). Refusals as answers.

A PURE validator over (Cycle, Capability): given a cycle that declares `implements X@V` and the
capability the workspace-pinned registry resolved for it, admit or refuse with the SAME structured
`ValidationResult` shape V1–V6 use, so the hub renders V7 refusals unchanged. Runs wherever V1–V6
run on register (the control plane's /cycles/register). Never raises — a governance verdict is
data the caller renders, not an exception the caller catches.

Rules (each carries its own code so callers branch on codes, never wording):

  V7_UNKNOWN_CAPABILITY    the declared target is missing from the registry (capability=None), or
                           the registry's record is a DIFFERENT id/contract-version than declared
                           (fail closed — conformance against the wrong contract proves nothing)
  V7_INPUT_UNPRODUCIBLE    a REQUIRED capability input is not producible from the cycle's
                           trigger/context/variables namespace
  V7_OUTPUT_UNBOUND        a declared capability output is bound by no step's `output`
  V7_FLOOR_WEAKENED        the capability's risk floor is HIGH/CRITICAL but the cycle presents no
                           gate at (or above) that tier — the floor only rises (invariant I3)
  V7_COMPENSATION_MISSING  the capability promises `compensation` but the cycle has no coverage
                           (neither `compensate` on every write step nor a checkpoint boundary)

Interpretation of "floor only rises" (documented, honest): the rule is NOT `max(step tiers) ≥
capability.risk` as a hard equation — it is that the cycle may not present itself as LOWER risk
than its capability floor. Concretely, when `capability.risk` is HIGH/CRITICAL the cycle must
carry at least one human gate strong enough for the floor: an `await approval` step, a step whose
DECLARED verb tier (adapter `verb_details`, fail-closed: undeclared = HIGH, invariant I2 — the
same rule `wrap_cycle` uses) is ≥ the floor, or a policy that raises a step to ≥ the floor. An
undeclared verb satisfies a HIGH floor honestly because the runtime gate parks every undeclared
(= HIGH) commit for a human; it does NOT satisfy a CRITICAL floor.
"""

from __future__ import annotations

from nilscript.capability.models import Capability
from nilscript.capability.wrap import VerbMetadataLookup
from nilscript.cycle.models import ActionStep, ApprovalStep, Cycle, PolicyTier
from nilscript.kernel.diagnostics import DiagnosticCollector, ValidationResult

_TIER_ORDER: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
# Fail-closed tier for an effectful step whose verb declares nothing usable (invariant I2).
_UNDECLARED_TIER: PolicyTier = "HIGH"
# Floors that demand a matching gate in the implementation (LOW/MEDIUM auto-commit anyway).
_GATED_FLOORS = frozenset({"HIGH", "CRITICAL"})


def _no_metadata(_verb: str) -> None:
    """The fail-closed default lookup: every verb is undeclared (= HIGH)."""
    return None


def validate_implements(
    cycle: Cycle,
    capability: Capability | None,
    *,
    verb_metadata_lookup: VerbMetadataLookup = _no_metadata,
) -> ValidationResult:
    """Run every V7 rule for `cycle` against its declared capability.

    `capability` is what the WORKSPACE-PINNED registry resolved for the cycle's `implements`
    clause — None when the target is missing (V7_UNKNOWN_CAPABILITY). `verb_metadata_lookup`
    maps a verb to its DECLARED adapter metadata (`verb_details` row) or None; the default treats
    every verb as undeclared (= HIGH, fail closed). A cycle with no `implements` clause has
    nothing to conform to and passes vacuously.
    """
    collector = DiagnosticCollector()
    ref = cycle.implements
    if ref is None:
        return ValidationResult.of(collector.items)
    if capability is None:
        collector.error(
            "V7_UNKNOWN_CAPABILITY",
            f"implements {ref.capability_id}@{ref.version}: no such capability in this "
            "workspace's registry — register the capability first",
            location="implements",
        )
        return ValidationResult.of(collector.items)
    if capability.capability_id != ref.capability_id or capability.version != ref.version:
        collector.error(
            "V7_UNKNOWN_CAPABILITY",
            f"implements {ref.capability_id}@{ref.version}: the registry resolved "
            f"{capability.capability_id}@{capability.version} — conformance against a different "
            "contract proves nothing (fail closed)",
            location="implements",
        )
        return ValidationResult.of(collector.items)

    _check_inputs_producible(cycle, capability, collector)
    _check_outputs_bound(cycle, capability, collector)
    _check_floor_only_rises(cycle, capability, verb_metadata_lookup, collector)
    _check_compensation_coverage(cycle, capability, collector)
    return ValidationResult.of(collector.items)


# --- (a) required inputs are producible -------------------------------------------------------


def _producible_names(cycle: Cycle) -> set[str]:
    """The cycle's trigger/context/variables namespace — the names a seeded input can bind to:
    context entities, `let` bindings, and (for an event trigger) the trigger's match fields."""
    names = {entity.name for entity in cycle.context}
    names |= {binding.name for binding in cycle.variables}
    match = getattr(cycle.trigger, "match", None)
    if isinstance(match, dict):
        names |= set(match.keys())
    return names


def _check_inputs_producible(
    cycle: Cycle, capability: Capability, collector: DiagnosticCollector
) -> None:
    names = _producible_names(cycle)
    for field in capability.inputs:
        if field.required and field.name not in names:
            collector.error(
                "V7_INPUT_UNPRODUCIBLE",
                f"required capability input {field.name!r} is not producible: no context "
                "entity, variable, or trigger match field carries that name",
                location=f"inputs.{field.name}",
            )


# --- (b) declared outputs are bound -----------------------------------------------------------


def _check_outputs_bound(
    cycle: Cycle, capability: Capability, collector: DiagnosticCollector
) -> None:
    bound = {
        output for step in cycle.flow.steps if (output := getattr(step, "output", None))
    }
    for field in capability.outputs:
        if field.name not in bound:
            collector.error(
                "V7_OUTPUT_UNBOUND",
                f"capability output {field.name!r} is bound by no step's `output` — the "
                "implementation never produces what the contract promises",
                location=f"outputs.{field.name}",
            )


# --- (c) the floor only rises ------------------------------------------------------------------


def _check_floor_only_rises(
    cycle: Cycle,
    capability: Capability,
    lookup: VerbMetadataLookup,
    collector: DiagnosticCollector,
) -> None:
    if capability.risk not in _GATED_FLOORS:
        return
    if any(isinstance(step, ApprovalStep) for step in cycle.flow.steps):
        return  # an explicit human gate satisfies the floor
    # Strongest gate tier the cycle presents: declared verb tiers (undeclared = HIGH, fail
    # closed) ∨ policy-raised tiers. Track the strongest verb-bearing step for the refusal site.
    strongest: str = "LOW"
    offending: str | None = None
    for step in cycle.flow.steps:
        verb = getattr(step, "use", None)
        if verb is None:
            continue
        tier = ((lookup(verb) or {}).get("tier")) or ""
        step_tier = tier if tier in _TIER_ORDER else _UNDECLARED_TIER
        if _TIER_ORDER[step_tier] >= _TIER_ORDER[strongest]:
            strongest, offending = step_tier, step.id
    for policy in cycle.policies:
        raised = policy.raises_tier
        if raised is not None and _TIER_ORDER[raised] > _TIER_ORDER[strongest]:
            strongest = raised
    if _TIER_ORDER[strongest] < _TIER_ORDER[capability.risk]:
        collector.error(
            "V7_FLOOR_WEAKENED",
            f"capability risk floor is {capability.risk} but the cycle's strongest gate tier "
            f"is {strongest} — the floor only rises: add an approval step, or a step whose "
            f"declared verb tier is ≥ {capability.risk}",
            node=offending,
            location="risk",
        )


# --- (d) compensation coverage -----------------------------------------------------------------


def _check_compensation_coverage(
    cycle: Cycle, capability: Capability, collector: DiagnosticCollector
) -> None:
    if capability.compensation is None:
        return
    if any(step.type == "checkpoint" for step in cycle.flow.steps):
        return  # a checkpoint boundary provides the per-phase rollback coverage (plan B5)
    for step in cycle.flow.steps:
        if isinstance(step, ActionStep) and step.compensate is None:
            collector.error(
                "V7_COMPENSATION_MISSING",
                f"capability promises compensation ({capability.compensation}) but write step "
                f"{step.id!r} declares no `compensate` and the cycle has no checkpoint boundary",
                node=step.id,
                location="compensation",
            )


__all__ = ["validate_implements"]
