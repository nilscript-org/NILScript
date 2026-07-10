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

from typing import TYPE_CHECKING, Any

from nilscript.kernel.context import SkillSpec, ValidationContext
from nilscript.kernel.diagnostics import Diagnostic, DiagnosticCollector, ValidationResult
from nilscript.kernel.models import WosoolProgram
from nilscript.kernel.references import resolve
from nilscript.kernel.validator import validate

if TYPE_CHECKING:  # pragma: no cover — types only; the runtime import is lazy (see __getattr__)
    from nilscript.kernel.executor import LocalExecutor, RunResult


def __getattr__(name: str) -> Any:
    """Lazy executor import (PEP 562). The executor pulls in nilscript.runtime, whose command_bus
    imports nilscript.cycle.models — which itself imports nilscript.kernel.models and therefore
    runs THIS package __init__. Importing the executor eagerly here closes that loop into a
    circular-import crash for any entrypoint that reaches cycle.models before the runtime
    (e.g. the catalog seeder importing nilscript.capability). Deferring it breaks the cycle
    while `from nilscript.kernel import LocalExecutor` keeps working unchanged."""
    if name in ("LocalExecutor", "RunResult"):
        from nilscript.kernel import executor

        return getattr(executor, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

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
