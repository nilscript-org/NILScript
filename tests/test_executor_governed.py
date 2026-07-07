"""LocalExecutor with GovernedRoutingNilClient — integration tests for D8 governance.

Tests the LocalExecutor.from_governed class method and the integration between the executor
and GovernedRoutingNilClient. Verifies that cycles can run with explicit Domain bindings.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from nilscript.kernel.executor import LocalExecutor
from nilscript.kernel.models import WosoolProgram
from nilscript.sdk.sentences import ProposalState, StatusBody

_TS = datetime(2026, 7, 4, tzinfo=UTC)


class _FakeNilClient:
    """A stand-in NilClient for testing."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, Any]] = []

    async def propose(self, verb, args, *, session_id, request_timestamp, trace=None):
        self.calls.append(("propose", verb))
        return SimpleNamespace(id=f"pid-{self.name}", verb=verb, is_refusal=False)

    async def propose_batch(self, proposes, *, session_id, request_timestamp, trace=None):
        out = []
        for p in proposes:
            out.append(SimpleNamespace(id=f"pid-{self.name}", verb=p.verb))
        return tuple(out)

    async def commit(self, proposal_id, *, idempotency_key, ts=None, trace=None):
        self.calls.append(("commit", proposal_id))
        return StatusBody(proposal=proposal_id, state=ProposalState.EXECUTED)

    async def query(self, verb, args=None, *, ts=None, trace=None):
        return {"result": f"queried {verb}"}

    async def status(self, proposal_id):
        return StatusBody(proposal=proposal_id, state=ProposalState.EXECUTED)

    async def rollback(self, compensation_token, reason, *, idempotency_key=None, ts=None, trace=None):
        return SimpleNamespace(id="comp-id")


def _simple_program() -> dict[str, Any]:
    """A minimal DSL program with one action."""
    return {
        "wosool": "0.1",
        "workspace": "test_workspace",
        "locale": "ar",
        "entry": "step_1",
        "pipeline": [
            {
                "id": "step_1",
                "type": "action",
                "skill": "procurement",
                "verb": "procurement.create_invoice",
                "args": {"po_id": "PO-123"},
                "next": None,
            }
        ],
        "on_error": "halt",
    }


@pytest.mark.asyncio
async def test_executor_from_governed_initializes_with_governed_router() -> None:
    """Verify LocalExecutor.from_governed creates an executor with GovernedRoutingNilClient."""
    odoo = _FakeNilClient("odoo")
    bindings = {"procurement.create_invoice": "odoo"}
    adapter_clients = {"odoo": odoo}

    executor = LocalExecutor.from_governed(
        domain_id="ws_acme@1.0.0",
        backend_bindings=bindings,
        adapter_clients=adapter_clients,
        session_id="test-session",
        run_id="test-run",
    )

    # Verify the executor was initialized
    assert executor is not None
    assert executor._session_id == "test-session"
    assert executor._run_id == "test-run"
    # The client should be a GovernedRoutingNilClient
    from nilscript.sdk.routing import GovernedRoutingNilClient

    assert isinstance(executor._client, GovernedRoutingNilClient)


@pytest.mark.asyncio
async def test_executor_governed_runs_program_with_explicit_bindings() -> None:
    """Verify a program executes correctly using explicit Domain bindings."""
    odoo = _FakeNilClient("odoo")
    bindings = {"procurement.create_invoice": "odoo"}
    adapter_clients = {"odoo": odoo}

    executor = LocalExecutor.from_governed(
        domain_id="ws_acme@1.0.0",
        backend_bindings=bindings,
        adapter_clients=adapter_clients,
    )

    program = _simple_program()
    result = await executor.execute(program, input={"test": "data"})

    # Verify the execution completed
    assert result.completed
    assert len(result.context) > 0
    assert ("propose", "procurement.create_invoice") in odoo.calls


@pytest.mark.asyncio
async def test_executor_governed_fails_with_unbound_capability() -> None:
    """Verify execution fails with clear error when capability is not bound."""
    odoo = _FakeNilClient("odoo")
    # Intentionally exclude the capability
    bindings = {"other.capability": "odoo"}
    adapter_clients = {"odoo": odoo}

    executor = LocalExecutor.from_governed(
        domain_id="ws_acme@1.0.0",
        backend_bindings=bindings,
        adapter_clients=adapter_clients,
    )

    program = _simple_program()
    result = await executor.execute(program, input={"test": "data"})

    # Execution should fail with a refusal or error
    assert not result.completed
    assert result.error is not None or result.refusal is not None
