"""Test Wave 5 Kernel — the two-entry-point API (stubs for Phase 3)."""

import pytest

from nilscript.wbos.intent import (
    CreateBusinessCycleIntent,
    ExecuteCycleIntent,
    IntentKind,
)
from nilscript.wbos.kernel import CompiledPlan, ExecutionResult, Kernel


class TestExecutionResult:
    """ExecutionResult encapsulates Kernel.execute() outcome."""

    def test_execution_result_creation_success(self):
        """Can create a successful ExecutionResult."""
        result = ExecutionResult(
            success=True,
            intent_kind=IntentKind.EXECUTE_CYCLE,
            result={"cycle_id": "ApprovalProcess", "run_id": "run-123"},
        )
        assert result.success is True
        assert result.intent_kind == IntentKind.EXECUTE_CYCLE
        assert result.result["cycle_id"] == "ApprovalProcess"

    def test_execution_result_creation_failure(self):
        """Can create a failed ExecutionResult."""
        result = ExecutionResult(
            success=False,
            intent_kind=IntentKind.EXECUTE_CYCLE,
            error="Cycle not found",
        )
        assert result.success is False
        assert result.error == "Cycle not found"

    def test_execution_result_includes_audit_log(self):
        """ExecutionResult can include audit log."""
        result = ExecutionResult(
            success=True,
            intent_kind=IntentKind.EXECUTE_CYCLE,
            result={},
            audit_log={"actor": "user-1", "action": "execute_cycle", "timestamp": "2026-07-07T12:00:00Z"},
        )
        assert result.audit_log["actor"] == "user-1"

    def test_execution_result_includes_timeline(self):
        """ExecutionResult can include timeline of events."""
        result = ExecutionResult(
            success=True,
            intent_kind=IntentKind.EXECUTE_CYCLE,
            result={},
            timeline=[
                {"event": "start", "timestamp": "2026-07-07T12:00:00Z"},
                {"event": "step_1_complete", "timestamp": "2026-07-07T12:00:05Z"},
                {"event": "end", "timestamp": "2026-07-07T12:00:10Z"},
            ],
        )
        assert len(result.timeline) == 3


class TestCompiledPlan:
    """CompiledPlan encapsulates Kernel.compile() outcome."""

    def test_compiled_plan_creation_success(self):
        """Can create a successful CompiledPlan."""
        plan = CompiledPlan(
            success=True,
            intent_kind=IntentKind.CREATE_BUSINESS_CYCLE,
            cycle_blueprint={"cycle_id": "ApprovalProcess", "steps": []},
            nil_code="cycle ApprovalProcess { ... }",
        )
        assert plan.success is True
        assert plan.intent_kind == IntentKind.CREATE_BUSINESS_CYCLE
        assert plan.cycle_blueprint["cycle_id"] == "ApprovalProcess"

    def test_compiled_plan_creation_failure(self):
        """Can create a failed CompiledPlan."""
        plan = CompiledPlan(
            success=False,
            intent_kind=IntentKind.CREATE_BUSINESS_CYCLE,
            validation_errors=["Missing actor definition", "No approval strategy"],
        )
        assert plan.success is False
        assert len(plan.validation_errors) == 2

    def test_compiled_plan_includes_preview(self):
        """CompiledPlan can include a preview."""
        plan = CompiledPlan(
            success=True,
            intent_kind=IntentKind.CREATE_BUSINESS_CYCLE,
            cycle_blueprint={},
            preview="Approval Workflow\n- Step 1: Verify order amount\n- Step 2: Route for approval\n",
        )
        assert "Approval Workflow" in plan.preview

    def test_compiled_plan_includes_clarification_needed(self):
        """CompiledPlan can indicate clarifications needed."""
        plan = CompiledPlan(
            success=False,
            intent_kind=IntentKind.CREATE_BUSINESS_CYCLE,
            clarification_needed=[
                {"question": "Which suppliers should auto-approve?", "options": ["ACME", "SUPPLIER2"]},
            ],
            requires_confirmation=True,
        )
        assert len(plan.clarification_needed) == 1
        assert plan.requires_confirmation is True


class TestKernelExecuteStub:
    """Kernel.execute() is a stub returning Phase 3 message."""

    def test_kernel_execute_returns_error_stub(self):
        """Kernel.execute() returns error indicating stub status."""
        intent = ExecuteCycleIntent(
            description="Execute order approval",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = Kernel.execute(intent)
        assert result.success is False
        assert "stub" in result.error.lower()
        assert "Phase 3" in result.error

    def test_kernel_execute_preserves_intent_kind(self):
        """Kernel.execute() preserves the intent kind in result."""
        intent = ExecuteCycleIntent(
            description="Execute order approval",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = Kernel.execute(intent)
        assert result.intent_kind == IntentKind.EXECUTE_CYCLE

    def test_kernel_execute_returns_execution_result(self):
        """Kernel.execute() always returns ExecutionResult."""
        intent = CreateBusinessCycleIntent(
            description="Create workflow",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = Kernel.execute(intent)
        assert isinstance(result, ExecutionResult)


class TestKernelCompileStub:
    """Kernel.compile() is a stub returning Phase 3 message."""

    def test_kernel_compile_returns_error_stub(self):
        """Kernel.compile() returns error indicating stub status."""
        intent = CreateBusinessCycleIntent(
            description="Create approval workflow for orders over $10k",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = Kernel.compile(intent)
        assert result.success is False
        assert len(result.validation_errors) > 0
        assert "stub" in result.validation_errors[0].lower()
        assert "Phase 3" in result.validation_errors[0]

    def test_kernel_compile_preserves_intent_kind(self):
        """Kernel.compile() preserves the intent kind in result."""
        intent = CreateBusinessCycleIntent(
            description="Create approval workflow",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = Kernel.compile(intent)
        assert result.intent_kind == IntentKind.CREATE_BUSINESS_CYCLE

    def test_kernel_compile_returns_compiled_plan(self):
        """Kernel.compile() always returns CompiledPlan."""
        intent = CreateBusinessCycleIntent(
            description="Create workflow",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = Kernel.compile(intent)
        assert isinstance(result, CompiledPlan)


class TestKernelSaveCompiledCycleStub:
    """Kernel.save_compiled_cycle() is a stub for Phase 3."""

    def test_kernel_save_compiled_cycle_returns_error_stub(self):
        """Kernel.save_compiled_cycle() returns error indicating stub status."""
        plan = CompiledPlan(
            success=True,
            intent_kind=IntentKind.CREATE_BUSINESS_CYCLE,
            cycle_blueprint={},
            nil_code="",
        )
        result = Kernel.save_compiled_cycle("ApprovalProcess", plan, "ws-1")
        assert result.success is False
        assert "stub" in result.error.lower()

    def test_kernel_save_compiled_cycle_returns_execution_result(self):
        """Kernel.save_compiled_cycle() returns ExecutionResult."""
        plan = CompiledPlan(
            success=True,
            intent_kind=IntentKind.CREATE_BUSINESS_CYCLE,
            cycle_blueprint={},
            nil_code="",
        )
        result = Kernel.save_compiled_cycle("ApprovalProcess", plan, "ws-1")
        assert isinstance(result, ExecutionResult)


class TestKernelValidateIntentStub:
    """Kernel.validate_intent() performs basic validation."""

    def test_kernel_validate_intent_accepts_valid_intent(self):
        """Kernel.validate_intent() accepts well-formed intent."""
        intent = CreateBusinessCycleIntent(
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        is_valid, errors = Kernel.validate_intent(intent)
        assert is_valid is True
        assert len(errors) == 0

    def test_kernel_validate_intent_returns_tuple(self):
        """Kernel.validate_intent() returns (bool, list[str]) tuple."""
        intent = CreateBusinessCycleIntent(
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = Kernel.validate_intent(intent)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], list)


class TestKernelIntegration:
    """Kernel integrates with frozen Intent schemas."""

    def test_kernel_works_with_frozen_intents(self):
        """Kernel methods accept frozen Intent objects."""
        intent = ExecuteCycleIntent(
            description="Execute",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        # Ensure intent is frozen
        with pytest.raises(Exception):
            intent.kind = None

        # Kernel should still work
        result = Kernel.execute(intent)
        assert isinstance(result, ExecutionResult)

    def test_kernel_execute_and_compile_have_different_semantics(self):
        """Kernel.execute() and Kernel.compile() are distinct operations."""
        intent_exec = ExecuteCycleIntent(
            description="Execute",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        intent_create = CreateBusinessCycleIntent(
            description="Create",
            workspace_id="ws-1",
            actor_id="user-1",
        )

        result_exec = Kernel.execute(intent_exec)
        result_compile = Kernel.compile(intent_create)

        # Results are different types
        assert isinstance(result_exec, ExecutionResult)
        assert isinstance(result_compile, CompiledPlan)

        # Different intent kinds
        assert result_exec.intent_kind == IntentKind.EXECUTE_CYCLE
        assert result_compile.intent_kind == IntentKind.CREATE_BUSINESS_CYCLE
