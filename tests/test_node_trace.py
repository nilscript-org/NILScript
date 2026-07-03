"""Full-run observability: the per-node trace + gates that actually PAUSE.

Two guarantees this file locks in:

  1. The no-pause bug is dead. A human gate whose polled proposal is unknown (a standalone
     `gate_step_N` handle the System never saw, which an adapter answers `expired`) must PARK —
     surfacing a pending approval — not silently self-resolve as a timeout and complete in 0s.

  2. Every run carries a structured, ordered per-node trace (`RunResult.trace_nodes` →
     persisted `trace["nodes"]`): each node's status/timing/output_summary/proposal, accumulated
     ACROSS park→resume segments, restart-safe (row-backed in the run trace blob).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from nilscript.automation.dispatch import (
    _merge_trace_nodes,
    fire_manual,
    resume_on_decision,
)
from nilscript.automation.scheduler import resume_due_waits
from nilscript.controlplane.store import EventStore
from nilscript.kernel.executor import LocalExecutor

# ── a fake NIL client: a query returns rows, a gate's status is "expired" (unknown proposal) ─────


class _FakeClient:
    """The gate handle `gate_step_2` was never proposed, so a real adapter reports `expired` — the
    exact shape that used to route a human gate straight to 'timeout' and complete the run."""

    def __init__(self, status_state: str = "expired") -> None:
        self._status_state = status_state
        self.status_calls = 0

    async def query(self, verb, args=None):
        return {"rows": [{"id": 1, "name": "Ada"}], "verb": verb}

    async def status(self, proposal_id):
        self.status_calls += 1
        return SimpleNamespace(state=self._status_state, proposal=proposal_id)


QUERY_GATE_NOTIFY = {
    "wosool": "0.1",
    "workspace": "acme",
    "entry": "step_1",
    "pipeline": [
        {"id": "step_1", "type": "query", "verb": "crm.list", "args": {}, "next": "step_2"},
        {"id": "step_2", "type": "await_approval", "proposal": "gate_step_2",
         "timeout_seconds": 3600, "on_approved": "step_3", "on_rejected": "step_4"},
        {"id": "step_3", "type": "notify", "message": {"ar": "تم", "en": "done"}},
        {"id": "step_4", "type": "notify", "message": {"ar": "رُفض", "en": "rejected"}},
    ],
}

WAIT_EVENT_PLAN = {
    "wosool": "0.1",
    "workspace": "acme",
    "entry": "step_1",
    "pipeline": [
        {"id": "step_1", "type": "query", "verb": "crm.list", "args": {}, "next": "step_2"},
        {"id": "step_2", "type": "wait_for_event", "on_event": "invoice.paid",
         "match": {"id": 7}, "timeout_seconds": 1800, "on_timeout": "step_3"},
        {"id": "step_3", "type": "notify", "message": {"ar": "انتهى", "en": "timed out"}},
    ],
}


def _executor(client, run_id="r1"):
    # poll ONCE with no sleep: an unknown proposal parks immediately instead of a 10s poll budget.
    return LocalExecutor(client, run_id=run_id, approval_max_polls=1, approval_poll_interval=0)


# ── the no-pause fix: a gate with no decision PARKS, it does not complete ─────────────────────────


async def test_unknown_gate_proposal_parks_instead_of_completing():
    result = await _executor(_FakeClient("expired")).execute(QUERY_GATE_NOTIFY)
    assert result.completed is False  # the run did NOT run straight to completed
    assert result.waiting == {
        "kind": "approval", "node": "step_2",
        "proposal": "gate_step_2", "timeout_seconds": 3600,
    }


@pytest.mark.parametrize("state", ["expired", "pending", "suspended", "failed_terminal"])
async def test_non_decision_states_all_park(state):
    result = await _executor(_FakeClient(state)).execute(QUERY_GATE_NOTIFY)
    assert result.completed is False and result.waiting is not None


async def test_genuine_approval_still_routes_without_parking():
    result = await _executor(_FakeClient("approved")).execute(QUERY_GATE_NOTIFY)
    assert result.completed is True  # a real decision short-circuits — the on_approved branch ran
    assert result.notifications == [{"ar": "تم", "en": "done"}]


# ── the per-node trace at PARK: earlier nodes completed, the gate is waiting_approval ────────────


async def test_park_trace_shows_completed_and_waiting_nodes():
    result = await _executor(_FakeClient("expired")).execute(QUERY_GATE_NOTIFY)
    nodes = {n["node_id"]: n for n in result.trace_nodes}

    q = nodes["step_1"]
    assert q["status"] == "completed" and q["type"] == "query" and q["verb"] == "crm.list"
    assert q["started_at"] and q["ended_at"]  # both stamped from the runtime clock
    assert q["output_summary"] == {"rows": {"count": 1}, "verb": "crm.list"}

    gate = nodes["step_2"]
    assert gate["status"] == "waiting_approval"
    assert gate["proposal_id"] == "gate_step_2"
    assert gate["ended_at"] is None  # a waiting node has not finished
    assert "step_3" not in nodes and "step_4" not in nodes  # nothing downstream ran


async def test_wait_for_event_parks_with_event_wait_on_the_node():
    result = await _executor(_FakeClient()).execute(WAIT_EVENT_PLAN)
    assert result.waiting is not None and result.waiting["kind"] == "event"
    gate = {n["node_id"]: n for n in result.trace_nodes}["step_2"]
    assert gate["status"] == "waiting_event"
    assert gate["event_wait"] == {
        "on_event": "invoice.paid", "match": {"id": 7}, "timeout_seconds": 1800,
    }


# ── merge across segments: the gate advances waiting → completed, seq is re-ordered ──────────────


def test_merge_replaces_waiting_node_and_reorders_seq():
    seg1 = [
        {"node_id": "step_1", "seq": 0, "status": "completed"},
        {"node_id": "step_2", "seq": 1, "status": "waiting_approval"},
    ]
    seg2 = [
        {"node_id": "step_2", "seq": 0, "status": "completed"},  # the decision landed
        {"node_id": "step_3", "seq": 1, "status": "completed"},
    ]
    merged = _merge_trace_nodes(seg1, seg2)
    assert [n["node_id"] for n in merged] == ["step_1", "step_2", "step_3"]
    assert [n["seq"] for n in merged] == [0, 1, 2]
    assert merged[1]["status"] == "completed"  # step_2 advanced, not duplicated


# ── end-to-end through the dispatcher: fire → park → decide → the trace shows every node done ────


def _runner(client):
    async def run(plan, *, run_id, resume=None, input=None):
        return await _executor(client, run_id=run_id).execute(plan, resume=resume)

    return run


def _armed_store(tmp_path, plan, name="nt.db"):
    store = EventStore(path=str(tmp_path / name))
    store.register_automation(
        workspace="acme", automation_id="cyc", content_hash="h1",
        name={"ar": "دورة", "en": "Cycle"}, plan=plan, trigger={"type": "manual"},
        state="active",
    )
    return store


async def test_fire_parks_then_decision_completes_full_trace(tmp_path):
    client = _FakeClient("expired")
    store = _armed_store(tmp_path, QUERY_GATE_NOTIFY)

    fired = await fire_manual(
        store, workspace="acme", automation_id="cyc",
        idempotency_key="k1", runner=_runner(client),
    )
    run = fired["run"]
    assert run["state"] == "waiting_approval"  # PARKED, not completed
    parked_nodes = {n["node_id"]: n for n in run["trace"]["nodes"]}
    assert parked_nodes["step_1"]["status"] == "completed"
    assert parked_nodes["step_2"]["status"] == "waiting_approval"
    assert run["trace"]["current_node"] == "step_2"

    # the pending approval is reachable via the park row (the Decisions feed's source)
    park = store.parked_for_proposal("gate_step_2")[0]
    assert park["node_id"] == "step_2"

    out = await resume_on_decision(store, park, runner=_runner(client), status="approved")
    assert out["state"] == "completed"

    final = store.get_run(run["run_id"])
    assert final["state"] == "completed"
    nodes = final["trace"]["nodes"]
    by_id = {n["node_id"]: n for n in nodes}
    assert by_id["step_1"]["status"] == "completed"
    assert by_id["step_2"]["status"] == "completed"  # the gate advanced on the decision
    assert by_id["step_3"]["status"] == "completed"  # the on_approved branch ran
    assert [n["seq"] for n in nodes] == list(range(len(nodes)))  # ordered, contiguous


async def test_node_trace_survives_a_process_restart(tmp_path):
    client = _FakeClient("expired")
    store = _armed_store(tmp_path, QUERY_GATE_NOTIFY, name="restart.db")
    fired = await fire_manual(
        store, workspace="acme", automation_id="cyc",
        idempotency_key="k1", runner=_runner(client),
    )
    run_id = fired["run"]["run_id"]

    # a fresh EventStore over the SAME db file = a process restart; the node trace is row-backed
    reopened = EventStore(path=str(tmp_path / "restart.db"))
    persisted = reopened.get_run(run_id)
    nodes = {n["node_id"]: n for n in persisted["trace"]["nodes"]}
    assert nodes["step_1"]["status"] == "completed"
    assert nodes["step_2"]["status"] == "waiting_approval"
    assert nodes["step_2"]["proposal_id"] == "gate_step_2"


async def test_wait_for_event_deadline_routes_and_trace_completes(tmp_path):
    client = _FakeClient()
    store = _armed_store(tmp_path, WAIT_EVENT_PLAN, name="wait.db")
    await fire_manual(
        store, workspace="acme", automation_id="cyc",
        idempotency_key="k1", runner=_runner(client),
    )
    # push the deadline into the past, then let the clock resume the parked wait via on_timeout
    resumed = await resume_due_waits(
        store, runner=_runner(client), now=datetime.now(UTC) + timedelta(hours=2)
    )
    assert len(resumed) == 1 and resumed[0]["state"] == "completed"
    final = store.get_run("cyc:v1:k1")
    by_id = {n["node_id"]: n for n in final["trace"]["nodes"]}
    assert by_id["step_2"]["status"] == "completed"  # the wait advanced on the deadline
    assert by_id["step_3"]["status"] == "completed"  # the on_timeout branch ran
