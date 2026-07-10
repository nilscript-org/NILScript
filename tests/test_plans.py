"""Governed dependent plans (ordered, linked approval cards) — store + control-plane executor.

Proves the lifecycle: nil_plan holds the prerequisite (even at MEDIUM) + a BLOCKED dependent;
approving a blocked dependent is refused; approving the prerequisite MATERIALIZES + unblocks the
dependent with the handoff id resolved; rejecting the prerequisite CANCELS the whole plan.

Universal by construction — everything here is kernel/CP, adapter-agnostic. The adapter is faked at
the NilClient seam (the same seam `_execute_approved` and `_materialize_dependents` build against the
active adapter), so the ordered executor is exercised end-to-end without a real backend.
"""

import pytest

pytest.importorskip("fastapi", reason="needs fastapi")

from types import SimpleNamespace  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import nilscript.controlplane.app as cp_app  # noqa: E402
from nilscript.controlplane.app import create_app  # noqa: E402
from nilscript.controlplane.store import EventStore  # noqa: E402


def _store():
    return EventStore(":memory:")


# ── store layer ──────────────────────────────────────────────────────────────────────────────────

def test_await_approval_carries_plan_link_and_pending_computes_blocked():
    s = _store()
    # Prerequisite (root) — a plan card, seq 0, no dependency → never blocked, even at MEDIUM.
    s.await_approval("root1", verb="res.partner.create", tier="MEDIUM", workspace="ws1",
                     plan_id="planA", seq=0, depends_on=None)
    # A dependent planned step (not yet proposed) → a blocked card with a synthetic id.
    s.register_planned_step("planned:planA:1", plan_id="planA", seq=1, depends_on="root1",
                            verb="account.invoice.create",
                            args={"client_id": "$.step0.id", "amount": 100},
                            handoff={"client_id": "$.step0.id"}, tier=None, workspace="ws1")
    pend = {p["proposal_id"]: p for p in s.pending("ws1")}
    assert pend["root1"]["plan_id"] == "planA" and pend["root1"]["seq"] == 0
    assert pend["root1"]["blocked"] is False              # prerequisite is never blocked
    assert pend["planned:planA:1"]["blocked"] is True     # dependent blocked until prereq commits
    assert pend["planned:planA:1"]["planned"] is True
    assert pend["planned:planA:1"]["depends_on"] == "root1"


def test_dependent_hold_is_blocked_until_prerequisite_committed():
    s = _store()
    s.await_approval("root1", verb="res.partner.create", tier="MEDIUM", plan_id="planA", seq=0)
    s.await_approval("dep1", verb="account.invoice.create", tier="HIGH",
                     plan_id="planA", seq=1, depends_on="root1")
    assert {p["proposal_id"]: p["blocked"] for p in s.pending()}["dep1"] is True
    # Approve + record the prerequisite as committed → the dependent unblocks.
    s.decide("root1", "approved")
    s.record_committed("root1", "42")
    assert {p["proposal_id"]: p["blocked"] for p in s.pending()}["dep1"] is False


def test_cancel_plan_rejects_holds_and_cancels_planned():
    s = _store()
    s.await_approval("root1", verb="res.partner.create", tier="MEDIUM", plan_id="planA", seq=0)
    s.register_planned_step("planned:planA:1", plan_id="planA", seq=1, depends_on="root1",
                            verb="account.invoice.create", args={}, handoff={})
    n = s.cancel_plan("planA")
    assert n == 2
    assert s.decision("root1") == "rejected"
    assert s.pending() == []  # nothing left blocked or held — no orphan


def test_next_planned_steps_and_promote():
    s = _store()
    s.await_approval("root1", verb="res.partner.create", tier="MEDIUM", plan_id="planA", seq=0)
    s.register_planned_step("planned:planA:1", plan_id="planA", seq=1, depends_on="root1",
                            verb="account.invoice.create",
                            args={"client_id": "$.step0.id"}, handoff={"client_id": "$.step0.id"})
    nxt = s.next_planned_steps("planA", "root1")
    assert len(nxt) == 1 and nxt[0]["handoff"] == {"client_id": "$.step0.id"}
    s.promote_planned_step("planned:planA:1", real_proposal_id="real1",
                           verb="account.invoice.create", tier="HIGH", preview={"en": "invoice"},
                           workspace="ws1", plan_id="planA", seq=1, depends_on="root1")
    # The synthetic planned step is gone from pending; the real held card appears.
    ids = {p["proposal_id"] for p in s.pending()}
    assert "planned:planA:1" not in ids and "real1" in ids
    assert s.next_planned_steps("planA", "root1") == []  # consumed (materialized)


# ── control-plane ordered executor (adapter faked at the NilClient seam) ───────────────────────────

class _FakeProposal(SimpleNamespace):
    is_refusal = False
    def model_dump(self, **_):  # for commit outcomes
        return self._dump


def _proposal(pid, verb, tier="HIGH", *, committed_id=None):
    p = _FakeProposal(id=pid, verb=verb, tier=SimpleNamespace(value=tier),
                      preview={"en": verb}, resolved={}, modifiable=())
    p._dump = {"result": {"entity": {"id": committed_id}}} if committed_id else {"outcome": "ok"}
    return p


class _FakeClient:
    """A fake NilClient: propose() mints a proposal; commit() returns a StatusBody-shaped dump with the
    committed entity id, and records the args it was proposed with so tests can assert handoff resolution."""

    proposed_args: dict[str, dict] = {}
    commit_ids: dict[str, str] = {}   # verb → committed backend id to return

    def __init__(self, *a, **k):
        pass

    async def propose(self, verb, args, *, session_id=None, request_timestamp=None):
        pid = f"re:{verb}:{len(_FakeClient.proposed_args)}"
        _FakeClient.proposed_args[pid] = dict(args)
        return _proposal(pid, verb)

    async def commit(self, proposal_id, *, idempotency_key=None):
        # The committed id per proposal_id; a plan prerequisite maps to its configured backend id.
        cid = _FakeClient.commit_ids.get(proposal_id, "100")
        return _FakeStatus(cid)


class _FakeStatus:
    def __init__(self, cid):
        self._cid = cid
    def model_dump(self, **_):
        return {"result": {"entity": {"id": self._cid}}}


@pytest.fixture()
def cp(monkeypatch):
    _FakeClient.proposed_args = {}
    _FakeClient.commit_ids = {}
    monkeypatch.setattr(cp_app, "NilClient", _FakeClient)
    monkeypatch.setattr(cp_app, "NilTransport",
                        lambda *a, **k: SimpleNamespace(aclose=_aclose))
    s = _store()
    s.register_adapter("ws1", "odoo", url="https://odoo/nil", bearer="tok", system="odoo")
    s.activate_adapter("ws1", "odoo")
    # A proposed event so proposal_workspace() resolves the prerequisite to ws1.
    s.ingest({"nil": "0.1", "id": "e0", "performative": "EVENT", "workspace": "ws1",
              "body": {"event": "proposed", "proposal": "root1", "verb": "res.partner.create",
                       "tier": "MEDIUM"}}, 1)
    return s, TestClient(create_app(s, secret=""))


async def _aclose():
    return None


def test_approving_blocked_dependent_is_refused(cp):
    s, client = cp
    s.await_approval("root1", verb="res.partner.create", tier="MEDIUM", workspace="ws1",
                     plan_id="planA", seq=0)
    s.await_approval("dep1", verb="account.invoice.create", tier="HIGH", workspace="ws1",
                     plan_id="planA", seq=1, depends_on="root1")
    r = client.post("/proposals/dep1/decision", json={"status": "approved"})
    assert r.status_code == 409
    assert "BLOCKED" in r.json()["error"] and r.json()["depends_on"] == "root1"
    assert s.decision("dep1") == "pending"  # still awaiting — never silently approved


def test_approving_prerequisite_materializes_and_resolves_handoff(cp):
    s, client = cp
    s.await_approval("root1", verb="res.partner.create", tier="MEDIUM", workspace="ws1",
                     plan_id="planA", seq=0)
    s.register_planned_step("planned:planA:1", plan_id="planA", seq=1, depends_on="root1",
                            verb="account.invoice.create",
                            args={"target": "account.invoice", "client_id": "$.step0.id", "amount": 100},
                            handoff={"client_id": "$.step0.id"}, workspace="ws1")
    _FakeClient.commit_ids["root1"] = "777"  # the prerequisite commits to backend id 777
    r = client.post("/proposals/root1/decision", json={"status": "approved"}).json()
    assert r["execution"]["executed"] is True
    assert r["execution"]["committed_id"] == "777"
    mat = r["materialized"]
    assert len(mat) == 1 and mat[0]["seq"] == 1 and "proposal_id" in mat[0]
    # The dependent was proposed with the handoff resolved to the prerequisite's committed id.
    args = _FakeClient.proposed_args[mat[0]["proposal_id"]]
    assert args["client_id"] == "777"      # $.step0.id → 777
    assert args["amount"] == 100           # untouched
    # The dependent is now a REAL held card, no longer blocked.
    pend = {p["proposal_id"]: p for p in s.pending("ws1")}
    assert mat[0]["proposal_id"] in pend and pend[mat[0]["proposal_id"]]["blocked"] is False
    assert "planned:planA:1" not in pend   # the synthetic blocked card is gone


def test_rejecting_prerequisite_cancels_the_plan(cp):
    s, client = cp
    s.await_approval("root1", verb="res.partner.create", tier="MEDIUM", workspace="ws1",
                     plan_id="planA", seq=0)
    s.register_planned_step("planned:planA:1", plan_id="planA", seq=1, depends_on="root1",
                            verb="account.invoice.create", args={"client_id": "$.step0.id"},
                            handoff={"client_id": "$.step0.id"}, workspace="ws1")
    r = client.post("/proposals/root1/decision", json={"status": "rejected"}).json()
    assert r["plan_cancelled"]["plan_id"] == "planA"
    assert s.decision("root1") == "rejected"
    assert s.pending("ws1") == []          # the dependent is gone — no orphan


def test_planned_step_endpoint_registers_blocked_card(cp):
    s, client = cp
    s.await_approval("root1", verb="res.partner.create", tier="MEDIUM", workspace="ws1",
                     plan_id="planA", seq=0)
    r = client.post("/plans/planA/steps", json={
        "proposal_id": "planned:planA:1", "seq": 1, "depends_on": "root1",
        "verb": "account.invoice.create", "args": {"client_id": "$.step0.id"},
        "handoff": {"client_id": "$.step0.id"}, "workspace": "ws1"})
    assert r.status_code == 200 and r.json()["status"] == "planned"
    pend = {p["proposal_id"]: p for p in client.get("/api/pending?workspace=ws1").json()["pending"]}
    assert pend["planned:planA:1"]["blocked"] is True and pend["planned:planA:1"]["seq"] == 1
