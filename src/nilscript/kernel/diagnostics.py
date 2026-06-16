"""Structured validation diagnostics — the result contract consumed by engineers AND the LLM.

Mirrors AWS ValidateStateMachineDefinition: callers branch on `result` (+ codes), never on exact
wording. ERROR-severity diagnostics block admission; WARNING informs. The canonical code list
lives in wosool-dsl/conformance/README.md and wosool-dsl/03-VALIDATION-AND-TYPES.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["ERROR", "WARNING"]


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: Severity
    message: str
    location: str = ""
    node: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    result: Literal["OK", "FAIL"]
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def ok(self) -> bool:
        return self.result == "OK"

    @classmethod
    def of(cls, diagnostics: list[Diagnostic]) -> ValidationResult:
        """Admit unless any diagnostic is an ERROR."""
        blocking = any(d.severity == "ERROR" for d in diagnostics)
        return cls(result="FAIL" if blocking else "OK", diagnostics=tuple(diagnostics))


@dataclass
class DiagnosticCollector:
    """Accumulates diagnostics across the validator passes."""

    items: list[Diagnostic] = field(default_factory=list)

    def error(
        self, code: str, message: str, *, node: str | None = None, location: str = ""
    ) -> None:
        self.items.append(
            Diagnostic(code=code, severity="ERROR", message=message, node=node, location=location)
        )

    def warning(
        self, code: str, message: str, *, node: str | None = None, location: str = ""
    ) -> None:
        self.items.append(
            Diagnostic(code=code, severity="WARNING", message=message, node=node, location=location)
        )

    @property
    def has_errors(self) -> bool:
        return any(d.severity == "ERROR" for d in self.items)
