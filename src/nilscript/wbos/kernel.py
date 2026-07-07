"""Wave 5 Kernel — The single business API for Intent execution and compilation.

The Kernel is the server-side orchestrator that:
- Kernel.execute: Runs a business Intent at runtime
- Kernel.compile: Compiles a business Intent to a Cycle blueprint at design-time

Both entry points accept frozen Intent schemas and return structured results.
Hermes never interacts with Verbs, Capabilities, or Cycles directly.

Reference: docs/WAVE-5-MIGRATION.md §Kernel
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nilscript.wbos.intent import Intent, IntentKind


@dataclass
class ExecutionResult:
    """Result of Kernel.execute()."""

    success: bool
    intent_kind: IntentKind
    result: Any = None
    error: str | None = None
    audit_log: dict[str, Any] = field(default_factory=dict)
    timeline: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CompiledPlan:
    """Result of Kernel.compile()."""

    success: bool
    intent_kind: IntentKind
    cycle_blueprint: dict[str, Any] | None = None
    nil_code: str | None = None
    preview: str | None = None
    validation_errors: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    clarification_needed: list[dict[str, Any]] = field(default_factory=list)


class Kernel:
    """The Business Kernel — the single API for everything.

    Hermes → Intent → Kernel (execute or compile) → Result

    The Kernel resolves all business semantics server-side:
    - Capability resolution (which capabilities does this intent need?)
    - Governance validation (is the actor allowed to do this?)
    - Cycle compilation (for design-time blueprint generation)
    - Execution orchestration (for runtime execution)

    All methods are stubs in Wave 5; implementation follows in Phase 3.
    """

    @staticmethod
    def execute(intent: Intent) -> ExecutionResult:
        """Execute an intent at runtime.

        Route:
        1. Intent validation (schema check)
        2. Capability Resolver (intent → capabilities)
        3. Governance validation (permission card, audit)
        4. Capability execution (fire resolved verbs)
        5. Return structured result with audit log and timeline

        Args:
            intent: A frozen Intent from Hermes

        Returns:
            ExecutionResult with success/error, audit log, and timeline

        Raises:
            ValueError: If intent validation fails
            PermissionError: If actor lacks authorization

        TODO: Implementation in Phase 3
        - Call CapabilityResolver.resolve_for_intent()
        - Check governance tiers and permission cards
        - Execute resolved capabilities in order
        - Emit audit log entries
        - Track timeline (start, step completion, end)
        - Handle errors and compensation
        """
        # Stub: return error
        return ExecutionResult(
            success=False,
            intent_kind=intent.kind,
            error="Kernel.execute() is a stub — implementation in Phase 3",
        )

    @staticmethod
    def compile(intent: Intent) -> CompiledPlan:
        """Compile an intent at design-time to a Cycle blueprint.

        Route:
        1. Intent validation (schema check)
        2. Specification Engine (NL → spec with Clarify loop)
        3. Capability Resolver (spec → capabilities)
        4. Cycle Builder (capabilities → cycle blueprint)
        5. NIL Compiler (blueprint → .nil text)
        6. Validator (policy/type/gov checks)
        7. Return preview + confirmation request

        This is used when a user designs a new cycle interactively:
        - User describes intent in NL: "Create an approval workflow for orders over $10k"
        - Kernel.compile(intent) generates a Cycle blueprint
        - User previews and edits (Hermes shows cycle text and UI preview)
        - User confirms → Kernel.save_compiled_cycle(cycle_id, blueprint)
        - User runs it → Kernel.execute(ExecuteCycleIntent(cycle_id))

        Args:
            intent: A frozen Intent from Hermes (usually CreateBusinessCycleIntent)

        Returns:
            CompiledPlan with cycle_blueprint, .nil code, and preview

        Raises:
            ValueError: If intent validation fails
            RuntimeError: If specification or compilation fails

        TODO: Implementation in Phase 3
        - Initialize Specification Engine
        - Loop: generate spec, emit Clarify requests for ambiguities
        - Call CapabilityResolver.resolve_for_intent()
        - Call CycleBuilder to generate cycle AST
        - Call NILCompiler to generate .nil text
        - Call Validator to check governance/types/policy
        - Generate preview (text + visual)
        - Ask for user confirmation
        """
        # Stub: return error
        return CompiledPlan(
            success=False,
            intent_kind=intent.kind,
            validation_errors=["Kernel.compile() is a stub — implementation in Phase 3"],
        )

    @staticmethod
    def save_compiled_cycle(
        cycle_id: str, compiled_plan: CompiledPlan, workspace_id: str
    ) -> ExecutionResult:
        """Save a compiled cycle blueprint to the registry.

        Called after user confirmation in the design-time flow.

        Args:
            cycle_id: The new cycle id
            compiled_plan: The compiled plan from Kernel.compile()
            workspace_id: Tenant context

        Returns:
            ExecutionResult with saved cycle metadata

        TODO: Implementation in Phase 3
        - Validate compiled_plan.success is True
        - Store cycle blueprint in registry
        - Return success result with cycle_id
        """
        # Stub
        return ExecutionResult(
            success=False,
            intent_kind=IntentKind.CREATE_BUSINESS_CYCLE,
            error="Kernel.save_compiled_cycle() is a stub — Phase 3",
        )

    @staticmethod
    def validate_intent(intent: Intent) -> tuple[bool, list[str]]:
        """Validate an intent schema.

        This is the first gate: ensures the intent is well-formed before
        resolution or execution. The Intent schema itself (pydantic frozen
        model) enforces basic structure; this method can add semantic checks.

        Args:
            intent: A frozen Intent

        Returns:
            (is_valid, error_messages)

        TODO: Phase 3
        - Check required fields are present
        - Validate intent-specific semantics
        - Return errors if any
        """
        # Stub: basic pydantic validation only
        return (True, [])
