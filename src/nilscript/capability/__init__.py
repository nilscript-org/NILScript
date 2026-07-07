"""The Capability AST — the business-contract protocol object (CAPABILITY-SHIFT plan §A1).

`Capability` describes what an organisation can do — typed contract, risk floor, approval-strategy
binding, exposure, SoD class — as pure data over the same `.nil` grammar family as cycles.
`capability_content_hash` locks a version; the control-plane registry (§B1) stores versions with
the automation registry's supersede-never-edit disciplines; `wrap_cycle` (§B8) derives a fail-closed
v0 capability from any registered cycle.
"""

from __future__ import annotations

from nilscript.capability.conformance import validate_implements
from nilscript.capability.hash import capability_content_hash
from nilscript.capability.models import (
    ArchetypeTag,
    Capability,
    CapabilityField,
    Exposure,
    FieldType,
    GovernanceEnvelope,
    Metrics,
    Skill,
    Sod,
)
from nilscript.capability.nil_parser import parse_capability_nil
from nilscript.capability.nil_printer import print_capability_nil
from nilscript.capability.skills import resolve_skill, resolve_skill_verb
from nilscript.capability.wrap import WrappedCapability, wrap_cycle
from nilscript.cycle.nil_parser import NilSyntaxError

__all__ = [
    "ArchetypeTag",
    "Capability",
    "CapabilityField",
    "Exposure",
    "FieldType",
    "GovernanceEnvelope",
    "Metrics",
    "NilSyntaxError",
    "Skill",
    "Sod",
    "WrappedCapability",
    "capability_content_hash",
    "parse_capability_nil",
    "print_capability_nil",
    "resolve_skill",
    "resolve_skill_verb",
    "validate_implements",
    "wrap_cycle",
]
