"""Pure graph-walk helpers for the DSL interpreter (DynamicGraphExecutorWorkflow).

The deterministic decisions made between activity calls — routing, idempotency-key derivation,
propose shaping — live here so they are unit-testable without a Temporal server and so the
workflow body stays a thin, replay-safe orchestration shell. No I/O, no clock, no randomness.
"""

from __future__ import annotations

from typing import Any


def node_map(program: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """id → node, from an admitted program's pipeline (uniqueness guaranteed by the validator)."""
    return {node["id"]: node for node in program["pipeline"]}


def next_after(node: dict[str, Any], output: Any) -> str | None:
    """The next node id to walk to, given a node and the output it produced.

    Branching nodes choose by their output; every other node follows `next` (None = terminal).
    """
    node_type = node.get("type")
    if node_type == "condition":
        if output:
            return node.get("on_true")
        return node.get("on_false") if node.get("on_false") is not None else node.get("next")
    if node_type == "await_approval":
        return node.get(f"on_{output}")  # on_approved / on_rejected / on_timeout (None = terminal)
    return node.get("next")


def idem_key(run_id: str, node_id: str) -> str:
    """Deterministic per-node idempotency key — derived from workflow state, never uuid()/clock,
    so a retry or replay re-issues the same NIL COMMIT and the System dedupes it."""
    return f"{run_id}:{node_id}"


def propose_dict(verb: str, args: dict[str, Any]) -> dict[str, Any]:
    """The ProposeBody wire shape for an `action` node (verb + resolved hint args)."""
    return {"verb": verb, "args": args}
