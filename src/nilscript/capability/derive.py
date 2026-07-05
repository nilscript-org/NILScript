"""B8+ — auto-derive DRAFT capabilities from a plugged-in adapter's verbs.

`wrap_cycle` turns a *cycle* into a v0 capability. This module closes the plug-and-play loop: given an
adapter's describe skeleton, it SYNTHESIZES a one-action cycle per verb and wraps each — so activating a
new backend populates the tenant catalog with fail-closed draft candidates on day one, no hand-authoring.

Fail-closed and honest, by construction:
  - every derived capability is `exposure.ai = false` (wrap's invariant) — exposing it stays a deliberate,
    governed human act (the ExposureConfirmDialog / publish endpoint).
  - risk is `max` over declared verb metadata; an undeclared verb floors at HIGH (never a name guess).
  - `covered_verbs` (verbs an existing capability already implements) are SKIPPED, so a curated catalog is
    never shadowed by generic auto-drafts, and re-derivation is an idempotent no-op.
  - PURE / deterministic: no timestamps, no randomness — re-deriving an unchanged skeleton yields the same
    ids and content-hashes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from nilscript.capability.wrap import WrappedCapability, wrap_cycle
from nilscript.cycle.models import Cycle

# Auto-derived ids are namespaced so they never collide with a hand-curated capability and are
# recognisable in the UI as "derived, awaiting curation".
AUTO_PREFIX = "auto_"


@dataclass(frozen=True)
class DerivedCapability:
    """One derived draft: the synthesized cycle (to register as the implementation) plus the wrapped
    capability + its generated approval strategy."""

    verb: str
    cycle: Cycle
    wrapped: WrappedCapability


def _slug(verb: str) -> str:
    # "services.create_invoice" -> "auto_services_create_invoice" (a valid cycle/capability id).
    return AUTO_PREFIX + verb.replace(".", "_").replace("-", "_")


def _humanize(verb: str) -> str:
    # "services.create_invoice" -> "Services create invoice" — a readable placeholder intent.
    words = verb.replace(".", " ").replace("_", " ").split()
    return " ".join(words).capitalize() if words else verb


def synthesize_cycle(workspace: str, verb: str) -> Cycle:
    """A minimal, valid v0.2 cycle whose single action fires `verb`. No context/inputs are inferred
    (that would be a guess); the operator adds the contract's inputs when curating the draft."""
    return Cycle.model_validate(
        {
            "nil": "cycle/0.2",
            "cycle_id": _slug(verb),
            "workspace": workspace,
            "metadata": {"version": "0.1.0", "owner": "auto-derive"},
            "intent": {"en": _humanize(verb), "ar": verb},
            "trigger": {"type": "manual"},
            "context": (),
            "flow": {
                "entry": "Do",
                "steps": [{"id": "Do", "type": "action", "use": verb, "with": {}}],
            },
        }
    )


def _verbs_of(skeleton: Mapping[str, Any]) -> list[str]:
    verbs = skeleton.get("verbs")
    if verbs:
        return [v for v in verbs if isinstance(v, str)]
    return [
        d["verb"]
        for d in skeleton.get("verb_details", [])
        if isinstance(d, dict) and isinstance(d.get("verb"), str)
    ]


def derive_from_skeleton(
    workspace: str,
    skeleton: Mapping[str, Any],
    covered_verbs: Iterable[str] = (),
) -> list[DerivedCapability]:
    """Derive a fail-closed draft capability for every verb the adapter declares that no existing
    capability already implements. Deterministic and idempotent."""
    covered = set(covered_verbs)
    details = {
        d["verb"]: d
        for d in skeleton.get("verb_details", [])
        if isinstance(d, dict) and d.get("verb")
    }
    derived: list[DerivedCapability] = []
    for verb in _verbs_of(skeleton):
        if verb in covered:
            continue
        cycle = synthesize_cycle(workspace, verb)
        wrapped = wrap_cycle(cycle, details.get)
        derived.append(DerivedCapability(verb=verb, cycle=cycle, wrapped=wrapped))
    return derived


__all__ = ["DerivedCapability", "derive_from_skeleton", "synthesize_cycle", "AUTO_PREFIX"]
