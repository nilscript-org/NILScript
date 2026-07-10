"""GovernedRoutingNilClient — routes via explicit Domain backend bindings (D8).

The governed router replaces implicit verb discovery with explicit, upfront bindings. Every
capability is bound to a specific backend adapter at compile time; the binding follows through
propose→commit→status/rollback. This tests: explicit routing by capability, proposal tracking,
error handling for missing bindings, and cross-adapter proposal safety.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from nilscript.sdk.routing import GovernedRoutingNilClient

_TS = datetime(2026, 7, 4, tzinfo=UTC)


class _FakeClient:
    """A stand-in NilClient that tags every answer with its adapter name and logs calls."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, str]] = []

    async def propose(self, verb, args, *, session_id, request_timestamp, trace=None):
        self.calls.append(("propose", verb))
        return SimpleNamespace(id=f"{self.name}:{verb}:pid", verb=verb, is_refusal=False)

    async def propose_batch(self, proposes, *, session_id, request_timestamp, trace=None):
        out = []
        for p in proposes:
            self.calls.append(("propose_batch", p.verb))
            out.append(SimpleNamespace(id=f"{self.name}:{p.verb}:pid", verb=p.verb))
        return tuple(out)

    async def commit(self, proposal_id, *, idempotency_key, ts=None, trace=None):
        self.calls.append(("commit", proposal_id))
        return SimpleNamespace(state="executed", proposal=proposal_id, adapter=self.name)

    async def query(self, verb, args=None, *, ts=None, trace=None):
        self.calls.append(("query", verb))
        return {"adapter": self.name, "verb": verb}

    async def status(self, proposal_id):
        self.calls.append(("status", proposal_id))
        return SimpleNamespace(state="pending", adapter=self.name)

    async def rollback(self, compensation_token, reason, *, idempotency_key=None, ts=None, trace=None):
        self.calls.append(("rollback", compensation_token))
        return SimpleNamespace(id=f"comp:{compensation_token}", verb="rollback")


def _governed_router() -> tuple[GovernedRoutingNilClient, _FakeClient, _FakeClient]:
    """Create a governed router with explicit bindings: odoo and comms adapters."""
    odoo = _FakeClient("odoo")
    comms = _FakeClient("comms")
    bindings = {
        "procurement.create_purchase_invoice": "odoo",
        "procurement.list_vendors": "odoo",
        "comms.send_email": "comms",
        "comms.send_sms": "comms",
    }
    adapter_clients = {"odoo": odoo, "comms": comms}
    router = GovernedRoutingNilClient("ws_acme_procurement@1.0.0", bindings, adapter_clients)
    return router, odoo, comms


@pytest.mark.asyncio
async def test_governed_propose_routes_to_bound_adapter() -> None:
    """Verify propose routes to the adapter bound in the Domain."""
    router, odoo, comms = _governed_router()
    p1 = await router.propose("procurement.create_purchase_invoice", {}, session_id="s", request_timestamp=_TS)
    p2 = await router.propose("comms.send_email", {"to": "x"}, session_id="s", request_timestamp=_TS)
    assert p1.id.startswith("odoo:")  # bound to odoo
    assert p2.id.startswith("comms:")  # bound to comms
    assert ("propose", "procurement.create_purchase_invoice") in odoo.calls
    assert ("propose", "comms.send_email") in comms.calls


@pytest.mark.asyncio
async def test_governed_propose_fails_on_missing_binding() -> None:
    """Verify missing capability binding raises clear error."""
    router, _, _ = _governed_router()
    with pytest.raises(RuntimeError, match="No backend binding for 'unknown.verb'"):
        await router.propose("unknown.verb", {}, session_id="s", request_timestamp=_TS)


@pytest.mark.asyncio
async def test_governed_propose_batch_routes_each_to_its_adapter() -> None:
    """Verify propose_batch routes each intent to its bound adapter, preserving order."""
    from nilscript.sdk.sentences import ProposeBody

    router, odoo, comms = _governed_router()
    proposes = (
        ProposeBody(verb="procurement.create_purchase_invoice", args={}),
        ProposeBody(verb="comms.send_email", args={"to": "x"}),
        ProposeBody(verb="procurement.list_vendors", args={}),
    )
    results = await router.propose_batch(proposes, session_id="s", request_timestamp=_TS)
    assert len(results) == 3
    assert results[0].id.startswith("odoo:")
    assert results[1].id.startswith("comms:")
    assert results[2].id.startswith("odoo:")


@pytest.mark.asyncio
async def test_governed_commit_follows_the_adapter_that_held_the_proposal() -> None:
    """Verify commit lands on the adapter that held the proposal."""
    router, odoo, comms = _governed_router()
    p = await router.propose("comms.send_email", {"to": "x"}, session_id="s", request_timestamp=_TS)
    outcome = await router.commit(p.id, idempotency_key="k1")
    assert outcome.adapter == "comms"
    assert ("commit", p.id) in comms.calls
    assert all(c[0] != "commit" for c in odoo.calls)


@pytest.mark.asyncio
async def test_governed_commit_fails_on_unknown_proposal() -> None:
    """Verify commit on unknown proposal raises clear error (governance safety)."""
    router, _, _ = _governed_router()
    with pytest.raises(RuntimeError, match="Proposal 'unknown:pid' is unknown"):
        await router.commit("unknown:pid", idempotency_key="k")


@pytest.mark.asyncio
async def test_governed_status_follows_the_proposal_origin() -> None:
    """Verify status checks on the adapter that held the proposal."""
    router, _, comms = _governed_router()
    p = await router.propose("comms.send_email", {}, session_id="s", request_timestamp=_TS)
    st = await router.status(p.id)
    assert st.adapter == "comms"


@pytest.mark.asyncio
async def test_governed_status_fails_on_unknown_proposal() -> None:
    """Verify status on unknown proposal raises clear error (governance safety)."""
    router, _, _ = _governed_router()
    with pytest.raises(RuntimeError, match="Proposal 'unknown:pid' is unknown"):
        await router.status("unknown:pid")


@pytest.mark.asyncio
async def test_governed_query_routes_to_bound_adapter() -> None:
    """Verify query routes to the adapter bound for the verb."""
    router, odoo, comms = _governed_router()
    r1 = await router.query("procurement.list_vendors")
    r2 = await router.query("comms.send_email")
    assert r1["adapter"] == "odoo"
    assert r2["adapter"] == "comms"


@pytest.mark.asyncio
async def test_governed_query_fails_on_missing_binding() -> None:
    """Verify query for unbound verb raises clear error."""
    router, _, _ = _governed_router()
    with pytest.raises(RuntimeError, match="No backend binding for 'unknown.query'"):
        await router.query("unknown.query")


@pytest.mark.asyncio
async def test_governed_rollback_follows_the_token_origin() -> None:
    """Verify rollback reverses on the adapter that issued the token."""
    from nilscript.sdk.sentences import RollbackReason

    router, _, comms = _governed_router()
    # Propose and commit to bind the token
    p = await router.propose("comms.send_email", {}, session_id="s", request_timestamp=_TS)
    outcome = await router.commit(p.id, idempotency_key="k1")
    # Simulate a compensation token
    token = "comp:email123"
    router._by_token[token] = comms  # Manual bind for this test
    result = await router.rollback(token, RollbackReason.SAGA_UNWIND, idempotency_key="k2")
    assert ("rollback", token) in comms.calls


@pytest.mark.asyncio
async def test_governed_rollback_fails_on_unknown_token() -> None:
    """Verify rollback on unknown token raises clear error (governance safety)."""
    from nilscript.sdk.sentences import RollbackReason

    router, _, _ = _governed_router()
    with pytest.raises(RuntimeError, match="Compensation token 'unknown:token' is unknown"):
        await router.rollback("unknown:token", RollbackReason.SAGA_UNWIND)


@pytest.mark.asyncio
async def test_governed_adapter_not_available_raises_error() -> None:
    """Verify requesting a capability bound to a missing adapter raises clear error."""
    odoo = _FakeClient("odoo")
    bindings = {"procurement.create_purchase_invoice": "nonexistent_adapter"}
    adapter_clients = {"odoo": odoo}
    router = GovernedRoutingNilClient("ws_acme@1.0.0", bindings, adapter_clients)

    with pytest.raises(RuntimeError, match="Adapter 'nonexistent_adapter'.*not available"):
        await router.propose("procurement.create_purchase_invoice", {}, session_id="s", request_timestamp=_TS)


@pytest.mark.asyncio
async def test_governed_multiple_backends_in_batch() -> None:
    """Verify a batch can cross multiple backends with each proposal tracked correctly."""
    from nilscript.sdk.sentences import ProposeBody

    router, odoo, comms = _governed_router()
    proposes = (
        ProposeBody(verb="procurement.create_purchase_invoice", args={"po": "123"}),
        ProposeBody(verb="comms.send_email", args={"to": "buyer"}),
    )
    results = await router.propose_batch(proposes, session_id="s", request_timestamp=_TS)

    # Each proposal is tracked to its origin adapter
    assert results[0].id.startswith("odoo:")
    assert results[1].id.startswith("comms:")

    # Commits follow the bound adapter
    o1 = await router.commit(results[0].id, idempotency_key="k1")
    o2 = await router.commit(results[1].id, idempotency_key="k2")
    assert o1.adapter == "odoo"
    assert o2.adapter == "comms"
