"""B8 — the auto-wrap generator: `wrap_cycle(cycle, verb_metadata_lookup) -> WrappedCapability`.

Derives a v0 capability (plus its owner-approval strategy) from a registered cycle, so the tenant
catalog is populated on day one. PURE and deterministic — no timestamps, no randomness — so
re-wrapping an unchanged cycle yields byte-identical JSON, the same content-hash, and an
idempotent no-op at the registry.

Fail-closed rules (invariant I2 — never guess):
  - risk = max over the cycle's verb-bearing steps using DECLARED adapter metadata
    (`verb_details`); a verb with no declaration — or a garbage tier — counts as HIGH.
  - exposure is `{ai: false}`; flipping it is a deliberate, governed human act.
  - archetype is OMITTED — a heuristic tag would be a semantic guess.
  - the strategy is `seq(approve(role: owner))`: one human gate, registered alongside.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from nilscript.capability.models import Capability, CapabilityField, Exposure, FieldType, Sod
from nilscript.cycle.models import Cycle, PolicyTier
from nilscript.strategy.models import ApprovalUnit, Approve, Seq, Strategy

VerbMetadataLookup = Callable[[str], Mapping[str, Any] | None]

_TIER_ORDER: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
# The fail-closed floor for an effectful step whose verb declares nothing usable.
_UNDECLARED_TIER: PolicyTier = "HIGH"
# The one role every workspace has; the generated gate binds to it.
_OWNER_ROLE = "owner"
_WRAPPED_VERSION = "0.1"


@dataclass(frozen=True)
class WrappedCapability:
    """The wrap output: the v0 capability AND the generated strategy it references — the two are
    registered together (a capability naming a strategy that does not exist would be a dangling
    governance pointer)."""

    capability: Capability
    strategy: Strategy


def wrap_cycle(cycle: Cycle, verb_metadata_lookup: VerbMetadataLookup) -> WrappedCapability:
    """Derive the v0 capability for `cycle`. `verb_metadata_lookup` maps a verb name to its
    DECLARED metadata entry (the adapter's `verb_details` row) or None when undeclared."""
    strategy = Strategy(
        nil="strategy/0.1",
        strategy_id=f"{cycle.cycle_id}Approval",
        workspace=cycle.workspace,
        version=1,
        root=Seq(
            form="seq",
            items=(Approve(form="approve", unit=ApprovalUnit(by="role", name=_OWNER_ROLE)),),
        ),
    )
    capability = Capability(
        nil="capability/0.1",
        capability_id=cycle.cycle_id,
        workspace=cycle.workspace,
        version=_WRAPPED_VERSION,
        domain="General",  # organisational grouping, not semantics — editable, never inferred
        owner_role=_OWNER_ROLE,
        intent=cycle.intent,
        inputs=_inputs_from_cycle(cycle),
        risk=_declared_risk(cycle, verb_metadata_lookup),
        strategy=strategy.strategy_id,
        exposure=Exposure(ai=False),  # exposure is always a deliberate human act
        sod=Sod(),
        archetype=None,  # never guess semantics: no tag beats a wrong tag
        implemented_by={"default": cycle.cycle_id},
    )
    return WrappedCapability(capability=capability, strategy=strategy)


def _declared_risk(cycle: Cycle, lookup: VerbMetadataLookup) -> PolicyTier:
    """`max(step tiers)` over every verb-bearing step, from DECLARED metadata only. An undeclared
    verb (or an unparseable tier) counts as HIGH — the floor never comes from a name-substring
    guess. A cycle with no verb-bearing steps (notify-only) effects nothing and floors at LOW."""
    risk: PolicyTier = "LOW"
    for step in cycle.flow.steps:
        verb = getattr(step, "use", None)
        if verb is None:
            continue
        meta = lookup(verb)
        tier = (meta or {}).get("tier")
        step_tier: PolicyTier = tier if tier in _TIER_ORDER else _UNDECLARED_TIER
        if _TIER_ORDER[step_tier] > _TIER_ORDER[risk]:
            risk = step_tier
    return risk


def _inputs_from_cycle(cycle: Cycle) -> tuple[CapabilityField, ...]:
    """v0 contract inference: each context entity becomes a typed Entity input (that IS the
    cycle's declared world). Variables and trigger payloads are internal bindings, not contract
    slots — inferring more would be a guess."""
    return tuple(
        CapabilityField(
            name=ref.name,
            type=FieldType(kind="entity", of=ref.entity_type),
            required=False,
        )
        for ref in cycle.context
    )


__all__ = ["WrappedCapability", "wrap_cycle", "VerbMetadataLookup"]
