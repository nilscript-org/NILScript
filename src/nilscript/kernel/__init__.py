"""nilscript.kernel — the headless DSL execution kernel.

Two halves: the **pure compiler frontend** (validate a program against a `ValidationContext`,
returning structured diagnostics) and the **runtime** (`LocalExecutor` walks an admitted program
and drives a mounted NIL adapter via the SDK `NilClient`). Temporal-free and dashboard-free — the
local sibling of wosool-cloud's durable executor.

    from nilscript.kernel import validate, ValidationContext, LocalExecutor

The DSL engine (models/validator/guards/references) is lifted intact from the reference
implementation; only the executor + CLI are kernel-specific. See
docs/nilscript-kernel-extraction-plan.md.
"""

from __future__ import annotations

from nilscript.kernel.context import SkillSpec, ValidationContext
from nilscript.kernel.diagnostics import Diagnostic, DiagnosticCollector, ValidationResult
from nilscript.kernel.executor import LocalExecutor, RunResult
from nilscript.kernel.models import WosoolProgram
from nilscript.kernel.references import resolve
from nilscript.kernel.validator import validate

__all__ = [
    "validate",
    "ValidationContext",
    "SkillSpec",
    "ValidationResult",
    "Diagnostic",
    "DiagnosticCollector",
    "WosoolProgram",
    "resolve",
    "LocalExecutor",
    "RunResult",
]
