"""The `.capability.nil` printer — `print_capability_nil(capability) -> str`.

This module DEFINES the canonical textual form of a Capability, exactly as `cycle/nil_printer.py`
does for cycles: deterministic key order, 2-space indent, one printed token per AST field, and
`parse_capability_nil(print_capability_nil(c)) == c` as the trust contract. Optional sections
(aliases/examples/inputs/outputs/compensation/requires/creates/enables/archetype/metrics) print
only when set, so absence ⟺ the model default and the bijection stays exact. `exposure` and `sod`
ALWAYS print — governance is never implicit on the surface (invariants I2/I6).

String/bilingual/list token forms are shared with the cycle printer (one grammar family).
"""

from __future__ import annotations

from nilscript.capability.models import Capability, CapabilityField, FieldType
from nilscript.cycle.nil_printer import INDENT, _bilingual, _id_list, _string

_BOOL = {True: "true", False: "false"}


def print_capability_nil(capability: Capability) -> str:
    """Render a Capability to its canonical `.nil` text. Deterministic and round-trippable."""
    c = capability
    lines: list[str] = [f"capability {c.capability_id} v{c.version} {{"]
    body: list[str] = []
    body.append(f"workspace {_string(c.workspace)}")
    body.append(f"domain {c.domain}")
    body.append(f"owner role {c.owner_role}")
    body.append(f"intent {_bilingual(c.intent)}")
    if c.aliases:
        body.append("aliases { " + ", ".join(_string(a) for a in c.aliases) + " }")
    if c.examples:
        body.append("examples { " + ", ".join(_string(e) for e in c.examples) + " }")
    if c.inputs:
        body.extend(_fields_block("inputs", c.inputs))
    if c.outputs:
        body.extend(_fields_block("outputs", c.outputs))
    body.append(f"risk {c.risk}")
    body.append(f"strategy {c.strategy}")
    if c.compensation is not None:
        body.append(f"compensation {c.compensation}")
    if c.requires:
        body.append(f"requires {_id_list(c.requires)}")
    if c.creates:
        body.append(f"creates {_id_list(c.creates)}")
    if c.enables:
        body.append(f"enables {_id_list(c.enables)}")
    exposure = [f"ai: {_BOOL[c.exposure.ai]}"]
    if c.exposure.roles:
        exposure.append(f"roles: {_id_list(c.exposure.roles)}")
    body.append("exposure { " + "; ".join(exposure) + " }")
    body.append(f"sod {{ preparer_not_approver: {_BOOL[c.sod.preparer_not_approver]} }}")
    if c.archetype is not None:
        body.append(f"archetype {c.archetype}")
    if c.metrics is not None:
        body.append(f"metrics {{ sla: {_string(c.metrics.sla)} }}")
    impls = "; ".join(f"{name}: {ref}" for name, ref in c.implemented_by.items())
    body.append("implemented_by { " + impls + " }")
    lines.extend(INDENT + line for line in body)
    lines.append("}")
    return "\n".join(lines) + "\n"


def _fields_block(keyword: str, fields: tuple[CapabilityField, ...]) -> list[str]:
    lines = [f"{keyword} {{"]
    for f in fields:
        required = " required" if f.required else ""
        lines.append(f"{INDENT}{f.name}: {_field_type(f.type)}{required};")
    lines.append("}")
    return lines


def _field_type(ft: FieldType) -> str:
    if ft.kind == "entity":
        return f"Entity({ft.of})"
    if ft.kind == "list":
        return f"List({ft.of})"
    return ft.of  # scalar — a bare type name (Money, Date, …)


__all__ = ["print_capability_nil"]
