"""End-to-end integration test: compiled cycle → governed execution.

This test verifies the full pipeline:
1. Compile a cycle with explicit Domain bindings (CompiledPlan)
2. Lower to Flow (carrying domain_id + backend_bindings)
3. Execute via LocalExecutor with GovernedRoutingNilClient
4. Verify verbs route to their bound adapters

Simulates a real procurement cycle that spans multiple backends (CRM reads from Odoo,
email sends through comms adapter).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from nilscript.compiler.models import CompiledEnvelope, CompiledPlan, CompiledStep
from nilscript.compiler.lower import lower_to_flow
from nilscript.cycle.models import CycleStep
from nilscript.kernel.executor import LocalExecutor
from nilscript.sdk.sentences import ProposalBody, StatusBody, Tier

_TS = datetime(2026, 7, 4, tzinfo=UTC)


class _MockAdapter:
    """Mock backend adapter (Odoo, comms, etc.)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.proposal_counter = 0

    async def propose(self, verb, args, *, session_id, request_timestamp, trace=None):
        from datetime import datetime, timedelta, timezone
        self.calls.append(("propose", verb, args))
        self.proposal_counter += 1
        # Generate a valid proposal ID matching PROPOSAL_ID_PATTERN (8-128 chars, [A-Za-z0-9_-])
        pid = f"{self.name}_proposal_{self.proposal_counter}"
        return ProposalBody(
            outcome="proposal",
            id=pid,
            verb=verb,
            tier=Tier.LOW,
            preview={"en": "Proposal preview", "ar": "معاينة الاقتراح"},
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    async def commit(self, proposal_id, *, idempotency_key, ts=None, trace=None):
        self.calls.append(("commit", proposal_id, {}))
        return StatusBody(
            proposal=proposal_id,
            state="executed",
        )

    async def query(self, verb, args=None, *, ts=None, trace=None):
        self.calls.append(("query", verb, args or {}))
        return {
            "adapter": self.name,
            "verb": verb,
            "result": "success",
        }

    async def status(self, proposal_id):
        self.calls.append(("status", proposal_id, {}))
        return StatusBody(
            proposal=proposal_id,
            state="executed",
        )

    async def rollback(self, compensation_token, reason, *, idempotency_key=None, ts=None, trace=None):
        self.calls.append(("rollback", compensation_token, {}))
        return SimpleNamespace(id=f"comp:{compensation_token}")


def _procurement_compiled_plan() -> CompiledPlan:
    """Build a compiled procurement cycle with multi-backend bindings.

    Simulates:
    - Read vendor list from CRM (Odoo)
    - Create purchase invoice (Odoo)
    - Send notification email (comms)
    """
    return CompiledPlan(
        domain="ws_acme_procurement@1.0.0",
        intent="Create purchase invoice and notify vendor",
        steps=(
            CompiledStep(
                kind="effect",
                capability="resource.list_vendors",
                version="1.0.0",
                skill="resource",
                verb="odoo.list_vendors",
                backend="odoo",
                args={"category": "active"},
                bind="vendors",
            ),
            CompiledStep(
                kind="effect",
                capability="procurement.create_invoice",
                version="1.0.0",
                skill="procurement",
                verb="odoo.create_purchase_invoice",
                backend="odoo",
                args={"po_id": "$.input.po_id", "vendor_id": "$.vendors.id"},
                bind="invoice",
            ),
            CompiledStep(
                kind="control",
                control="notify",
                message={
                    "en": "Invoice created",
                    "ar": "تم إنشاء الفاتورة",
                },
            ),
            CompiledStep(
                kind="effect",
                capability="comms.send_email",
                version="1.0.0",
                skill="comms",
                verb="comms.send_email",
                backend="comms",
                args={
                    "to": "vendor@example.com",
                    "subject": "Purchase Invoice",
                    "body": "Invoice ID: $.invoice.id",
                },
                bind="email_result",
            ),
        ),
        envelope=CompiledEnvelope(
            tier="MEDIUM",
            reversibility="REVERSIBLE",
            effects=("resource.list_vendors", "procurement.create_invoice", "comms.send_email"),
        ),
        backend_bindings={
            "odoo.list_vendors": "odoo",
            "odoo.create_purchase_invoice": "odoo",
            "comms.send_email": "comms",
        },
    )


@pytest.mark.asyncio
async def test_procurement_cycle_with_governed_routing() -> None:
    """Full integration: compiled procurement cycle routes via Domain bindings."""
    # 1. Build compiled plan with explicit bindings
    plan = _procurement_compiled_plan()
    assert plan.backend_bindings
    assert plan.domain == "ws_acme_procurement@1.0.0"

    # 2. Lower to Flow (carries domain_id + backend_bindings)
    flow = lower_to_flow(plan)
    assert flow.domain_id == "ws_acme_procurement@1.0.0"
    assert flow.backend_bindings == plan.backend_bindings
    assert len(flow.steps) >= len(plan.steps)

    # 3. Prepare adapters
    odoo = _MockAdapter("odoo")
    comms = _MockAdapter("comms")
    adapter_clients = {"odoo": odoo, "comms": comms}

    # 4. Create executor with governed routing
    executor = LocalExecutor.from_governed(
        domain_id=flow.domain_id,
        backend_bindings=flow.backend_bindings,
        adapter_clients=adapter_clients,
        run_id="proc-cycle-001",
    )

    # 5. Convert flow to kernel program format (simplified for testing)
    # In production, this would be the serialized Flow from the control plane
    program = {
        "entry": "Step1",
        "domain_id": flow.domain_id,
        "backend_bindings": flow.backend_bindings,
        "pipeline": [
            {
                "id": "Step1",
                "type": "action",
                "verb": "odoo.list_vendors",
                "args": {"category": "active"},
                "next": "Step2",
            },
            {
                "id": "Step2",
                "type": "action",
                "verb": "odoo.create_purchase_invoice",
                "args": {"po_id": "PO-123", "vendor_id": "V-456"},
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
                "args": {
                    "to": "vendor@example.com",
                    "subject": "Purchase Invoice",
                    "body": "Invoice ID: INV-789",
                },
                "next": "Done",
            },
            {
                "id": "Done",
                "type": "notify",
                "message": {"en": "Complete", "ar": "اكتمل"},
            },
        ],
    }

    # 6. Execute the program
    result = await executor.execute(program, input={"po_id": "PO-123"})

    # 7. Verify success
    assert result.completed
    assert result.error is None

    # 8. Verify routing: odoo adapter received both its verbs, comms received email
    odoo_verbs = [c[1] for c in odoo.calls if c[0] == "propose"]
    comms_verbs = [c[1] for c in comms.calls if c[0] == "propose"]

    assert "odoo.list_vendors" in odoo_verbs
    assert "odoo.create_purchase_invoice" in odoo_verbs
    assert "comms.send_email" in comms_verbs

    # Odoo should NOT have received email verb
    assert "comms.send_email" not in odoo_verbs
    # Comms should NOT have received procurement verbs
    assert "odoo.list_vendors" not in comms_verbs
    assert "odoo.create_purchase_invoice" not in comms_verbs


@pytest.mark.asyncio
async def test_flow_preserves_bindings_through_lower() -> None:
    """Verify lower_to_flow() preserves domain_id and backend_bindings from CompiledPlan."""
    plan = _procurement_compiled_plan()
    flow = lower_to_flow(plan)

    # Domain and bindings are carried through
    assert flow.domain_id == plan.domain
    assert flow.backend_bindings == plan.backend_bindings

    # Flow structure is correct
    assert flow.entry is not None
    assert len(flow.steps) > 0


@pytest.mark.asyncio
async def test_executor_rejects_unbound_capability() -> None:
    """Verify executor fails gracefully when cycle attempts unbound capability."""
    odoo = _MockAdapter("odoo")
    comms = _MockAdapter("comms")
    adapter_clients = {"odoo": odoo, "comms": comms}

    executor = LocalExecutor.from_governed(
        domain_id="ws_acme_procurement@1.0.0",
        backend_bindings={
            "odoo.list_vendors": "odoo",
            "comms.send_email": "comms",
        },
        adapter_clients=adapter_clients,
        run_id="proc-cycle-002",
    )

    # Program references a verb NOT in bindings
    program = {
        "entry": "Step1",
        "domain_id": "ws_acme_procurement@1.0.0",
        "backend_bindings": {
            "odoo.list_vendors": "odoo",
            "comms.send_email": "comms",
        },
        "pipeline": [
            {
                "id": "Step1",
                "type": "action",
                "verb": "unknown.unmapped_verb",  # Not in bindings
                "args": {},
                "next": "Done",
            },
            {"id": "Done", "type": "notify", "message": {"en": "End", "ar": "النهاية"}},
        ],
    }

    result = await executor.execute(program)
    # The executor catches the error and returns it in the result
    assert not result.completed
    assert result.error is not None
    assert "No backend binding for 'unknown.unmapped_verb'" in result.error
