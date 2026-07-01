"""`simulate` — the dry-run / "preview what will happen" projection.

A pure function: Cycle → an ordered list of proposed steps along the HAPPY PATH from `flow.entry`.
For a decision it follows on_true; for an approval it follows on_approve (the optimistic walk). It
PROPOSES only — no verb is executed, no control plane is touched, nothing is committed. The walk is
capped at len(steps) so a malformed `next` cycle can never loop forever.
"""

from __future__ import annotations

from nilscript.cycle.models import (
    ActionStep,
    ApprovalStep,
    Cycle,
    DecisionStep,
    NotifyStep,
    QueryStep,
)
from nilscript.cycle.projections._shared import step_map


def _entry(step: object) -> tuple[dict, str | None]:
    """The proposed-step record + the name of the next step on the happy path."""
    record: dict = {
        "step": step.id,
        "kind": step.type,
        "requires_approval": isinstance(step, ApprovalStep),
    }
    if isinstance(step, ActionStep | QueryStep):
        record["verb"] = step.use
        record["proposes"] = step.use  # what WOULD be proposed — never executed
        next_name = step.next
    elif isinstance(step, ApprovalStep):
        record["approver"] = step.approver
        next_name = step.on_approve  # happy path takes the approval
    elif isinstance(step, DecisionStep):
        next_name = step.on_true  # happy path takes the true branch
    elif isinstance(step, NotifyStep):
        next_name = step.next
    else:
        next_name = None
    return record, next_name


def simulate(cycle: Cycle) -> list[dict]:
    """Walk the happy path and return the ordered list of proposed steps (no side effects)."""
    by_name = step_map(cycle)
    walk: list[dict] = []
    seen: set[str] = set()
    current: str | None = cycle.flow.entry
    cap = len(cycle.flow.steps)

    while current is not None and current in by_name and len(walk) < cap:
        if current in seen:
            break  # defensive: a `next` cycle — stop rather than loop
        seen.add(current)
        record, next_name = _entry(by_name[current])
        walk.append(record)
        current = next_name

    return walk


__all__ = ["simulate"]
