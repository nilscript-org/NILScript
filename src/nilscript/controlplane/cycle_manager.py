"""Cycle manager — wire the compile pipeline into the control plane.

When a cycle is published, this module triggers compile_cycle and stores the compiled
Flow + backend bindings in the database.
"""

from __future__ import annotations

import json
from typing import Any

from nilscript.cycle import Cycle, compile_cycle
from nilscript.cycle.compile import CompileResult
from nilscript.kernel.context import ValidationContext


class CompileError(Exception):
    """Raised when Cycle compilation fails."""
    pass


class LowerError(Exception):
    """Raised when lowering the compiled plan fails."""
    pass


class CycleManager:
    """Manages the compile pipeline for cycles in the control plane."""

    def __init__(
        self,
        store,  # EventStore instance
        registry: Any | None = None,
        domains: Any | None = None,
    ) -> None:
        """
        Initialize the CycleManager.

        Args:
            store: EventStore instance for database access
            registry: Capability registry (for compile context)
            domains: Domain registry (for compile context)
        """
        self.store = store
        self.registry = registry
        self.domains = domains

    def _get_validation_context(self, workspace: str) -> ValidationContext:
        """Build a ValidationContext for cycle compilation."""
        # Build context from registry if available, otherwise use a minimal empty context
        if self.registry:
            # Extract skills from registry
            skills = {}
            workspaces = {workspace: frozenset()}
            read_verbs = frozenset()
            return ValidationContext(
                skills=skills,
                read_verbs=read_verbs,
                workspaces=workspaces,
            )
        else:
            # Minimal context for testing
            return ValidationContext(
                skills={},
                read_verbs=frozenset(),
                workspaces={workspace: frozenset()},
            )

    def publish_cycle(
        self,
        workspace: str,
        cycle_id: str,
        cycle: Cycle,
    ) -> dict[str, Any]:
        """
        Publish a cycle: compile BizSpec → CompiledPlan → Flow, and store results.

        Args:
            workspace: Workspace identifier
            cycle_id: Cycle identifier
            cycle: Cycle AST to publish

        Returns:
            Dictionary with cycle state, including status, compiled_plan, flow, and any errors

        Raises:
            CompileError: If cycle compilation fails
        """
        # 1. COMPILE the Cycle AST to WosoolProgram IR
        ctx = self._get_validation_context(workspace)
        try:
            compile_result: CompileResult = compile_cycle(cycle, ctx)
        except Exception as e:
            raise CompileError(f"Failed to compile cycle {cycle_id}: {str(e)}") from e

        # Handle compilation failure
        if not compile_result.ok:
            # Extract error messages from diagnostics
            error_lines = []
            for diag in compile_result.diagnostics.diagnostics:
                if diag.severity == "ERROR":
                    error_lines.append(f"{diag.code}: {diag.message}")
            error_msg = " | ".join(error_lines) if error_lines else "Compilation failed with unknown error"
            cycle_data = {
                "workspace": workspace,
                "cycle_id": cycle_id,
                "version": 1,
                "cycle_ast": cycle.model_dump_json(),
                "status": "compile_error",
                "compile_error": error_msg,
                "content_hash": None,
                "backend_bindings": "{}",
                "created_at": self._now(),
                "published_at": None,
            }
            self._store_cycle(cycle_data)
            return cycle_data

        # 2. Extract the compiled plan
        if not compile_result.program:
            error_msg = "Compilation succeeded but program is None"
            cycle_data = {
                "workspace": workspace,
                "cycle_id": cycle_id,
                "version": 1,
                "cycle_ast": cycle.model_dump_json(),
                "status": "compile_error",
                "compile_error": error_msg,
                "content_hash": compile_result.content_hash,
                "backend_bindings": "{}",
                "created_at": self._now(),
                "published_at": None,
            }
            self._store_cycle(cycle_data)
            return cycle_data

        # 3. Extract backend bindings from the program
        # Scan the program's pipeline for verbs and map to adapters
        backend_bindings = self._extract_backend_bindings(compile_result.program)

        # 4. STORE compiled state
        now = self._now()
        cycle_data = {
            "workspace": workspace,
            "cycle_id": cycle_id,
            "version": 1,
            "domain_id": cycle.implements.capability_id if cycle.implements else None,
            "cycle_ast": cycle.model_dump_json(),
            "compiled_plan": compile_result.program.model_dump_json(),
            "flow": self._extract_flow_json(cycle),
            "backend_bindings": json.dumps(backend_bindings),
            "status": "published",
            "compile_error": None,
            "content_hash": compile_result.content_hash,
            "created_at": now,
            "published_at": now,
        }
        self._store_cycle(cycle_data)

        # 5. NOTIFY (could emit to event bus here)
        self._notify_cycle_published(workspace, cycle_id, cycle_data)

        return cycle_data

    def _store_cycle(self, cycle_data: dict[str, Any]) -> None:
        """Store cycle data in the database."""
        with self.store._lock:
            self.store._conn.execute(
                """INSERT OR REPLACE INTO cycles
                   (workspace, cycle_id, version, domain_id, cycle_ast, compiled_plan,
                    flow, backend_bindings, status, compile_error, content_hash,
                    created_at, published_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cycle_data["workspace"],
                    cycle_data["cycle_id"],
                    cycle_data.get("version", 1),
                    cycle_data.get("domain_id"),
                    cycle_data["cycle_ast"],
                    cycle_data.get("compiled_plan"),
                    cycle_data.get("flow"),
                    cycle_data["backend_bindings"],
                    cycle_data["status"],
                    cycle_data.get("compile_error"),
                    cycle_data.get("content_hash"),
                    cycle_data["created_at"],
                    cycle_data.get("published_at"),
                ),
            )
            self.store._conn.commit()

    def _extract_backend_bindings(self, program: Any) -> dict[str, str]:
        """
        Extract backend bindings from a compiled program.

        Scans the pipeline for verbs and maps each to its adapter (for now, we use
        simple heuristics based on verb prefix).

        Args:
            program: WosoolProgram instance

        Returns:
            Dictionary mapping capability identifiers to adapter names
        """
        bindings: dict[str, str] = {}

        # Scan pipeline for verbs and extract bindings
        pipeline = program.pipeline if hasattr(program, "pipeline") else []
        for node in pipeline:
            if isinstance(node, dict):
                verb = node.get("verb")
            else:
                verb = getattr(node, "verb", None)

            if verb and isinstance(verb, str):
                # Simple heuristic: map verb prefix to adapter
                # e.g., "odoo.crm_create_lead" → "odoo"
                adapter = verb.split(".", 1)[0]
                if verb not in bindings:
                    bindings[verb] = adapter

        return bindings

    def _extract_flow_json(self, cycle: Cycle) -> str:
        """Extract and serialize the cycle's flow."""
        return cycle.flow.model_dump_json()

    def _notify_cycle_published(
        self,
        workspace: str,
        cycle_id: str,
        cycle_data: dict[str, Any],
    ) -> None:
        """
        Notify observers that a cycle was published.

        In a full implementation, this would emit to an event bus.
        """
        # Placeholder for event bus emission
        # self.event_bus.publish("cycle.published", {
        #     "workspace": workspace,
        #     "cycle_id": cycle_id,
        #     "status": cycle_data["status"],
        #     "domain_id": cycle_data.get("domain_id"),
        # })
        pass

    @staticmethod
    def _now() -> str:
        """Return current timestamp in ISO format."""
        import datetime
        return datetime.datetime.now(datetime.UTC).isoformat()

    def get_cycle(self, workspace: str, cycle_id: str, version: int = 1) -> dict[str, Any] | None:
        """Retrieve a published cycle from the database."""
        with self.store._lock:
            row = self.store._conn.execute(
                """SELECT * FROM cycles
                   WHERE workspace = ? AND cycle_id = ? AND version = ?""",
                (workspace, cycle_id, version),
            ).fetchone()
            if not row:
                return None
            return dict(row)

    def list_cycles(
        self,
        workspace: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List cycles in a workspace, optionally filtered by status."""
        with self.store._lock:
            if status:
                rows = self.store._conn.execute(
                    """SELECT * FROM cycles
                       WHERE workspace = ? AND status = ?
                       ORDER BY created_at DESC
                       LIMIT ?""",
                    (workspace, status, limit),
                ).fetchall()
            else:
                rows = self.store._conn.execute(
                    """SELECT * FROM cycles
                       WHERE workspace = ?
                       ORDER BY created_at DESC
                       LIMIT ?""",
                    (workspace, limit),
                ).fetchall()
            return [dict(row) for row in rows]
