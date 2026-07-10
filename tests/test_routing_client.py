"""RoutingNilClient — each verb reaches its declaring adapter; a proposal follows its origin.

The router is the primitive that lets one governed run span several backends (crm reads from Odoo,
comms.send_email sends via the comms adapter). These tests use fake per-adapter clients that record
which backend each call landed on, proving: propose routes by verb; commit/status follow the adapter
that HELD the proposal (never a sibling); query routes by verb; an unknown verb falls to default.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from nilscript.sdk.routing import RoutingNilClient

_TS = datetime(2026, 7, 4, tzinfo=UTC)


class _FakeClient:
    """A stand-in NilClient that tags every answer with its adapter name and logs the calls."""

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


def _router() -> tuple[RoutingNilClient, _FakeClient, _FakeClient]:
    odoo = _FakeClient("odoo")
    comms = _FakeClient("comms")
    router = RoutingNilClient(default=odoo, routes={"comms.send_email": comms})
    return router, odoo, comms


@pytest.mark.asyncio
async def test_propose_routes_by_verb() -> None:
    router, odoo, comms = _router()
    p1 = await router.propose("crm.list", {}, session_id="s", request_timestamp=_TS)
    p2 = await router.propose("comms.send_email", {"to": "x"}, session_id="s", request_timestamp=_TS)
    assert p1.id.startswith("odoo:")  # default adapter served the crm verb
    assert p2.id.startswith("comms:")  # routed to the comms adapter
    assert ("propose", "crm.list") in odoo.calls
    assert ("propose", "comms.send_email") in comms.calls


@pytest.mark.asyncio
async def test_commit_follows_the_adapter_that_held_the_proposal() -> None:
    router, odoo, comms = _router()
    p = await router.propose("comms.send_email", {"to": "x"}, session_id="s", request_timestamp=_TS)
    outcome = await router.commit(p.id, idempotency_key="k1")
    # The commit MUST land on comms (which held the proposal), never on the default odoo client.
    assert outcome.adapter == "comms"
    assert ("commit", p.id) in comms.calls
    assert all(c[0] != "commit" for c in odoo.calls)


@pytest.mark.asyncio
async def test_status_follows_the_proposal_origin() -> None:
    router, _odoo, comms = _router()
    p = await router.propose("comms.send_email", {}, session_id="s", request_timestamp=_TS)
    st = await router.status(p.id)
    assert st.adapter == "comms"


@pytest.mark.asyncio
async def test_query_routes_by_verb_and_unknown_falls_to_default() -> None:
    router, _odoo, comms = _router()
    assert (await router.query("comms.send_email"))["adapter"] == "comms"
    assert (await router.query("crm.find_contact"))["adapter"] == "odoo"  # unrouted → default


@pytest.mark.asyncio
async def test_commit_of_unknown_proposal_falls_to_default() -> None:
    router, odoo, _comms = _router()
    # A proposal the router never saw (e.g. resumed cross-process) commits on default, not a crash.
    outcome = await router.commit("stranger:pid", idempotency_key="k")
    assert outcome.adapter == "odoo"
