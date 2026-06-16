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
- `await_approval` polls `client.status()` with a short local interval (no durable signal).
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

# Terminal STATUS state → the branch an await_approval node takes.
_APPROVAL_ROUTE: dict[str, str] = {
    "approved": "approved",
    "executed": "approved",
    "rejected": "rejected",
    "expired": "timeout",
    "failed_terminal": "rejected",
    "suspended": "rejected",
}
_MAX_STEPS = 1000


@dataclass
class RunResult:
    """The outcome of executing one program: the append-only context + an honest status."""

    completed: bool
    context: dict[str, Any] = field(default_factory=dict)
    notifications: list[dict[str, str]] = field(default_factory=list)
    compensated: list[str] = field(default_factory=list)
    partial: bool = False
    blocked_at: str | None = None
    refusal: dict[str, Any] | None = None


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

    async def execute(self, program: dict[str, Any], *, input: dict[str, Any] | None = None) -> RunResult:
        self._program = program
        self._nodes = node_map(program)
        self._ctx: dict[str, Any] = {}
        if input is not None:
            self._ctx["input"] = input  # `$.input.field` references resolve against this
        self._notifications: list[dict[str, str]] = []
        self._committed: list[str] = []  # node ids that COMMITted, in order — for the unwind
        self._ts = datetime.now(timezone.utc)
        on_error = program.get("on_error", "abort")
        try:
            await self._walk(program["entry"], item=None)
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
                )
            return RunResult(
                completed=False,
                context=self._ctx,
                notifications=self._notifications,
                blocked_at=halt.node_id,
                refusal={"node": halt.node_id, "code": halt.code},
            )
        return RunResult(completed=True, context=self._ctx, notifications=self._notifications)

    async def _walk(self, node_id: str | None, *, item: Any) -> None:
        steps = 0
        while node_id is not None:
            if steps >= _MAX_STEPS:
                raise RuntimeError(f"graph exceeded {_MAX_STEPS} steps — possible cycle at {node_id!r}")
            steps += 1
            node = self._nodes[node_id]
            output = await self._execute(node, item)
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
        self._committed.append(node["id"])
        return _outcome_dict(outcome, proposal.id)

    async def _do_await_approval(self, node: dict[str, Any], item: Any) -> str:
        proposal_id = resolve(node["proposal"], self._ctx, item=item)
        for _ in range(self._max_polls):
            status = await self._client.status(proposal_id)
            route = _APPROVAL_ROUTE.get(status.state or "")
            if route is not None:
                return route
            await asyncio.sleep(self._poll_interval)
        return "timeout"

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


def _outcome_dict(outcome: StatusBody | ProposalBody, proposal_id: str) -> dict[str, Any]:
    """Normalize a commit outcome (STATUS, or a PROPOSAL when parked) into the node's output."""
    if isinstance(outcome, StatusBody):
        state = outcome.state.value if outcome.state is not None else None
        return {"proposal": outcome.proposal, "state": state}
    tier = outcome.tier.value if outcome.tier is not None else None
    return {"proposal": proposal_id, "parked": True, "tier": tier}
