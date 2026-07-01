"""`governance_report` — the trust-summary projection of a Cycle.

A pure, ctx-free function: Cycle → a dict that answers "what does this cycle gate, who approves, and
what can be undone?" without compiling. Gates are derived honestly from the AST surface: every
approval step is a gate, and every step a policy escalates to HIGH/CRITICAL is a gate (the floor
only rises). Reversibility is honest too: an action is reversible ONLY if it declares a
`compensate`; absent a declared inverse we do NOT claim it can be undone.
"""

from __future__ import annotations

from nilscript.cycle.models import ActionStep, ApprovalStep, Cycle

_GATING_TIERS = frozenset({"HIGH", "CRITICAL"})


def _gate_names(cycle: Cycle) -> list[str]:
    """Approval step names + policy-escalated step names, in stable declaration order, deduped."""
    gates: list[str] = []

    def add(name: str) -> None:
        if name not in gates:
            gates.append(name)

    valid_ids = {s.id for s in cycle.flow.steps}
    for step in cycle.flow.steps:
        if isinstance(step, ApprovalStep):
            add(step.id)
    for policy in cycle.policies:
        if policy.raises_tier in _GATING_TIERS:
            for name in policy.applies_to:
                if name in valid_ids:
                    add(name)
    return gates


def governance_report(cycle: Cycle) -> dict:
    """Summarise the cycle's gates, approvals, and step reversibility (no compile, no execution)."""
    approvals = [
        {"step": s.id, "approver": s.approver, "timeout_seconds": s.timeout_seconds}
        for s in cycle.flow.steps
        if isinstance(s, ApprovalStep)
    ]
    reversibility = [
        {"step": s.id, "verb": s.use, "reversible": s.compensate is not None}
        for s in cycle.flow.steps
        if isinstance(s, ActionStep)
    ]
    return {
        "total_steps": len(cycle.flow.steps),
        "gates": _gate_names(cycle),
        "approvals": approvals,
        "reversibility": reversibility,
    }


__all__ = ["governance_report"]
