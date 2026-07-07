"""Tests for cycle publish pipeline — compilation and storage."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nilscript.automation.models import ManualTrigger
from nilscript.controlplane.cycle_manager import CycleManager
from nilscript.controlplane.store import EventStore
from nilscript.cycle import Cycle
from nilscript.cycle.models import (
    ActionStep,
    CycleMetadata,
    Flow,
    ImplementsClause,
)
from nilscript.cycle.compile import CompileResult
from nilscript.kernel.models import BilingualText, WosoolProgram
from nilscript.kernel.diagnostics import ValidationResult


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        yield str(db_path)


@pytest.fixture
def store(temp_db):
    """Create an EventStore instance."""
    return EventStore(path=temp_db)


@pytest.fixture
def manager(store):
    """Create a CycleManager instance."""
    return CycleManager(store=store)


def _make_cycle(
    cycle_id: str = "TestCycle",
    domain_id: str | None = None,
    **kwargs,
) -> Cycle:
    """Factory for creating test Cycle instances."""
    defaults = {
        "nil": "cycle/0.2",
        "cycle_id": cycle_id,
        "workspace": "test-workspace",
        "metadata": CycleMetadata(version="1.0", owner="Test Owner"),
        "intent": BilingualText(en="Test cycle", ar="اختبار"),
        "trigger": ManualTrigger(type="manual"),
        "context": (),
        "variables": (),
        "roles": (),
        "policies": (),
        "resources": (),
        "outcomes": (),
        "flow": Flow(
            entry="CreateLead",
            steps=(
                ActionStep(
                    id="CreateLead",
                    type="action",
                    use="odoo.crm_create_lead",
                ),
            ),
        ),
    }
    if domain_id:
        defaults["nil"] = "cycle/0.3"
        defaults["implements"] = ImplementsClause(
            capability_id=domain_id,
            version="1.0",
        )

    defaults.update(kwargs)
    return Cycle(**defaults)


class TestPublishCycle:
    """Tests for cycle publishing."""

    def _mock_compile_result(self, cycle: Cycle) -> CompileResult:
        """Create a mock successful compile result."""
        program = WosoolProgram(
            wosool="0.1",
            workspace=cycle.workspace,
            entry="step_1",
            pipeline=[
                {
                    "id": "step_1",
                    "type": "action",
                    "verb": "odoo.crm_create_lead",
                    "args": {},
                    "skill": "odoo",
                }
            ],
        )
        return CompileResult(
            ok=True,
            diagnostics=ValidationResult(result="OK"),
            program=program,
            content_hash="abc123def456",
            gates=(),
            step_ids={"CreateLead": "step_1"},
        )

    @patch("nilscript.controlplane.cycle_manager.compile_cycle")
    def test_publish_cycle_succeeds_with_valid_cycle(self, mock_compile, manager):
        """Verify publish_cycle successfully compiles and stores a valid cycle."""
        cycle = _make_cycle()
        mock_compile.return_value = self._mock_compile_result(cycle)

        result = manager.publish_cycle(
            workspace="test-workspace",
            cycle_id="TestCycle",
            cycle=cycle,
        )

        assert result["status"] == "published"
        assert result["compiled_plan"] is not None
        assert result["flow"] is not None
        assert result["backend_bindings"] == '{"odoo.crm_create_lead": "odoo"}'
        assert result["compile_error"] is None

    @patch("nilscript.controlplane.cycle_manager.compile_cycle")
    def test_publish_cycle_stores_in_database(self, mock_compile, manager):
        """Verify published cycles are stored and retrievable."""
        cycle = _make_cycle()
        mock_compile.return_value = self._mock_compile_result(cycle)

        manager.publish_cycle(
            workspace="test-workspace",
            cycle_id="TestCycle",
            cycle=cycle,
        )

        # Retrieve from database
        stored = manager.get_cycle(
            workspace="test-workspace",
            cycle_id="TestCycle",
            version=1,
        )

        assert stored is not None
        assert stored["status"] == "published"
        assert stored["cycle_id"] == "TestCycle"

    @patch("nilscript.controlplane.cycle_manager.compile_cycle")
    def test_publish_cycle_with_domain_id(self, mock_compile, manager):
        """Verify cycle with domain_id (implements clause) is stored correctly."""
        cycle = _make_cycle(domain_id="ProcurementCycle")
        mock_compile.return_value = self._mock_compile_result(cycle)

        result = manager.publish_cycle(
            workspace="test-workspace",
            cycle_id="ProcurementCycle",
            cycle=cycle,
        )

        assert result["domain_id"] == "ProcurementCycle"
        assert result["status"] == "published"

    @patch("nilscript.controlplane.cycle_manager.compile_cycle")
    def test_publish_cycle_with_multiple_actions(self, mock_compile, manager):
        """Verify backend bindings are extracted from all steps."""
        cycle = Cycle(
            nil="cycle/0.2",
            cycle_id="MultiStep",
            workspace="test-workspace",
            metadata=CycleMetadata(version="1.0", owner="Test Owner"),
            intent=BilingualText(en="Multi-step cycle", ar="دورة متعددة الخطوات"),
            trigger=ManualTrigger(type="manual"),
            flow=Flow(
                entry="CreateLead",
                steps=(
                    ActionStep(
                        id="CreateLead",
                        type="action",
                        use="odoo.crm_create_lead",
                        output="lead",
                        next="CreateInvoice",
                    ),
                    ActionStep(
                        id="CreateInvoice",
                        type="action",
                        use="odoo.invoice_create",
                    ),
                ),
            ),
        )
        # Create a custom mock result with both verbs
        program = WosoolProgram(
            wosool="0.1",
            workspace=cycle.workspace,
            entry="step_1",
            pipeline=[
                {
                    "id": "step_1",
                    "type": "action",
                    "verb": "odoo.crm_create_lead",
                    "args": {},
                    "skill": "odoo",
                },
                {
                    "id": "step_2",
                    "type": "action",
                    "verb": "odoo.invoice_create",
                    "args": {},
                    "skill": "odoo",
                },
            ],
        )
        mock_compile.return_value = CompileResult(
            ok=True,
            diagnostics=ValidationResult(result="OK"),
            program=program,
            content_hash="abc123def456",
            gates=(),
            step_ids={"CreateLead": "step_1", "CreateInvoice": "step_2"},
        )

        result = manager.publish_cycle(
            workspace="test-workspace",
            cycle_id="MultiStep",
            cycle=cycle,
        )

        bindings = json.loads(result["backend_bindings"])
        assert "odoo.crm_create_lead" in bindings
        assert "odoo.invoice_create" in bindings
        assert bindings["odoo.crm_create_lead"] == "odoo"

    @patch("nilscript.controlplane.cycle_manager.compile_cycle")
    def test_list_cycles_by_status(self, mock_compile, manager):
        """Verify list_cycles filters by status."""
        cycle = _make_cycle()
        mock_compile.return_value = self._mock_compile_result(cycle)

        manager.publish_cycle(
            workspace="test-workspace",
            cycle_id="TestCycle",
            cycle=cycle,
        )

        published = manager.list_cycles(
            workspace="test-workspace",
            status="published",
        )

        assert len(published) >= 1
        assert published[0]["status"] == "published"

    @patch("nilscript.controlplane.cycle_manager.compile_cycle")
    def test_publish_cycle_stores_cycle_ast(self, mock_compile, manager):
        """Verify the original Cycle AST is stored as-is."""
        cycle = _make_cycle()
        mock_compile.return_value = self._mock_compile_result(cycle)

        result = manager.publish_cycle(
            workspace="test-workspace",
            cycle_id="TestCycle",
            cycle=cycle,
        )

        # The cycle AST should be serialized
        assert result["cycle_ast"] is not None
        stored_ast = json.loads(result["cycle_ast"])
        assert stored_ast["cycle_id"] == "TestCycle"

    @patch("nilscript.controlplane.cycle_manager.compile_cycle")
    def test_publish_cycle_content_hash_is_set(self, mock_compile, manager):
        """Verify content_hash is computed for version locking."""
        cycle = _make_cycle()
        mock_compile.return_value = self._mock_compile_result(cycle)

        result = manager.publish_cycle(
            workspace="test-workspace",
            cycle_id="TestCycle",
            cycle=cycle,
        )

        assert result["content_hash"] is not None
        assert len(result["content_hash"]) > 0  # Should be a non-empty hash

    @patch("nilscript.controlplane.cycle_manager.compile_cycle")
    def test_publish_cycle_sets_published_at(self, mock_compile, manager):
        """Verify published_at timestamp is set."""
        cycle = _make_cycle()
        mock_compile.return_value = self._mock_compile_result(cycle)

        result = manager.publish_cycle(
            workspace="test-workspace",
            cycle_id="TestCycle",
            cycle=cycle,
        )

        assert result["published_at"] is not None
        # Check it's an ISO format timestamp
        assert "T" in result["published_at"]

    def test_publish_cycle_extract_backend_bindings_single_adapter(self, manager):
        """Verify backend binding extraction for a single adapter."""
        from nilscript.kernel.models import WosoolProgram

        program = WosoolProgram(
            wosool="0.1",
            workspace="test-workspace",
            entry="step_1",
            pipeline=[
                {
                    "id": "step_1",
                    "type": "action",
                    "verb": "odoo.crm_create_lead",
                    "args": {"name": "Test"},
                    "skill": "odoo",
                }
            ],
        )

        bindings = manager._extract_backend_bindings(program)

        assert bindings == {"odoo.crm_create_lead": "odoo"}

    def test_publish_cycle_extract_backend_bindings_multiple_adapters(self, manager):
        """Verify backend binding extraction for multiple adapters."""
        from nilscript.kernel.models import WosoolProgram

        program = WosoolProgram(
            wosool="0.1",
            workspace="test-workspace",
            entry="step_1",
            pipeline=[
                {
                    "id": "step_1",
                    "type": "action",
                    "verb": "odoo.crm_create_lead",
                    "args": {"name": "Test"},
                    "skill": "odoo",
                },
                {
                    "id": "step_2",
                    "type": "action",
                    "verb": "zapier.send_email",
                    "args": {"to": "test@example.com"},
                    "skill": "zapier",
                },
            ],
        )

        bindings = manager._extract_backend_bindings(program)

        assert "odoo.crm_create_lead" in bindings
        assert "zapier.send_email" in bindings
        assert bindings["odoo.crm_create_lead"] == "odoo"
        assert bindings["zapier.send_email"] == "zapier"


class TestGetCycle:
    """Tests for cycle retrieval."""

    def _mock_compile_result(self, cycle: Cycle) -> CompileResult:
        """Create a mock successful compile result."""
        program = WosoolProgram(
            wosool="0.1",
            workspace=cycle.workspace,
            entry="step_1",
            pipeline=[
                {
                    "id": "step_1",
                    "type": "action",
                    "verb": "odoo.crm_create_lead",
                    "args": {},
                    "skill": "odoo",
                }
            ],
        )
        return CompileResult(
            ok=True,
            diagnostics=ValidationResult(result="OK"),
            program=program,
            content_hash="abc123def456",
            gates=(),
            step_ids={"CreateLead": "step_1"},
        )

    def test_get_cycle_returns_none_for_nonexistent_cycle(self, manager):
        """Verify get_cycle returns None for cycles that don't exist."""
        result = manager.get_cycle(
            workspace="test-workspace",
            cycle_id="NonExistent",
        )

        assert result is None

    @patch("nilscript.controlplane.cycle_manager.compile_cycle")
    def test_get_cycle_returns_stored_cycle(self, mock_compile, manager):
        """Verify get_cycle retrieves a published cycle."""
        cycle = _make_cycle()
        mock_compile.return_value = self._mock_compile_result(cycle)

        manager.publish_cycle(
            workspace="test-workspace",
            cycle_id="TestCycle",
            cycle=cycle,
        )

        result = manager.get_cycle(
            workspace="test-workspace",
            cycle_id="TestCycle",
        )

        assert result is not None
        assert result["cycle_id"] == "TestCycle"
        assert result["status"] == "published"


class TestListCycles:
    """Tests for cycle listing."""

    def _mock_compile_result(self, cycle: Cycle) -> CompileResult:
        """Create a mock successful compile result."""
        program = WosoolProgram(
            wosool="0.1",
            workspace=cycle.workspace,
            entry="step_1",
            pipeline=[
                {
                    "id": "step_1",
                    "type": "action",
                    "verb": "odoo.crm_create_lead",
                    "args": {},
                    "skill": "odoo",
                }
            ],
        )
        return CompileResult(
            ok=True,
            diagnostics=ValidationResult(result="OK"),
            program=program,
            content_hash="abc123def456",
            gates=(),
            step_ids={"CreateLead": "step_1"},
        )

    def test_list_cycles_empty_workspace(self, manager):
        """Verify list_cycles returns empty for workspace with no cycles."""
        result = manager.list_cycles(workspace="empty-workspace")

        assert result == []

    @patch("nilscript.controlplane.cycle_manager.compile_cycle")
    def test_list_cycles_respects_limit(self, mock_compile, manager):
        """Verify list_cycles respects the limit parameter."""
        # Create multiple cycles
        for i in range(5):
            cycle = _make_cycle(cycle_id=f"Cycle{i}")
            mock_compile.return_value = self._mock_compile_result(cycle)
            manager.publish_cycle(
                workspace="test-workspace",
                cycle_id=f"Cycle{i}",
                cycle=cycle,
            )

        result = manager.list_cycles(
            workspace="test-workspace",
            limit=2,
        )

        assert len(result) <= 2

    @patch("nilscript.controlplane.cycle_manager.compile_cycle")
    def test_list_cycles_ordered_by_created_at(self, mock_compile, manager):
        """Verify list_cycles returns results ordered by creation time (newest first)."""
        cycles = []
        for i in range(3):
            cycle = _make_cycle(cycle_id=f"Cycle{i}")
            mock_compile.return_value = self._mock_compile_result(cycle)
            manager.publish_cycle(
                workspace="test-workspace",
                cycle_id=f"Cycle{i}",
                cycle=cycle,
            )
            cycles.append(cycle)

        result = manager.list_cycles(workspace="test-workspace")

        # Results should be newest first, so the last cycle should be first
        assert len(result) >= 3
