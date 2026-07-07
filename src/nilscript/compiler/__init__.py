"""The compiler — Language 2 → Language 3 (Wave 4 Constitution §0/§10).

The DETERMINISTIC translation step: given a BizSpec (L2) + the Domain it targets + the capability
registry, resolve every skill call through the Domain's imports, pin SemVer, resolve the verb (D3) and
the backend (D8), compute the aggregate governance envelope (D5), validate the dependency DAG, and emit
a CompiledPlan (the structured L3 the printer serializes to `.nil`). No model runs here — same inputs
always yield the same plan. A reference the registry/Domain can't resolve is a REFUSAL, never a guess
(invariant I2): `compile_bizspec` raises `CompileRefusal(code, detail)`.
"""

from __future__ import annotations

from nilscript.compiler.compile import CompileRefusal, compile_bizspec
from nilscript.compiler.models import CompiledEnvelope, CompiledPlan, CompiledStep
from nilscript.compiler.printer import render_plan

__all__ = [
    "CompileRefusal",
    "CompiledEnvelope",
    "CompiledPlan",
    "CompiledStep",
    "compile_bizspec",
    "render_plan",
]
