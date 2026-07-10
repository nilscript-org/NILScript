"""Gates resume runs end-to-end (P0): a run that parks on a gate is resumed DETERMINISTICALLY by
the owner's decision — row-backed, never an in-memory await.

Three layers, all against the real seams:
  - executor: a HIGH-tier commit the System parks stops the walk with `RunResult.waiting`, and
    `execute(resume=...)` continues at the node's continuation with the commit result bound;
  - control plane: POST /proposals/{id}/decision — the SAME call that executes the approved
    proposal — resumes every run parked on it (approve → completed with the committed result in
    the run record; reject → the run closes as rejected with the reason);
  - restarts: the park is a `parked_runs` row keyed to the PINNED automation version, so a fresh
    app/store process resumes exactly the same way.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi", reason="needs fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import nilscript.controlplane.app as cp_app  # noqa: E402
from nilscript.automation.dispatch import resume_on_decision  # noqa: E402
from nilscript.automation.scheduler import resume_due_waits  # noqa: E402
from nilscript.controlplane.app import create_app  # noqa: E402
from nilscript.controlplane.store import EventStore  # noqa: E402
from nilscript.kernel.executor import LocalExecutor  # noqa: E402

# One HIGH write, then a notify — the continuation the resume must reach.
PLAN = {
    "wosool": "0.1",
    "workspace": "ws1",
    "entry": "step_1",
    "pipeline": [
        {"id": "step_1", "type": "action", "skill": "crm", "verb": "crm.delete_contact",
         "args": {"contact_id": "42"}, "next": "step_2"},
        {"id": "step_2", "type": "notify", "message": {"ar": "تم الحذف", "en": "deleted"}},
    ],
}


class _ParkingClient:
    """A NIL client whose commit is HELD by the System (HIGH tier): commit answers with a
    PROPOSAL-shaped body (not a STATUS) — exactly the parked-commit wire behavior."""

    def __init__(self, proposal_id: str = "hp1") -> None:
        self._pid = proposal_id

    async def propose(self, verb, args, *, session_id=None, request_timestamp=None):
        return SimpleNamespace(is_refusal=False, id=self._pid, code=None)

    async def commit(self, proposal_id, *, idempotency_key=None):
        return SimpleNamespace(tier=SimpleNamespace(value="HIGH"))  # not a StatusBody → parked


class _NeverCalledClient:
    """The resume continuation (a notify) needs no adapter — any call is a test failure."""

    def __getattr__(self, name):  # pragma: no cover - only reached on a bug
        raise AssertionError(f"resume must not call the adapter ({name})")


# ── executor: park + resume ────────────────────────────────────────────────────────────────────


async def test_high_commit_parks_the_run_with_the_proposal():
    result = await LocalExecutor(_ParkingClient(), run_id="r1").execute(PLAN)
    assert result.completed is False
    assert result.waiting == {"kind": "approval", "node": "step_1", "proposal": "hp1", "tier": "HIGH"}
    assert "step_2" not in result.context  # nothing downstream ran on a phantom result


async def test_resume_continues_at_the_continuation_with_the_bound_output():
    parked = await LocalExecutor(_ParkingClient(), run_id="r1").execute(PLAN)
    commit_output = {"proposal": "hp1", "state": "executed", "committed_id": "42"}
    result = await LocalExecutor(_NeverCalledClient(), run_id="r1").execute(
        PLAN, resume={"context": parked.context, "node_id": "step_1", "output": commit_output}
    )
    assert result.completed is True
    assert result.context["step_1"]["output"] == commit_output  # the commit result IS the output
    assert result.notifications == [{"ar": "تم الحذف", "en": "deleted"}]  # step_2 ran


# ── control plane: decision → resume (approve / reject / restart) ─────────────────────────────


def _runner():
    async def runner(plan, *, run_id, resume=None):
        client = _NeverCalledClient() if resume is not None else _ParkingClient()
        return await LocalExecutor(client, run_id=run_id, session_id=run_id).execute(
            plan, resume=resume
        )

    return runner


class _FakeStatus:
    def model_dump(self, **_):
        return {"state": "executed", "result": {"entity": {"id": "42"}}}


class _FakeCPClient:
    """Fakes the control plane's own commit of the approved proposal (`_execute_approved`)."""

    def __init__(self, *a, **k):
        pass

    async def commit(self, proposal_id, *, idempotency_key=None):
        return _FakeStatus()


async def _aclose():
    return None


def _make(tmp_path, monkeypatch, name="cp.db"):
    monkeypatch.setattr(cp_app, "NilClient", _FakeCPClient)
    monkeypatch.setattr(cp_app, "NilTransport", lambda *a, **k: SimpleNamespace(aclose=_aclose))
    store = EventStore(path=str(tmp_path / name))
    store.register_adapter("ws1", "odoo", url="https://odoo/nil", bearer="tok", system="odoo")
    store.activate_adapter("ws1", "odoo")

    async def provider(workspace: str):
        return {"reachable": True, "conformant": True, "verbs": ["crm.delete_contact"], "targets": {}}

    client = TestClient(create_app(store, secret="", skeleton_provider=provider, runner=_runner()))
    return store, client


def _arm_and_fire(client) -> dict:
    client.post("/automations/register", json={
        "automation_id": "purge", "name": {"ar": "حذف", "en": "Purge"},
        "plan": PLAN, "trigger": {"type": "manual"},
    })
    client.post("/automations/ws1/purge/1/state", json={"state": "active", "approved_by": "owner"})
    r = client.post("/automations/ws1/purge/run", json={"idempotency_key": "fire-001"})
    assert r.status_code == 200
    return r.json()["run"]


def test_run_parks_then_approval_resumes_and_completes(tmp_path, monkeypatch):
    store, client = _make(tmp_path, monkeypatch)
    run = _arm_and_fire(client)
    assert run["state"] == "waiting_approval"
    assert run["trace"]["waiting"]["proposal"] == "hp1"
    # The gate registers the hold (as os-server does), then the owner approves.
    client.post("/proposals/hp1/await", json={"verb": "crm.delete_contact", "tier": "HIGH", "workspace": "ws1"})
    decided = client.post("/proposals/hp1/decision", json={"status": "approved"}).json()
    assert decided["execution"]["executed"] is True
    assert decided["resumed"] == [
        {"run_id": run["run_id"], "node_id": "step_1", "resumed": True, "state": "completed"}
    ]
    # The run record carries the committed result bound as the gated step's output.
    final = store.get_run(run["run_id"])
    assert final["state"] == "completed"
    out = final["trace"]["context"]["step_1"]["output"]
    assert out["state"] == "executed" and out["committed_id"] == "42" and out["proposal"] == "hp1"
    assert store.parked_for_proposal("hp1") == []  # the park row is settled, not lingering


def test_rejection_marks_the_run_rejected_with_the_reason(tmp_path, monkeypatch):
    store, client = _make(tmp_path, monkeypatch)
    run = _arm_and_fire(client)
    client.post("/proposals/hp1/await", json={"verb": "crm.delete_contact", "tier": "HIGH", "workspace": "ws1"})
    decided = client.post(
        "/proposals/hp1/decision", json={"status": "rejected", "reason": "wrong contact"}
    ).json()
    assert decided["resumed"][0]["state"] == "rejected"
    final = store.get_run(run["run_id"])
    assert final["state"] == "rejected"
    assert final["trace"]["reason"] == "wrong contact"
    assert store.parked_for_proposal("hp1") == []


def test_resume_survives_a_process_restart(tmp_path, monkeypatch):
    store1, client1 = _make(tmp_path, monkeypatch)
    run = _arm_and_fire(client1)
    assert run["state"] == "waiting_approval"
    client1.post("/proposals/hp1/await", json={"verb": "crm.delete_contact", "tier": "HIGH", "workspace": "ws1"})

    # "Restart": a brand-new store handle + app over the SAME database file — no shared memory.
    store2 = EventStore(path=str(tmp_path / "cp.db"))

    async def provider(workspace: str):
        return {"reachable": True, "conformant": True, "verbs": [], "targets": {}}

    client2 = TestClient(create_app(store2, secret="", skeleton_provider=provider, runner=_runner()))
    decided = client2.post("/proposals/hp1/decision", json={"status": "approved"}).json()
    assert decided["resumed"][0]["state"] == "completed"
    final = store2.get_run(run["run_id"])
    assert final["state"] == "completed"
    assert final["trace"]["context"]["step_1"]["output"]["state"] == "executed"


def test_redelivered_decision_never_resumes_twice(tmp_path, monkeypatch):
    store, client = _make(tmp_path, monkeypatch)
    _arm_and_fire(client)
    client.post("/proposals/hp1/await", json={"verb": "crm.delete_contact", "tier": "HIGH", "workspace": "ws1"})
    first = client.post("/proposals/hp1/decision", json={"status": "approved"}).json()
    assert first["resumed"][0]["resumed"] is True
    again = client.post("/proposals/hp1/decision", json={"status": "approved"}).json()
    # decide() guards the transition; with the park settled there is nothing left to resume.
    assert again.get("resumed") is None or all(r["resumed"] is False for r in again["resumed"])


# ── await_approval nodes: decision routes the node's own branches ───────────────────────────────

GATED_PLAN = {
    "wosool": "0.1",
    "workspace": "ws1",
    "entry": "step_1",
    "pipeline": [
        {"id": "step_1", "type": "await_approval", "proposal": "gate-1", "timeout_seconds": 3600,
         "on_approved": "step_2", "on_rejected": "step_3", "on_timeout": "step_3"},
        {"id": "step_2", "type": "notify", "message": {"ar": "قُبل", "en": "approved"}},
        {"id": "step_3", "type": "notify", "message": {"ar": "رُفض", "en": "rejected"}},
    ],
}


def _parked_gate(tmp_path, name="gate.db"):
    store = EventStore(path=str(tmp_path / name))
    store.register_automation(
        workspace="ws1", automation_id="gated", content_hash="h1",
        name={"ar": "بوابة", "en": "Gate"}, plan=GATED_PLAN, trigger={"type": "manual"},
        state="active",
    )
    store.start_run("run-g1", workspace="ws1", automation_id="gated", version=1,
                    content_hash="h1", fired_by="test")
    store.finish_run("run-g1", "waiting_approval", {"waiting": {"proposal": "gate-1"}})
    store.park_run("run-g1", node_id="step_1", kind="approval", workspace="ws1",
                   automation_id="gated", version=1, proposal_id="gate-1",
                   deadline=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(), context={})
    return store


def _gate_runner():
    async def runner(plan, *, run_id, resume=None):
        return await LocalExecutor(_NeverCalledClient(), run_id=run_id).execute(plan, resume=resume)

    return runner


async def test_decision_routes_await_approval_branches(tmp_path):
    store = _parked_gate(tmp_path)
    park = store.parked_for_proposal("gate-1")[0]
    out = await resume_on_decision(store, park, runner=_gate_runner(), status="approved")
    assert out["state"] == "completed"
    assert store.get_run("run-g1")["trace"]["notifications"] == [{"ar": "قُبل", "en": "approved"}]


async def test_rejection_routes_on_rejected_branch(tmp_path):
    store = _parked_gate(tmp_path)
    park = store.parked_for_proposal("gate-1")[0]
    out = await resume_on_decision(store, park, runner=_gate_runner(), status="rejected")
    assert out["state"] == "completed"  # the on_rejected branch ran (a route, not a failure)
    assert store.get_run("run-g1")["trace"]["notifications"] == [{"ar": "رُفض", "en": "rejected"}]


async def test_deadline_passage_routes_on_timeout(tmp_path):
    store = _parked_gate(tmp_path)
    out = await resume_due_waits(store, runner=_gate_runner(), now=datetime.now(UTC))
    assert len(out) == 1 and out[0]["state"] == "completed"
    assert store.get_run("run-g1")["trace"]["notifications"] == [{"ar": "رُفض", "en": "rejected"}]
    # settled: a later decision on the same proposal finds nothing to resume
    assert store.parked_for_proposal("gate-1") == []
