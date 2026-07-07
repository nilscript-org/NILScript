"""The Business Specification IR — Language 2 of the three-language stack (Wave 4 Constitution §0/§11).

L1 natural language  ──Hermes──▶  **L2 BizSpec**  ──compiler──▶  L3 NIL  ──parser──▶ AST ──runtime──▶ Threads

A BizSpec expresses WHAT must happen in governed business terms — which capability Skills, in what order,
under which policies — with NO runtime detail (no node ids, no verb names, no NIL syntax). It is the
artifact Hermes emits (never NIL) and the artifact a human confirms before the deterministic compiler
lowers it to `.nil`. Capability/Skill references only; control flow (approval/wait/…) is explicit and
primitive (D4). DATA, never code — the same frozen-pydantic discipline as every other AST here.
"""

from __future__ import annotations

from nilscript.bizspec.models import (
    BizSpec,
    BizSpecPolicies,
    ControlStep,
    UseStep,
)

__all__ = [
    "BizSpec",
    "BizSpecPolicies",
    "ControlStep",
    "UseStep",
]
