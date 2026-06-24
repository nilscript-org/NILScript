"""Approval ceilings — the minimal, on-demand slice of parametric policy.

This is deliberately NOT a general ABAC/policy-pack engine (that is racing a banking-agent product).
It is one merchant-facing guard: a money-moving verb whose numeric arg exceeds a declared cap has its
tier floored to HIGH, so it parks for a human DECIDE instead of auto-committing. "The agent can never
move more than SAR 500 without me." Adapters declare a `{verb: {arg: max}}` map and apply it at PROPOSE.

Pure, so it is unit-tested without a backend. A breach never *denies* — it escalates to approval; the
honest-refusal path stays for skeleton/unexpressible/precondition cases.
"""

from __future__ import annotations

from typing import Any

_TIER_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def exceeds_ceiling(verb: str, args: dict[str, Any], ceilings: dict[str, dict[str, Any]]) -> str | None:
    """Return the first arg whose value breaches its configured numeric cap for `verb`, else None.
    Non-numeric or missing values never breach (the gate's other guards own those)."""
    for arg, cap in (ceilings.get(verb) or {}).items():
        value = args.get(arg)
        if value is None:
            continue
        try:
            if float(value) > float(cap):
                return arg
        except (TypeError, ValueError):
            continue
    return None


def floor_tier(tier: str, *, to: str = "HIGH") -> str:
    """Raise `tier` to at least `to` (default HIGH); never demote a stricter tier."""
    return to if _TIER_ORDER.get(tier, 0) < _TIER_ORDER.get(to, 2) else tier
