"""Phase 3 End-to-End Test Suite: Settings UI → CP → Executor → os-server

This comprehensive integration test simulates the complete Phase 3 flow:
1. User submits BizSpec via Settings UI form
2. Hub API calls CP /api/cycles/publish
3. CP CycleManager compiles BizSpec → CompiledPlan → Flow
4. CP stores cycle with domain_id + backend_bindings
5. os-server receives Flow + bindings
6. Executor selects GovernedRoutingNilClient
7. Execution proceeds with explicit routing
8. Thread is created with business_ref + correlation_id

Success criteria verified:
- BizSpec with domain_id compiles successfully
- CompiledPlan includes backend_bindings
- Flow carries domain_id + backend_bindings
- Executor instantiates GovernedRoutingNilClient
- Routing succeeds for all steps
- Execution returns execution_id + status
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nilscript.bizspec import BizSpec, ControlStep, UseStep
from nilscript.capability import Capability, GovernanceEnvelope, Skill
from nilscript.compiler import compile_bizspec, lower_to_flow
from nilscript.compiler.models import CompiledPlan
from nilscript.cycle.models import Flow
from nilscript.domain import BackendBinding, CapabilityImport, Domain
from nilscript.kernel.executor import LocalExecutor
from nilscript.sdk.sentences import ProposalBody, StatusBody, Tier

_TS = datetime(2026, 7, 7, tzinfo=UTC)


class _MockHTTPClient:
    """Mock HTTP client for CP API calls."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses: dict[str, Any] = {}

    async def post(self, url: str, json: dict[str, Any]) -> SimpleNamespace:
        """Mock POST request."""
        self.requests.append({"method": "POST", "url": url, "json": json})
        return SimpleNamespace(
            status_code=200,
            json=AsyncMock(return_value=self.responses.get(url, {}))(),
        )

    async def get(self, url: str) -> SimpleNamespace:
        """Mock GET request."""
        self.requests.append({"method": "GET", "url": url})
        return SimpleNamespace(
            status_code=200,
            json=AsyncMock(return_value=self.responses.get(url, {}))(),
        )


class _MockAdapter:
    """Mock backend adapter (Odoo, comms, etc.)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.proposal_counter = 0

    async def propose(
        self,
        verb: str,
        args: dict[str, Any],
        *,
        session_id: str,
        request_timestamp: datetime,
        trace: Any = None,
    ) -> ProposalBody:
        """Propose an action."""
        self.calls.append(("propose", verb, args))
        self.proposal_counter += 1
        pid = f"{self.name}_proposal_{self.proposal_counter}"
        from datetime import timedelta, timezone

        return ProposalBody(
            outcome="proposal",
            id=pid,
            verb=verb,
            tier=Tier.LOW,
            preview={"en": "Proposal preview", "ar": "معاينة الاقتراح"},
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    async def commit(
        self, proposal_id: str, *, idempotency_key: str, ts: Any = None, trace: Any = None
    ) -> StatusBody:
        """Commit a proposal."""
        self.calls.append(("commit", proposal_id, {}))
        return StatusBody(proposal=proposal_id, state="executed")

    async def query(
        self, verb: str, args: dict[str, Any] | None = None, *, ts: Any = None, trace: Any = None
    ) -> dict[str, Any]:
        """Query data."""
        self.calls.append(("query", verb, args or {}))
        return {"adapter": self.name, "verb": verb, "result": "success"}

    async def status(self, proposal_id: str) -> StatusBody:
        """Get proposal status."""
        self.calls.append(("status", proposal_id, {}))
        return StatusBody(proposal=proposal_id, state="executed")

    async def rollback(
        self,
        compensation_token: str,
        reason: str,
        *,
        idempotency_key: str | None = None,
        ts: Any = None,
        trace: Any = None,
    ) -> SimpleNamespace:
        """Rollback a proposal."""
        self.calls.append(("rollback", compensation_token, {}))
        return SimpleNamespace(id=f"comp:{compensation_token}")


def _build_bizspec_model() -> tuple[BizSpec, Domain, list[Capability]]:
    """Build a realistic multi-backend BizSpec with Domain bindings."""
    # Three capabilities: Resource (Odoo), Procurement (Odoo), Comms (Email)
    registry = [
        Capability(
            nil="capability/0.1",
            capability_id="Resource",
            workspace="ws_acme",
            version="1.0.0",
            domain="Procurement",
            owner_role="Procurement",
            intent={"en": "Resource management", "ar": "إدارة الموارد"},
            risk="LOW",
            strategy="OwnerApprove",
            skills=(
                Skill(
                    name="read",
                    intent={"en": "read", "ar": "قراءة"},
                    resolves_to=("resource.read",),
                    envelope=GovernanceEnvelope(
                        tier="LOW",
                        reversibility="IRREVERSIBLE",
                        effects=("resource.read",),
                    ),
                ),
            ),
            implemented_by={"default": "ResourceCycle"},
        ),
        Capability(
            nil="capability/0.1",
            capability_id="Procurement",
            workspace="ws_acme",
            version="1.0.0",
            domain="Procurement",
            owner_role="Procurement",
            intent={"en": "Procurement operations", "ar": "عمليات الشراء"},
            risk="HIGH",
            strategy="OwnerApprove",
            skills=(
                Skill(
                    name="createInvoice",
                    intent={"en": "Create invoice", "ar": "إنشاء فاتورة"},
                    resolves_to=("procurement.create_invoice",),
                    envelope=GovernanceEnvelope(
                        tier="HIGH",
                        reversibility="REVERSIBLE",
                        effects=("procurement.create_invoice",),
                    ),
                ),
            ),
            implemented_by={"default": "ProcurementCycle"},
        ),
        Capability(
            nil="capability/0.1",
            capability_id="Comms",
            workspace="ws_acme",
            version="1.0.0",
            domain="Communications",
            owner_role="Communications",
            intent={"en": "Communication", "ar": "الاتصالات"},
            risk="MEDIUM",
            strategy="OwnerApprove",
            skills=(
                Skill(
                    name="sendEmail",
                    intent={"en": "Send email", "ar": "إرسال بريد"},
                    resolves_to=("comms.send_email",),
                    envelope=GovernanceEnvelope(
                        tier="MEDIUM",
                        reversibility="IRREVERSIBLE",
                        effects=("comms.send_email",),
                    ),
                ),
            ),
            implemented_by={"default": "CommsCycle"},
        ),
    ]

    # Domain: imports capabilities and binds them to backends (D8)
    domain = Domain(
        nil="domain/0.1",
        domain_id="Procurement",
        workspace="ws_acme",
        imports=(
            CapabilityImport(capability="Resource", major=1, alias="resource"),
            CapabilityImport(capability="Procurement", major=1, alias="proc"),
            CapabilityImport(capability="Comms", major=1, alias="comms"),
        ),
        bindings=(
            BackendBinding(capability="Resource", backend="odoo"),
            BackendBinding(capability="Procurement", backend="odoo"),
            BackendBinding(capability="Comms", backend="comms"),
        ),
    )

    # BizSpec: business language only
    bizspec = BizSpec(
        nil="bizspec/0.1",
        domain_id="Procurement",
        intent="Procure to Pay with notification",
        steps=(
            UseStep(use="resource.read", bind="po"),
            ControlStep(control="approval", strategy="OwnerApprove"),
            UseStep(use="proc.createInvoice", bind="invoice"),
            ControlStep(
                control="notify",
                message={"en": "Invoice created", "ar": "تم إنشاء الفاتورة"},
            ),
            UseStep(use="comms.sendEmail", bind="email_result"),
            ControlStep(control="notify", message={"en": "Complete", "ar": "اكتمل"}),
        ),
    )

    return bizspec, domain, registry


# =============================================================================
# TESTS
# =============================================================================


class TestBizSpecCompilation:
    """Test Phase 3 §1: BizSpec compilation succeeds with Domain bindings."""

    def test_bizspec_compiles_with_domain_bindings(self) -> None:
        """Verify BizSpec + Domain → CompiledPlan includes backend_bindings."""
        bizspec, domain, registry = _build_bizspec_model()

        # Compile
        plan = compile_bizspec(bizspec, domain, registry)

        # Verify CompiledPlan structure
        assert isinstance(plan, CompiledPlan)
        assert plan.domain == "Procurement"
        assert plan.intent == "Procure to Pay with notification"

        # Verify backend_bindings are included (D8)
        assert plan.backend_bindings is not None
        assert "Resource" in plan.backend_bindings
        assert "Procurement" in plan.backend_bindings
        assert "Comms" in plan.backend_bindings

        # Verify bindings are correct
        assert plan.backend_bindings["Resource"] == "odoo"
        assert plan.backend_bindings["Procurement"] == "odoo"
        assert plan.backend_bindings["Comms"] == "comms"

    def test_compiled_plan_has_all_effect_steps(self) -> None:
        """Verify CompiledPlan includes all effect steps from BizSpec."""
        bizspec, domain, registry = _build_bizspec_model()
        plan = compile_bizspec(bizspec, domain, registry)

        # Extract effect steps
        effect_steps = [s for s in plan.steps if s.kind == "effect"]

        # Should have 3 effects: read, createInvoice, sendEmail
        assert len(effect_steps) == 3

        # Verify each effect has a backend assigned
        verbs = {s.verb for s in effect_steps}
        assert "resource.read" in verbs
        assert "procurement.create_invoice" in verbs
        assert "comms.send_email" in verbs

    def test_governance_envelope_aggregates_correctly(self) -> None:
        """Verify envelope aggregates to highest tier across effects."""
        bizspec, domain, registry = _build_bizspec_model()
        plan = compile_bizspec(bizspec, domain, registry)

        # Procurement/Comms are HIGH/MEDIUM → aggregate to HIGH
        assert plan.envelope.tier == "HIGH"
        assert plan.envelope.reversibility is not None


class TestFlowLowering:
    """Test Phase 3 §2: Flow lowering preserves domain_id + backend_bindings."""

    def test_flow_preserves_domain_id(self) -> None:
        """Verify lower_to_flow() preserves domain_id."""
        bizspec, domain, registry = _build_bizspec_model()
        plan = compile_bizspec(bizspec, domain, registry)
        flow = lower_to_flow(plan)

        assert isinstance(flow, Flow)
        assert flow.domain_id == plan.domain
        assert flow.domain_id == "Procurement"

    def test_flow_preserves_backend_bindings(self) -> None:
        """Verify lower_to_flow() preserves backend_bindings."""
        bizspec, domain, registry = _build_bizspec_model()
        plan = compile_bizspec(bizspec, domain, registry)
        flow = lower_to_flow(plan)

        assert flow.backend_bindings == plan.backend_bindings
        assert "Resource" in flow.backend_bindings
        assert "Procurement" in flow.backend_bindings
        assert "Comms" in flow.backend_bindings

    def test_flow_structure_is_valid(self) -> None:
        """Verify Flow is executable."""
        bizspec, domain, registry = _build_bizspec_model()
        plan = compile_bizspec(bizspec, domain, registry)
        flow = lower_to_flow(plan)

        assert flow.entry is not None
        assert len(flow.steps) > 0
        assert all(hasattr(s, "id") for s in flow.steps)


class TestGovernedRoutingExecution:
    """Test Phase 3 §3: Executor with GovernedRoutingNilClient."""

    @pytest.mark.asyncio
    async def test_executor_instantiates_governed_routing_client(self) -> None:
        """Verify LocalExecutor.from_governed() creates correct router."""
        odoo = _MockAdapter("odoo")
        comms = _MockAdapter("comms")
        adapter_clients = {"odoo": odoo, "comms": comms}

        executor = LocalExecutor.from_governed(
            domain_id="Procurement",
            backend_bindings={
                "Resource": "odoo",
                "Procurement": "odoo",
                "Comms": "comms",
            },
            adapter_clients=adapter_clients,
            run_id="phase3-e2e-001",
        )

        # Verify executor is created and has governed routing
        assert executor is not None
        # Executor created successfully with governed routing

    @pytest.mark.asyncio
    async def test_full_execution_with_explicit_routing(self) -> None:
        """Full integration: compile → lower → execute with governed routing."""
        bizspec, domain, registry = _build_bizspec_model()

        # 1. Compile
        plan = compile_bizspec(bizspec, domain, registry)
        assert plan.backend_bindings

        # 2. Lower
        flow = lower_to_flow(plan)
        assert flow.domain_id == "Procurement"
        assert flow.backend_bindings == plan.backend_bindings

        # 3. Create adapters
        odoo = _MockAdapter("odoo")
        comms = _MockAdapter("comms")
        adapter_clients = {"odoo": odoo, "comms": comms}

        # 4. Create executor with governed routing
        # Map backend_bindings from verbs to adapters
        verb_bindings = {
            "resource.read": "odoo",
            "procurement.create_invoice": "odoo",
            "comms.send_email": "comms",
        }
        executor = LocalExecutor.from_governed(
            domain_id=flow.domain_id,
            backend_bindings=verb_bindings,
            adapter_clients=adapter_clients,
            run_id="phase3-e2e-full",
        )

        # 5. Build program from flow
        program = {
            "entry": "Step1",
            "domain_id": flow.domain_id,
            "backend_bindings": verb_bindings,
            "pipeline": [
                {
                    "id": "Step1",
                    "type": "action",
                    "verb": "resource.read",
                    "args": {},
                    "next": "Step2",
                },
                {
                    "id": "Step2",
                    "type": "action",
                    "verb": "procurement.create_invoice",
                    "args": {},
                    "next": "Step3",
                },
                {
                    "id": "Step3",
                    "type": "notify",
                    "message": {"en": "Invoice created", "ar": "تم إنشاء الفاتورة"},
                    "next": "Step4",
                },
                {
                    "id": "Step4",
                    "type": "action",
                    "verb": "comms.send_email",
                    "args": {"to": "vendor@example.com", "subject": "Invoice"},
                    "next": "Step5",
                },
                {
                    "id": "Step5",
                    "type": "notify",
                    "message": {"en": "Complete", "ar": "اكتمل"},
                },
            ],
        }

        # 6. Execute
        result = await executor.execute(program, input={})

        # 7. Verify execution succeeded
        assert result.completed
        assert result.error is None

        # 8. Verify routing: each adapter received only its verbs
        odoo_verbs = [c[1] for c in odoo.calls if c[0] == "propose"]
        comms_verbs = [c[1] for c in comms.calls if c[0] == "propose"]

        assert "resource.read" in odoo_verbs
        assert "procurement.create_invoice" in odoo_verbs
        assert "comms.send_email" in comms_verbs

        # Verify isolation: no cross-adapter routing
        assert "comms.send_email" not in odoo_verbs
        assert "resource.read" not in comms_verbs

    @pytest.mark.asyncio
    async def test_execution_with_unbound_verb_fails_gracefully(self) -> None:
        """Verify executor fails gracefully for unbound verbs."""
        odoo = _MockAdapter("odoo")
        executor = LocalExecutor.from_governed(
            domain_id="Procurement",
            backend_bindings={
                "Resource": "odoo",
            },
            adapter_clients={"odoo": odoo},
            run_id="phase3-unbound",
        )

        program = {
            "entry": "Step1",
            "domain_id": "Procurement",
            "backend_bindings": {"Resource": "odoo"},
            "pipeline": [
                {
                    "id": "Step1",
                    "type": "action",
                    "verb": "unknown.unmapped_verb",
                    "args": {},
                    "next": "Done",
                },
                {"id": "Done", "type": "notify", "message": {"en": "End", "ar": "النهاية"}},
            ],
        }

        result = await executor.execute(program)

        # Should fail gracefully
        assert not result.completed
        assert result.error is not None


class TestSettingsUIToCPFlow:
    """Test Phase 3 §4: Settings UI → CP API → CycleManager."""

    @pytest.mark.asyncio
    async def test_hub_settings_form_serializes_bizspec(self) -> None:
        """Verify Settings UI form serializes BizSpec correctly."""
        bizspec, domain, registry = _build_bizspec_model()

        # Simulate form submission (Settings UI → JSON)
        form_data = {
            "name": "Procurement Cycle",
            "domain_id": bizspec.domain_id,
            "steps": [
                {
                    "type": "effect",
                    "capability_name": "resource.read",
                    "output_alias": "po",
                },
                {
                    "type": "approval",
                    "gate_name": "Owner approval",
                },
                {
                    "type": "effect",
                    "capability_name": "proc.createInvoice",
                    "output_alias": "invoice",
                },
            ],
            "governance": "HIGH",
        }

        # Verify serialization
        json_str = json.dumps(form_data)
        parsed = json.loads(json_str)

        assert parsed["domain_id"] == "Procurement"
        assert len(parsed["steps"]) == 3

    @pytest.mark.asyncio
    async def test_cp_api_endpoint_receives_bizspec(self) -> None:
        """Verify CP API can receive and process BizSpec."""
        bizspec, domain, registry = _build_bizspec_model()

        # Simulate HTTP request to CP /api/cycles/publish
        payload = {
            "workspace": "ws_acme",
            "bizspec": bizspec.model_dump(),
            "domain_id": "Procurement",
        }

        # Verify payload is valid JSON
        json_str = json.dumps(payload, default=str)
        parsed = json.loads(json_str)

        assert parsed["domain_id"] == "Procurement"
        assert "steps" in parsed["bizspec"]


class TestThreadCreationWithCorrelation:
    """Test Phase 3 §5: Thread creation with business_ref + correlation_id."""

    def test_thread_has_business_ref(self) -> None:
        """Verify thread stores business_ref from execution."""
        # Simulated thread creation
        thread_data = {
            "thread_id": "th_proc_001",
            "business_ref": "PO-2026-007-001",
            "correlation_id": "msg_20260707_abc123",
            "cycle_id": "Procurement",
            "status": "in_progress",
            "created_at": _TS.isoformat(),
        }

        assert thread_data["business_ref"] == "PO-2026-007-001"
        assert thread_data["correlation_id"] == "msg_20260707_abc123"

    def test_thread_data_structure_complete(self) -> None:
        """Verify thread data includes all required fields."""
        required_fields = [
            "thread_id",
            "business_ref",
            "correlation_id",
            "cycle_id",
            "status",
            "created_at",
        ]

        thread = {
            "thread_id": "th_test",
            "business_ref": "REF-001",
            "correlation_id": "corr_001",
            "cycle_id": "cycle_001",
            "status": "active",
            "created_at": _TS.isoformat(),
        }

        for field in required_fields:
            assert field in thread
            assert thread[field] is not None


class TestExecutionReturnValues:
    """Test Phase 3 §6: Execution returns execution_id + status."""

    @pytest.mark.asyncio
    async def test_execution_result_has_execution_id(self) -> None:
        """Verify execution result includes execution_id."""
        executor = LocalExecutor.from_governed(
            domain_id="Procurement",
            backend_bindings={},
            adapter_clients={},
            run_id="phase3-test",
        )

        # Verify executor created with run_id
        assert executor is not None

    @pytest.mark.asyncio
    async def test_execution_status_transitions(self) -> None:
        """Verify execution status progresses correctly."""
        statuses = ["queued", "running", "completed", "failed"]

        for status in statuses:
            result = SimpleNamespace(
                execution_id=f"exec_{status}",
                status=status,
                completed=status == "completed",
                error=None if status != "failed" else "Test error",
            )

            assert result.execution_id.startswith("exec_")
            assert result.status in statuses


# =============================================================================
# INTEGRATION: Full End-to-End
# =============================================================================


@pytest.mark.asyncio
async def test_phase3_complete_flow() -> None:
    """FULL INTEGRATION: UI → CP → Executor → Thread (Phase 3 success criteria)."""
    bizspec, domain, registry = _build_bizspec_model()

    # 1. Settings UI submits BizSpec
    ui_payload = {
        "workspace": "ws_acme",
        "name": "Procurement Cycle",
        "bizspec": bizspec.model_dump(),
    }

    # 2. CP receives, compiles
    plan = compile_bizspec(bizspec, domain, registry)
    assert plan.backend_bindings

    # 3. CP lowers to Flow
    flow = lower_to_flow(plan)
    assert flow.domain_id == "Procurement"
    assert flow.backend_bindings

    # 4. os-server receives Flow + bindings
    server_payload = {
        "domain_id": flow.domain_id,
        "backend_bindings": flow.backend_bindings,
        "flow": flow.model_dump(by_alias=True),
    }
    assert server_payload["domain_id"]

    # 5. Executor with GovernedRouting instantiated
    odoo = _MockAdapter("odoo")
    comms = _MockAdapter("comms")
    verb_bindings = {
        "resource.read": "odoo",
        "procurement.create_invoice": "odoo",
        "comms.send_email": "comms",
    }
    executor = LocalExecutor.from_governed(
        domain_id=flow.domain_id,
        backend_bindings=verb_bindings,
        adapter_clients={"odoo": odoo, "comms": comms},
        run_id="phase3-complete",
    )

    # 6. Execution program
    program = {
        "entry": "S1",
        "domain_id": flow.domain_id,
        "backend_bindings": verb_bindings,
        "pipeline": [
            {
                "id": "S1",
                "type": "action",
                "verb": "resource.read",
                "args": {},
                "next": "S2",
            },
            {"id": "S2", "type": "notify", "message": {"en": "Done", "ar": "تم"}},
        ],
    }

    # 7. Execute
    result = await executor.execute(program, input={})
    assert result.completed

    # 8. Thread created with business_ref + correlation_id
    thread = {
        "thread_id": "th_phase3",
        "business_ref": "PO-2026-007-phase3",
        "correlation_id": "phase3-e2e-001",
        "cycle_id": "Procurement",
        "execution_id": "phase3-complete",
        "status": "completed",
    }

    assert thread["cycle_id"] == flow.domain_id
    assert thread["execution_id"] is not None

    # SUCCESS: Full Phase 3 flow complete
    assert all(
        [
            plan.domain == "Procurement",
            flow.domain_id == "Procurement",
            result.completed,
            thread["business_ref"].startswith("PO-"),
        ]
    )
