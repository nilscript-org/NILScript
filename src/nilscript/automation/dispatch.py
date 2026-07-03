"""The dispatcher: fire one run of an armed automation through the executor, recorded in the SSOT.

P2. `fire_manual` is the only trigger P1/P2 execute end to end. It enforces the governance gate
(only an `active` automation runs), pins the exact stored version, derives a deterministic `run_id`
so a re-delivered fire replays rather than double-executes, and records the executor trace as a
first-class run row. The `runner` (what actually walks the plan) is injected so the orchestration is
testable without a live backend; the control-plane app supplies a `LocalExecutor`-backed default.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from nilscript.automation.compose import (
    ComposedResult,
    StageRunner,
    parse_composed,
    run_composed,
)
from nilscript.kernel.executor import RunResult
from nilscript.kernel.graph import node_map

# Walks a plan and returns its RunResult. (plan_dict, run_id[, resume]) -> RunResult.
Runner = Callable[..., Awaitable[RunResult]]


class _Store(Protocol):
    def get_automation(
        self, workspace: str, automation_id: str, version: int | None = ...
    ) -> dict[str, Any] | None: ...
    def start_run(self, run_id: str, **kw: Any) -> bool: ...
    def finish_run(self, run_id: str, state: str, trace: dict[str, Any] | None) -> bool: ...
    def get_run(self, run_id: str) -> dict[str, Any] | None: ...
    def park_run(self, run_id: str, **kw: Any) -> dict[str, Any]: ...
    def settle_park(self, run_id: str, node_id: str, status: str) -> bool: ...
    def record_checkpoint(self, run_id: str, **kw: Any) -> bool: ...


def _classify(result: RunResult) -> str:
    """Map an executor RunResult onto a run state. `completed` is the only success; a park is a
    WAITING state (not terminal — a decision/event/deadline resumes it); a saga unwind is
    `compensated`; a halt at a node is `blocked`; anything else partial is `partial`."""
    if result.completed:
        return "completed"
    if result.waiting is not None:
        return "waiting_event" if result.waiting.get("kind") == "event" else "waiting_approval"
    if result.compensated:
        return "compensated"
    if result.blocked_at:
        return "blocked"
    return "partial"


def _merge_trace_nodes(
    prior: list[dict[str, Any]], segment: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge one segment's node events onto the run's accumulated node trace.

    A run walks in SEGMENTS (the first fire, then one segment per park→resume). Each segment's
    executor only sees the nodes it walked, so the persisted `trace["nodes"]` must ACCUMULATE:
    a later event for the same node_id REPLACES the earlier one (waiting_approval → completed),
    a new node_id APPENDS in walk order. `seq` is re-stamped to the final 0-based order — the
    persisted list is the single ordered timeline the dashboard renders."""
    order: list[str] = [n["node_id"] for n in prior]
    by_id: dict[str, dict[str, Any]] = {n["node_id"]: n for n in prior}
    for event in segment:
        node_id = event["node_id"]
        if node_id not in by_id:
            order.append(node_id)
        by_id[node_id] = event
    merged: list[dict[str, Any]] = []
    for seq, node_id in enumerate(order):
        node = dict(by_id[node_id])
        node["seq"] = seq
        merged.append(node)
    return merged


def _current_node(nodes: list[dict[str, Any]], result: RunResult) -> str | None:
    """The node a reader should point at now: the one still running/waiting, else the parked node,
    else the last node walked (the run's leading edge)."""
    for node in nodes:
        if node.get("status") in ("running", "waiting_approval", "waiting_event"):
            return node["node_id"]
    if result.waiting is not None:
        return result.waiting.get("node")
    return nodes[-1]["node_id"] if nodes else result.blocked_at


def _trace(result: RunResult, prior_nodes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    nodes = _merge_trace_nodes(prior_nodes or [], result.trace_nodes)
    return {
        "completed": result.completed,
        "partial": result.partial,
        "blocked_at": result.blocked_at,
        "refusal": result.refusal,
        "compensated": result.compensated,
        "notifications": result.notifications,
        "context": result.context,
        "waiting": result.waiting,
        "checkpoints": result.checkpoints,
        # Per-node observability trace (SSOT contract in kernel/executor `_NODE_EVENT_SHAPE`),
        # accumulated across every park/resume segment. Row-backed via the run's trace blob.
        "nodes": nodes,
        "current_node": _current_node(nodes, result),
        "updated_at": datetime.now(UTC).isoformat(),
    }


def _record(
    store: _Store,
    run_id: str,
    result: RunResult,
    *,
    workspace: str,
    automation_id: str,
    version: int,
) -> None:
    """Close (or park) one run row from its RunResult. Every checkpoint marker the segment
    walked persists as a `run_checkpoints` row (B5 — the rollback address, idempotent by
    (run_id, name)). A waiting result ALSO persists a `parked_runs` row — the row, not any
    in-memory await, is what a decision/event resumes, so a process restart between park and
    decision loses nothing."""
    prior = store.get_run(run_id)
    prior_nodes = []
    if prior and isinstance(prior.get("trace"), dict):
        prior_nodes = prior["trace"].get("nodes") or []
    store.finish_run(run_id, _classify(result), _trace(result, prior_nodes))
    for marker in result.checkpoints:
        store.record_checkpoint(
            run_id,
            name=marker.get("name") or "",
            node_id=marker.get("node") or "",
            workspace=workspace,
            committed=marker.get("committed") or [],
            at=marker.get("at"),
        )
    if result.waiting is None:
        return
    w = result.waiting
    deadline = None
    if w.get("timeout_seconds"):
        deadline = (
            datetime.now(UTC) + timedelta(seconds=int(w["timeout_seconds"]))
        ).isoformat()
    store.park_run(
        run_id,
        node_id=w.get("node") or "",
        kind=w.get("kind") or "approval",
        workspace=workspace,
        automation_id=automation_id,
        version=version,
        proposal_id=w.get("proposal"),
        on_event=w.get("on_event"),
        match=w.get("match"),
        deadline=deadline,
        context=result.context,
    )


async def fire_manual(
    store: _Store,
    *,
    workspace: str,
    automation_id: str,
    idempotency_key: str,
    runner: Runner,
    fired_by: str = "manual",
    input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fire the latest version of an automation now. Returns a result envelope:

    - `{"ok": False, "error": ..., "status": 404|409}` when it cannot run (unknown / not armed),
    - `{"ok": True, "replayed": True, "run": ...}` for an idempotent re-fire (no re-execution),
    - `{"ok": True, "run": ...}` after a fresh run (run row carries the terminal state + trace).
    """
    auto = store.get_automation(workspace, automation_id)
    if auto is None:
        return {"ok": False, "error": "no such automation", "status": 404}
    if auto["state"] != "active":
        return {
            "ok": False,
            "error": f"automation is {auto['state']!r}, not active — approve/arm it first",
            "status": 409,
        }

    version, content_hash = auto["version"], auto["content_hash"]
    run_id = f"{automation_id}:v{version}:{idempotency_key}"

    if not store.start_run(
        run_id, workspace=workspace, automation_id=automation_id, version=version,
        content_hash=content_hash, fired_by=fired_by,
    ):
        return {"ok": True, "replayed": True, "run": store.get_run(run_id)}

    try:
        # `input` binds as the run's $.input (a prepared execution's seeded inputs). Passed only
        # when present so existing runner fakes with narrower signatures stay valid.
        result = await runner(auto["plan"], run_id=run_id, **({"input": input} if input else {}))
    except Exception as exc:  # noqa: BLE001 — a runner blow-up is a failed run, recorded honestly
        store.finish_run(run_id, "failed", {"error": str(exc)})
        return {"ok": False, "error": str(exc), "status": 500, "run": store.get_run(run_id)}

    _record(store, run_id, result, workspace=workspace, automation_id=automation_id, version=version)
    return {"ok": True, "run": store.get_run(run_id)}


async def resume_parked_run(
    store: _Store,
    park: dict[str, Any],
    *,
    runner: Runner,
    output: Any,
    final_state: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Resume ONE parked run deterministically from its row.

    `output` is bound as the parked node's output and the walk continues via the node's OWN
    routing (`next_after`) — no resume-only control flow. `final_state` short-circuits instead
    (a rejected HIGH write continues nowhere: the run closes as rejected, with the reason).
    The park row is CLAIMED first (waiting → settled), so a re-delivered decision/event replays
    as a no-op rather than resuming twice.
    """
    run_id, node_id = park["run_id"], park["node_id"]
    if not store.settle_park(run_id, node_id, final_state or "resumed"):
        return {"run_id": run_id, "node_id": node_id, "resumed": False, "reason": "already settled"}
    if final_state is not None:
        store.finish_run(
            run_id,
            final_state,
            {"reason": reason, "node": node_id, "proposal": park.get("proposal_id")},
        )
        return {"run_id": run_id, "node_id": node_id, "resumed": False, "state": final_state}
    auto = store.get_automation(
        park.get("workspace") or "", park.get("automation_id") or "", park.get("version")
    )
    if auto is None:
        store.finish_run(run_id, "failed", {"error": "parked run's pinned automation version is gone"})
        return {"run_id": run_id, "node_id": node_id, "resumed": False, "state": "failed"}
    try:
        result = await runner(
            auto["plan"],
            run_id=run_id,
            resume={"context": park.get("context") or {}, "node_id": node_id, "output": output},
        )
    except Exception as exc:  # noqa: BLE001 — a resume blow-up is a failed run, recorded honestly
        store.finish_run(run_id, "failed", {"error": str(exc)})
        return {"run_id": run_id, "node_id": node_id, "resumed": True, "state": "failed"}
    _record(
        store,
        run_id,
        result,
        workspace=park.get("workspace") or "",
        automation_id=park.get("automation_id") or "",
        version=int(park.get("version") or 0),
    )
    return {"run_id": run_id, "node_id": node_id, "resumed": True, "state": _classify(result)}


def _parked_node(store: _Store, park: dict[str, Any]) -> dict[str, Any] | None:
    """The parked IR node, from the run's PINNED automation version (None when it is gone)."""
    auto = store.get_automation(
        park.get("workspace") or "", park.get("automation_id") or "", park.get("version")
    )
    if auto is None or not isinstance(auto.get("plan"), dict):
        return None
    return node_map(auto["plan"]).get(park["node_id"])


async def resume_on_decision(
    store: _Store,
    park: dict[str, Any],
    *,
    runner: Runner,
    status: str,
    commit_output: dict[str, Any] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Route a human decision into a parked run — the deterministic gate-resume contract.

    - An `await_approval` node takes its own branch: approve → on_approved, reject → on_rejected
      (or, with no reject route, the run closes as rejected).
    - An action node parked on a HIGH-tier commit: approve → continue at the node's continuation
      with the control plane's commit result bound as its output; reject → the run closes as
      rejected with the reason (there is nothing safe to continue into).
    """
    node = _parked_node(store, park)
    if node is not None and node.get("type") == "await_approval":
        if status == "rejected" and not node.get("on_rejected"):
            return await resume_parked_run(
                store, park, runner=runner, output=None, final_state="rejected", reason=reason
            )
        return await resume_parked_run(store, park, runner=runner, output=status)
    if status == "approved":
        return await resume_parked_run(store, park, runner=runner, output=commit_output or {})
    return await resume_parked_run(
        store, park, runner=runner, output=None, final_state="rejected", reason=reason
    )


def _classify_composed(result: ComposedResult) -> str:
    if result.completed:
        return "completed"
    return "blocked" if result.blocked_at else "partial"


async def fire_composed(
    store: _Store,
    *,
    workspace: str,
    automation_id: str,
    idempotency_key: str,
    stage_runner: StageRunner,
    fired_by: str = "manual",
) -> dict[str, Any]:
    """Fire a *composed* automation now — run each stage against its adapter, threading the declared
    handoffs. Same gate/idempotency/recording as `fire_manual`; the run trace carries per-stage status."""
    auto = store.get_automation(workspace, automation_id)
    if auto is None:
        return {"ok": False, "error": "no such automation", "status": 404}
    if auto.get("kind") != "composed":
        return {"ok": False, "error": "automation is not composed", "status": 400}
    if auto["state"] != "active":
        return {
            "ok": False,
            "error": f"automation is {auto['state']!r}, not active — approve/arm it first",
            "status": 409,
        }

    version, content_hash = auto["version"], auto["content_hash"]
    run_id = f"{automation_id}:v{version}:{idempotency_key}"
    if not store.start_run(
        run_id, workspace=workspace, automation_id=automation_id, version=version,
        content_hash=content_hash, fired_by=fired_by,
    ):
        return {"ok": True, "replayed": True, "run": store.get_run(run_id)}

    try:
        composed = parse_composed(auto["plan"])
        result = await run_composed(composed, run_stage=stage_runner, run_id=run_id)
    except Exception as exc:  # noqa: BLE001 — a stage-runner blow-up is a failed run, recorded honestly
        store.finish_run(run_id, "failed", {"error": str(exc)})
        return {"ok": False, "error": str(exc), "status": 500, "run": store.get_run(run_id)}

    store.finish_run(run_id, _classify_composed(result), {
        "completed": result.completed, "blocked_at": result.blocked_at,
        "stages": result.stages, "context": result.context,
    })
    return {"ok": True, "run": store.get_run(run_id)}
