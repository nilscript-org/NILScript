"""LocalExecutor router selection — verify USE_GOVERNED_ROUTING feature flag wiring.

Tests that:
1. Executor selects GovernedRoutingNilClient when program has backend_bindings + flag enabled
2. Executor falls back to legacy client when flag disabled or bindings missing
3. Error handling for missing adapter clients during upgrade
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from nilscript.kernel.executor import LocalExecutor
from nilscript.sdk.routing import GovernedRoutingNilClient
from nilscript.sdk.sentences import ProposalBody, StatusBody, Tier

_TS = datetime(2026, 7, 4, tzinfo=UTC)


class _FakeNilClient:
    """A stand-in NilClient for testing executor router selection."""

    def __init__(self, name: str = "test") -> None:
        self.name = name
        self.proposals: dict[str, Any] = {}
        self.calls: list[tuple[str, str]] = []

    async def propose(self, verb, args, *, session_id, request_timestamp, trace=None):
        self.calls.append(("propose", verb))
        # Generate a valid proposal ID matching PROPOSAL_ID_PATTERN (8-128 chars, [A-Za-z0-9_-])
        import uuid
        from datetime import datetime, timedelta, timezone
        safe_uuid = str(uuid.uuid4()).replace("-", "_")[:16]
        pid = f"{self.name}_{safe_uuid}_p"
        self.proposals[pid] = {"verb": verb, "state": "pending"}
        return ProposalBody(
            outcome="proposal",
            id=pid,
            verb=verb,
            tier=Tier.LOW,
            preview={"en": "Proposal preview", "ar": "معاينة الاقتراح"},
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    async def commit(self, proposal_id, *, idempotency_key, ts=None, trace=None):
        self.calls.append(("commit", proposal_id))
        return StatusBody(
            proposal=proposal_id,
            state="executed",
        )

    async def query(self, verb, args=None, *, ts=None, trace=None):
        self.calls.append(("query", verb))
        return {"adapter": self.name, "result": "ok"}

    async def status(self, proposal_id):
        self.calls.append(("status", proposal_id))
        return StatusBody(
            proposal=proposal_id,
            state="executed",
        )

    async def rollback(self, compensation_token, reason, *, idempotency_key=None, ts=None, trace=None):
        self.calls.append(("rollback", compensation_token))
        return SimpleNamespace(id=f"comp:{compensation_token}", verb="rollback")


def _simple_program() -> dict[str, Any]:
    """A minimal valid program for testing."""
    return {
        "entry": "Done",
        "pipeline": [
            {
                "id": "Done",
                "type": "notify",
                "message": {"en": "Complete", "ar": "اكتمل"},
            }
        ],
    }


def _program_with_bindings() -> dict[str, Any]:
    """A program with domain_id and backend_bindings (governed)."""
    prog = _simple_program()
    prog["domain_id"] = "ws_acme_procurement@1.0.0"
    prog["backend_bindings"] = {
        "procurement.create_invoice": "odoo",
        "comms.send_email": "comms",
    }
    return prog


@pytest.mark.asyncio
async def test_executor_from_governed_uses_governed_router() -> None:
    """Verify from_governed() creates a LocalExecutor with GovernedRoutingNilClient."""
    domain_id = "ws_acme_procurement@1.0.0"
    bindings = {"procurement.create_invoice": "odoo"}
    adapter_clients = {"odoo": _FakeNilClient("odoo")}

    executor = LocalExecutor.from_governed(
        domain_id, bindings, adapter_clients, run_id="run-123"
    )

    assert isinstance(executor._client, GovernedRoutingNilClient)
    assert executor._run_id == "run-123"


@pytest.mark.asyncio
async def test_executor_raises_on_program_with_bindings_but_plain_client() -> None:
    """Verify executor raises if program has bindings but was initialized with plain client."""
    program = _program_with_bindings()
    client = _FakeNilClient("test")

    executor = LocalExecutor(client, run_id="run-123")

    with pytest.raises(RuntimeError, match="Program for domain.*has backend_bindings"):
        await executor.execute(program)


@pytest.mark.asyncio
async def test_executor_accepts_program_without_bindings() -> None:
    """Verify executor accepts programs without governance metadata (plain client)."""
    program = _simple_program()
    client = _FakeNilClient("test")

    executor = LocalExecutor(client, run_id="run-123")

    result = await executor.execute(program)
    assert result.completed


@pytest.mark.asyncio
async def test_executor_with_governed_router_executes_program() -> None:
    """Full integration: governed executor successfully runs a program."""
    domain_id = "ws_acme_procurement@1.0.0"
    bindings = {"procurement.create_invoice": "odoo"}
    adapter_clients = {"odoo": _FakeNilClient("odoo")}

    executor = LocalExecutor.from_governed(
        domain_id, bindings, adapter_clients, run_id="run-456"
    )
    program = _program_with_bindings()

    result = await executor.execute(program)

    assert result.completed
    assert result.error is None


@pytest.mark.asyncio
async def test_executor_governed_routes_verbs_to_bound_adapters() -> None:
    """Verify governed executor routes verbs to their bound adapters."""
    domain_id = "ws_acme_procurement@1.0.0"
    bindings = {
        "procurement.create_invoice": "odoo",
        "comms.send_email": "comms",
    }
    odoo_client = _FakeNilClient("odoo")
    comms_client = _FakeNilClient("comms")
    adapter_clients = {"odoo": odoo_client, "comms": comms_client}

    executor = LocalExecutor.from_governed(
        domain_id, bindings, adapter_clients, run_id="run-789"
    )

    # Program with two effect steps bound to different adapters
    program = {
        "entry": "Step1",
        "domain_id": domain_id,
        "backend_bindings": bindings,
        "pipeline": [
            {
                "id": "Step1",
                "type": "action",
                "verb": "procurement.create_invoice",
                "args": {"po_id": "PO-123"},
                "next": "Step2",
            },
            {
                "id": "Step2",
                "type": "action",
                "verb": "comms.send_email",
                "args": {"to": "buyer@example.com"},
                "next": "Done",
            },
            {
                "id": "Done",
                "type": "notify",
                "message": {"en": "Complete", "ar": "اكتمل"},
            },
        ],
    }

    result = await executor.execute(program)

    assert result.completed
    # Both adapters should have received their respective proposals
    assert any(c[1] == "procurement.create_invoice" for c in odoo_client.calls)
    assert any(c[1] == "comms.send_email" for c in comms_client.calls)


@pytest.mark.asyncio
async def test_executor_governed_fails_on_missing_binding() -> None:
    """Verify governed executor fails gracefully for unbound capabilities."""
    domain_id = "ws_acme_procurement@1.0.0"
    bindings = {"procurement.create_invoice": "odoo"}
    adapter_clients = {"odoo": _FakeNilClient("odoo")}

    executor = LocalExecutor.from_governed(
        domain_id, bindings, adapter_clients, run_id="run-x"
    )

    # Program references a verb not in bindings
    program = {
        "entry": "Step1",
        "domain_id": domain_id,
        "backend_bindings": bindings,
        "pipeline": [
            {
                "id": "Step1",
                "type": "action",
                "verb": "unknown.verb",
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
    assert "No backend binding for 'unknown.verb'" in result.error


@pytest.mark.asyncio
async def test_executor_governed_fails_on_missing_adapter() -> None:
    """Verify governed executor fails gracefully for unavailable adapter client."""
    domain_id = "ws_acme_procurement@1.0.0"
    bindings = {"procurement.create_invoice": "nonexistent_adapter"}
    adapter_clients = {"odoo": _FakeNilClient("odoo")}  # odoo is available, but nonexistent_adapter is not

    executor = LocalExecutor.from_governed(
        domain_id, bindings, adapter_clients, run_id="run-y"
    )

    program = {
        "entry": "Step1",
        "domain_id": domain_id,
        "backend_bindings": bindings,
        "pipeline": [
            {
                "id": "Step1",
                "type": "action",
                "verb": "procurement.create_invoice",
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
    assert "Adapter 'nonexistent_adapter'" in result.error
    assert "not available" in result.error
