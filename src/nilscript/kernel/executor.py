"""LocalExecutor — the headless, in-process port of the DSL interpreter.

This is the runtime "VM": it walks one admitted DSL program node-by-node and drives a mounted NIL
adapter via the SDK `NilClient`. It is the local, Temporal-free sibling of wosool-cloud's
`DynamicGraphExecutorWorkflow` — same graph walk, same idempotency-key format, same SEQRD-PC
honesty (PROPOSE→COMMIT, compensate-on-error), but plain `asyncio` instead of durable workflows.
Durability/replay is intentionally NOT here — that is the Wosool Cloud upgrade.

Deviations from the cloud executor (documented, intentional for v1):
- Dispatch is direct: `client.propose(node["verb"], resolved_args)` then `client.commit(...)`. The
  cloud's skill `to_proposes` hint→NIL-arg transform is a cloud/skill-registry feature; locally the
  node's resolved `args` are the NIL args.
- `notify` is collected (no channel senders); `wait` is a real `asyncio.sleep`.
- `await_approval` polls `client.status()` with a short local interval; if undecided within the
  poll budget the run PARKS (`RunResult.waiting`) — the control plane persists the park row and
  resumes the run via `execute(resume=...)` when the decision (or deadline) arrives. A HIGH-tier
  commit the System holds parks the same way. Parks inside `parallel` branches are not supported
  (the gather swallows the signal) — a gate belongs on the main path.
- Compensation uses the DSL node's own `compensate_with` (verb+args) executed via PROPOSE→COMMIT —
  an honest forward compensation. Full ROLLBACK-performative + tier-based parking is a refinement.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nilscript.kernel.graph import idem_key, next_after, node_map
from nilscript.kernel.guards import evaluate_guard
from nilscript.kernel.references import resolve
from nilscript.sdk.client import NilClient
from nilscript.sdk.sentences import ProposalBody, StatusBody

# A GENUINE human decision on a gate's proposal → the branch an await_approval node takes.
# ONLY a real decision short-circuits the gate. Every other state a status poll can report —
# `expired`/`pending`/`suspended`/`failed_terminal`, or a proposal the System never saw (a
# standalone gate handle like `gate_step_2` that was never proposed, which the adapter answers
# `expired`) — is NOT a decision. Those PARK: a human gate with no decision must WAIT (surfacing a
# pending approval), never silently self-resolve. The real deadline-driven timeout is applied by
# the control plane's `resume_due_waits` (routing on_timeout), not by an adapter's `expired`.
_APPROVAL_ROUTE: dict[str, str] = {
    "approved": "approved",
    "executed": "approved",
    "rejected": "rejected",
}
_MAX_STEPS = 1000


@dataclass
class RunResult:
    """The outcome of executing one program: the append-only context + an honest status.

    `waiting` (when set) means the run PARKED — it neither completed nor failed. It carries what
    the caller must persist to resume deterministically: the parked node, and either the proposal
    a human decision must settle (`kind: "approval"`) or the event filter a matching ledger event
    must satisfy (`kind: "event"`). The caller resumes via `execute(program, resume=...)`.
    """

    completed: bool
    context: dict[str, Any] = field(default_factory=dict)
    notifications: list[dict[str, str]] = field(default_factory=list)
    compensated: list[str] = field(default_factory=list)
    partial: bool = False
    blocked_at: str | None = None
    refusal: dict[str, Any] | None = None
    waiting: dict[str, Any] | None = None
    # Checkpoint markers walked THIS segment (plan B5): {name, node, committed, at}. The caller
    # persists each as a row (`run_checkpoints`) — the row, not this list, is the rollback SSOT.
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    # Per-node observability trace walked THIS segment — an ordered list of node events (see
    # `_NODE_EVENT_SHAPE`). Timestamps are stamped from the runtime clock (never the model). On a
    # PARK the parked node's entry is status waiting_approval|waiting_event and carries its
    # proposal_id/event_wait; earlier nodes are `completed` with a redacted output_summary. The
    # caller MERGES each segment's nodes into the persisted run trace (`trace["nodes"]`) so a
    # resumed run advances the same list rather than overwriting it — restart-safe, row-backed.
    trace_nodes: list[dict[str, Any]] = field(default_factory=list)


# The exact JSON shape of one entry in `RunResult.trace_nodes` / persisted `trace["nodes"]`.
# Documented here as the SSOT contract the control plane persists and the BFF maps to node_states.
_NODE_EVENT_SHAPE = {
    "node_id": "step_1",  # IR node id (stable across versions of the same step)
    "seq": 0,  # 0-based walk order within the persisted, merged trace
    "type": "action",  # action|query|condition|notify|wait|parallel|foreach|await_approval|
    #                     checkpoint|wait_for_event
    "verb": "crm.create_contact",  # action/query only; else None
    "adapter": None,  # reserved for composed/multi-adapter runs; None in single-adapter runs
    "label": None,  # human label if the IR carries one; else None
    "status": "completed",  # running|completed|waiting_approval|waiting_event|skipped|failed
    "started_at": "2026-07-03T10:00:00+00:00",  # ISO-8601 UTC, runtime clock
    "ended_at": "2026-07-03T10:00:00+00:00",  # ISO-8601 UTC or None while running/waiting
    "tier": None,  # governance tier when a commit/gate carries one (e.g. "HIGH"); else None
    "reversibility": None,  # saga reversibility hint when known; else None
    "output_summary": {"proposal": "p1", "state": "executed"},  # small, secret-redacted; or None
    "proposal_id": None,  # the proposal a gate/park awaits (await_approval / HIGH commit); else None
    "event_wait": None,  # {on_event, match, timeout_seconds} for a parked wait_for_event; else None
    "error": None,  # refusal code / error string when status is failed; else None
}

# Keys whose VALUES must never appear in an output_summary (secret hygiene). Matched as substrings,
# case-insensitive, against the key name.
_SECRET_KEY_HINTS = (
    "secret",
    "token",
    "password",
    "passwd",
    "bearer",
    "authorization",
    "api_key",
    "apikey",
    "private",
    "credential",
)
_REDACTED = "***REDACTED***"
_SUMMARY_MAX_KEYS = 12
_SUMMARY_MAX_STR = 200


def _summarize(value: Any, *, depth: int = 0) -> Any:
    """A small, secret-free projection of a node's output for the observability trace.

    Never emits a value under a secret-looking key; truncates long strings; collapses long/deep
    structures to counts. This is a SUMMARY for humans and the dashboard — not the SSOT effect
    (that lives in the run context / the System of record)."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= _SUMMARY_MAX_STR else value[:_SUMMARY_MAX_STR] + "…"
    if isinstance(value, dict):
        if depth >= 3:
            return {"keys": len(value)}
        out: dict[str, Any] = {}
        for key, inner in list(value.items())[:_SUMMARY_MAX_KEYS]:
            name = str(key)
            if any(hint in name.lower() for hint in _SECRET_KEY_HINTS):
                out[name] = _REDACTED
            else:
                out[name] = _summarize(inner, depth=depth + 1)
        if len(value) > _SUMMARY_MAX_KEYS:
            out["…"] = f"+{len(value) - _SUMMARY_MAX_KEYS} more"
        return out
    if isinstance(value, (list, tuple)):
        return {"count": len(value)}
    return _summarize(str(value), depth=depth)


def looks_committed(output: Any) -> bool:
    """True when an ACTION node's recorded output is a COMMITTED effect: it carries the proposal
    id and a terminal state. A parked commit ({"parked": True}, no state) and a refusal
    ({"refused": code}, no proposal) are not commits. Shared with the control plane's rollback
    preview, which replays this judgement over a persisted run trace."""
    return (
        isinstance(output, dict)
        and bool(output.get("proposal"))
        and output.get("state") is not None
        and not output.get("parked")
    )


class _Park(Exception):
    """Raised internally when the walk must stop and wait for an external signal — a human
    decision on a parked proposal, or a matching ledger event. NOT a failure: the caller
    persists `info` (row-backed at the control plane) and later resumes the run with
    `execute(program, resume=...)`. Governance outcomes are answers, never crashes."""

    def __init__(self, info: dict[str, Any]) -> None:
        super().__init__(str(info.get("kind", "park")))
        self.info = info


class CompensationHalt(Exception):
    """Raised internally when a node refuses and the program elected `on_error: compensate`."""

    def __init__(self, node_id: str, code: str) -> None:
        super().__init__(f"{node_id} refused: {code}")
        self.node_id = node_id
        self.code = code


class LocalExecutor:
    """Walks one admitted DSL program against a mounted NIL adapter. Headless, no durability."""

    def __init__(
        self,
        client: NilClient,
        *,
        session_id: str = "local-session",
        run_id: str = "local-run",
        locale: str = "ar",
        approval_poll_interval: float = 0.5,
        approval_max_polls: int = 20,
    ) -> None:
        self._client = client
        self._session_id = session_id
        self._run_id = run_id
        self._locale = locale
        self._poll_interval = approval_poll_interval
        self._max_polls = approval_max_polls

    async def execute(
        self,
        program: dict[str, Any],
        *,
        input: dict[str, Any] | None = None,
        resume: dict[str, Any] | None = None,
    ) -> RunResult:
        """Walk the program from its entry — or RESUME a parked run.

        `resume` is `{"context": <ctx at park>, "node_id": <parked node>, "output": <bound
        output>}`: the saved context is restored, the output is bound as the parked node's output,
        and the walk continues at whatever `next_after(node, output)` routes to — so an approved
        commit continues at the node's continuation and an approval/timeout route follows the
        node's own branch, with no resume-only routing logic."""
        self._program = program
        self._nodes = node_map(program)
        self._ctx: dict[str, Any] = {}
        self._notifications: list[dict[str, str]] = []
        self._committed: list[str] = []  # node ids that COMMITted, in order — for the unwind
        self._checkpoints: list[dict[str, Any]] = []  # markers walked this segment (B5)
        self._trace_nodes: list[dict[str, Any]] = []  # per-node observability events this segment
        self._ts = datetime.now(timezone.utc)
        on_error = program.get("on_error", "abort")
        if resume is not None:
            self._ctx = dict(resume.get("context") or {})
            node_id = resume["node_id"]
            output = resume.get("output")
            self._ctx[node_id] = {"output": output}
            # The parked node's decision has landed — record it COMPLETED (its resolved output) so
            # the merged trace shows the gate advancing from waiting_approval → completed. The walk
            # resumes at the node's own continuation, so the node itself is not re-walked.
            resumed_node = self._nodes.get(node_id)
            if resumed_node is not None:
                stamp = self._now()
                self._trace_nodes.append(
                    self._node_event(
                        resumed_node,
                        status="completed",
                        started_at=stamp,
                        ended_at=stamp,
                        output=output,
                        proposal_id=_proposal_of(output),
                        tier=_tier_of(output),
                    )
                )
            # Rebuild the committed-write ledger from the restored context (pipeline order —
            # deterministic) so a checkpoint or saga unwind walked AFTER a park still sees every
            # commit made before it, not just this segment's.
            self._committed = [
                node["id"]
                for node in program["pipeline"]
                if node.get("type") == "action"
                and looks_committed((self._ctx.get(node["id"]) or {}).get("output"))
            ]
            start = next_after(self._nodes[node_id], output)
        else:
            if input is not None:
                self._ctx["input"] = input  # `$.input.field` references resolve against this
            start = program["entry"]
        try:
            await self._walk(start, item=None)
        except _Park as park:
            return RunResult(
                completed=False,
                context=self._ctx,
                notifications=self._notifications,
                waiting=park.info,
                checkpoints=self._checkpoints,
                trace_nodes=self._trace_nodes,
            )
        except CompensationHalt as halt:
            if on_error == "compensate":
                done = await self._compensate()
                return RunResult(
                    completed=False,
                    context=self._ctx,
                    notifications=self._notifications,
                    compensated=done,
                    partial=True,
                    blocked_at=halt.node_id,
                    refusal={"node": halt.node_id, "code": halt.code},
                    checkpoints=self._checkpoints,
                    trace_nodes=self._trace_nodes,
                )
            return RunResult(
                completed=False,
                context=self._ctx,
                notifications=self._notifications,
                blocked_at=halt.node_id,
                refusal={"node": halt.node_id, "code": halt.code},
                checkpoints=self._checkpoints,
                trace_nodes=self._trace_nodes,
            )
        return RunResult(
            completed=True,
            context=self._ctx,
            notifications=self._notifications,
            checkpoints=self._checkpoints,
            trace_nodes=self._trace_nodes,
        )

    def _now(self) -> str:
        """The runtime wall clock as ISO-8601 UTC. Timestamps come from HERE (the runtime), never
        from a model — the repo forbids clock reads inside models."""
        return datetime.now(timezone.utc).isoformat()

    def _node_event(
        self,
        node: dict[str, Any],
        *,
        status: str,
        started_at: str,
        ended_at: str | None = None,
        output: Any = None,
        proposal_id: str | None = None,
        event_wait: dict[str, Any] | None = None,
        tier: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Build one node-trace event (`_NODE_EVENT_SHAPE`). `seq` is provisional (segment-local);
        the control plane re-sequences by final walk order when it merges segments."""
        return {
            "node_id": node["id"],
            "seq": len(self._trace_nodes),
            "type": node.get("type"),
            "verb": node.get("verb"),
            "adapter": node.get("adapter"),
            "label": node.get("label"),
            "status": status,
            "started_at": started_at,
            "ended_at": ended_at,
            "tier": tier,
            "reversibility": node.get("reversibility"),
            "output_summary": _summarize(output) if output is not None else None,
            "proposal_id": proposal_id,
            "event_wait": event_wait,
            "error": error,
        }

    async def _walk(self, node_id: str | None, *, item: Any) -> None:
        steps = 0
        while node_id is not None:
            if steps >= _MAX_STEPS:
                raise RuntimeError(f"graph exceeded {_MAX_STEPS} steps — possible cycle at {node_id!r}")
            steps += 1
            node = self._nodes[node_id]
            started_at = self._now()
            entry = self._node_event(node, status="running", started_at=started_at)
            self._trace_nodes.append(entry)
            try:
                output = await self._execute(node, item)
            except _Park as park:
                # The walk stops HERE awaiting an external signal. Mark the parked node's event as
                # waiting (approval vs event) with what the resume needs, and re-raise so the caller
                # records the park row. The node's ended_at stays None — it has not finished.
                info = park.info
                is_event = info.get("kind") == "event"
                entry["status"] = "waiting_event" if is_event else "waiting_approval"
                entry["proposal_id"] = info.get("proposal")
                entry["tier"] = info.get("tier")
                if is_event:
                    entry["event_wait"] = {
                        "on_event": info.get("on_event"),
                        "match": info.get("match"),
                        "timeout_seconds": info.get("timeout_seconds"),
                    }
                raise
            except CompensationHalt as halt:
                entry["status"] = "failed"
                entry["ended_at"] = self._now()
                entry["error"] = halt.code
                raise
            entry["status"] = "completed"
            entry["ended_at"] = self._now()
            entry["output_summary"] = _summarize(output) if output is not None else None
            entry["tier"] = _tier_of(output)
            entry["proposal_id"] = _proposal_of(output)
            self._ctx[node["id"]] = {"output": output}
            node_id = next_after(node, output)

    async def _execute(self, node: dict[str, Any], item: Any) -> Any:
        node_type = node["type"]
        if node_type == "action":
            return await self._do_action(node, item)
        if node_type == "query":
            args = resolve(node.get("args", {}), self._ctx, item=item)
            return await self._client.query(node["verb"], args or None)
        if node_type == "condition":
            return evaluate_guard(node["expression"], self._ctx, item=item)
        if node_type == "notify":
            message = resolve(node["message"], self._ctx, item=item)
            entry = {"ar": str(message.get("ar", "")), "en": str(message.get("en", ""))}
            self._notifications.append(entry)
            return None
        if node_type == "wait":
            await asyncio.sleep(node["seconds"])
            return None
        if node_type == "parallel":
            await asyncio.gather(
                *[self._walk(b, item=None) for b in node["branches"]], return_exceptions=True
            )
            return {"branches": list(node["branches"])}
        if node_type == "foreach":
            items = resolve(node["items"], self._ctx, item=item)
            capped = list(items)[: node["max_items"]] if isinstance(items, list) else []
            for element in capped:
                await self._walk(node["body"], item={node["as"]: element})
            return {"count": len(capped)}
        if node_type == "await_approval":
            return await self._do_await_approval(node, item)
        if node_type == "checkpoint":
            # A compensation boundary (B5): record the marker with the committed-so-far snapshot
            # (what a later rollback reverses BACK TO) and keep walking — no pause, no adapter.
            self._checkpoints.append(
                {
                    "name": node["name"],
                    "node": node["id"],
                    "committed": list(self._committed),
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            )
            return {"name": node["name"]}
        if node_type == "wait_for_event":
            # PARK until a matching ledger event (or the deadline). The match filter is resolved
            # NOW against the run context ($.step_N.output.* / $.input.*), so the persisted park
            # row carries literal values the event dispatcher can compare with shallow equality.
            raise _Park(
                {
                    "kind": "event",
                    "node": node["id"],
                    "on_event": node["on_event"],
                    "match": resolve(node.get("match", {}), self._ctx, item=item),
                    "timeout_seconds": node.get("timeout_seconds"),
                }
            )
        raise ValueError(f"unknown node type {node_type!r}")  # validator forbids this

    async def _do_action(self, node: dict[str, Any], item: Any) -> dict[str, Any]:
        args = resolve(node.get("args", {}), self._ctx, item=item)
        proposal = await self._client.propose(
            node["verb"], args, session_id=self._session_id, request_timestamp=self._ts
        )
        if proposal.is_refusal or not proposal.id:
            code = proposal.code.value if proposal.code is not None else "UNKNOWN"
            if self._program.get("on_error") == "compensate":
                raise CompensationHalt(node["id"], code)
            return {"refused": code}
        outcome = await self._client.commit(
            proposal.id, idempotency_key=idem_key(self._run_id, node["id"])
        )
        if not isinstance(outcome, StatusBody):
            # The System PARKED the commit (HIGH/CRITICAL tier held for a human). The run stops
            # HERE — nothing executed, so nothing downstream may run on a phantom result. The
            # decision (via the control plane) resumes the walk at this node's continuation with
            # the real commit result bound.
            tier = outcome.tier.value if outcome.tier is not None else None
            raise _Park(
                {"kind": "approval", "node": node["id"], "proposal": proposal.id, "tier": tier}
            )
        self._committed.append(node["id"])
        return _outcome_dict(outcome, proposal.id)

    async def _do_await_approval(self, node: dict[str, Any], item: Any) -> str:
        # RUN-SCOPE the gate handle. The compiled `proposal` is per-VERSION (e.g. `gate_step_2`),
        # identical across every run of the cycle. Awaiting/parking under that shared id lets a
        # second run silently bind to the FIRST run's decision — it either stalls forever (parks
        # after the shared gate was already decided) or resumes on someone else's single approval
        # (a two-key/SoD breach). Scoping by run_id gives each run its own held approval, while the
        # gate-check below, the park, and the decision→resume all key off this same id.
        gate_key = resolve(node["proposal"], self._ctx, item=item)
        proposal_id = _gate_scoped_proposal(self._run_id, gate_key)
        for _ in range(self._max_polls):
            status = await self._client.status(proposal_id)
            route = _APPROVAL_ROUTE.get(status.state or "")
            if route is not None:
                return route
            await asyncio.sleep(self._poll_interval)
        # Undecided within the local poll budget → PARK. Exhausting a poll budget is not a human
        # "timeout" decision; the control plane resumes the run row-backed when the decision (or
        # the node's real deadline) arrives, routing on_approved/on_rejected/on_timeout.
        raise _Park(
            {
                "kind": "approval",
                "node": node["id"],
                "proposal": proposal_id,
                "timeout_seconds": node.get("timeout_seconds"),
            }
        )

    async def _compensate(self) -> list[str]:
        """Honest saga unwind: walk COMMITted steps in reverse; for each with `compensate_with`,
        execute the inverse verb via PROPOSE→COMMIT. A step without `compensate_with` is
        IRREVERSIBLE — it blocks the unwind and we stop with an honest partial (never claim more)."""
        done: list[str] = []
        for node_id in reversed(self._committed):
            node = self._nodes[node_id]
            comp = node.get("compensate_with")
            if comp is None:
                break  # IRREVERSIBLE — cannot undo; stop honestly
            args = resolve(comp.get("args", {}), self._ctx, item=None)
            proposal = await self._client.propose(
                comp["verb"], args, session_id=self._session_id, request_timestamp=self._ts
            )
            if proposal.is_refusal or not proposal.id:
                break  # compensation itself refused — stop honestly
            await self._client.commit(
                proposal.id, idempotency_key=idem_key(self._run_id, f"{node_id}:rollback")
            )
            done.append(node_id)
        return done


def _gate_scoped_proposal(run_id: str, gate_key: str) -> str:
    """Run-scope a compiled gate handle so two runs of the SAME cycle version never collide on one
    held approval. The compiled `proposal` (e.g. `gate_step_2`) is per-version, identical across
    runs; this appends a URL-safe form of the run id. Stable per (run, gate) so a resume re-derives
    the exact same id."""
    safe_run = "".join(ch if (ch.isalnum() or ch in "_-") else "-" for ch in run_id)
    return f"{gate_key}--{safe_run}"


def _proposal_of(output: Any) -> str | None:
    """The proposal id an ACTION node's output carries (committed or parked), for the node trace."""
    if isinstance(output, dict) and output.get("proposal"):
        return str(output["proposal"])
    return None


def _tier_of(output: Any) -> str | None:
    """The governance tier an ACTION node's output carries (set on a parked HIGH commit)."""
    if isinstance(output, dict) and output.get("tier"):
        return str(output["tier"])
    return None


def _outcome_dict(outcome: StatusBody | ProposalBody, proposal_id: str) -> dict[str, Any]:
    """Normalize a commit outcome (STATUS, or a PROPOSAL when parked) into the node's output."""
    if isinstance(outcome, StatusBody):
        state = outcome.state.value if outcome.state is not None else None
        return {"proposal": outcome.proposal, "state": state}
    tier = outcome.tier.value if outcome.tier is not None else None
    return {"proposal": proposal_id, "parked": True, "tier": tier}
