"""lower_to_flow — CompiledPlan → a runnable cycle Flow (Wave 4 §14.4c pt.2).

The compiler-synthesized half of L3: the plan's ordered steps become a valid `Flow` (the kernel's
executable step graph). This is where the RUNTIME SCAFFOLDING that L2 deliberately omits (§11) is
generated — stable step ids, linear `next`-chaining, and the required transition targets
(`on_approve`/`on_reject`/`on_timeout`) — none of it authored in the BizSpec. Effects lower to
ActionSteps on the resolved verb; control primitives lower to their kernel step type. A trailing
terminal step gives every required target a valid destination, so the Flow is always well-formed.

Decision steps are not lowered in v0.1 (linear plans only) — a `decision` control step is a refusal.
"""

from __future__ import annotations

from nilscript.compiler.compile import CompileRefusal
from nilscript.compiler.models import CompiledPlan, CompiledStep
from nilscript.cycle.models import (
    ActionStep,
    ApprovalStep,
    CheckpointStep,
    Flow,
    NotifyStep,
    WaitForEventStep,
)

_TERMINAL_ID = "Done"
_TERMINAL_MSG = {"en": "Completed", "ar": "اكتمل"}
_DEFAULT_TIMEOUT = 86400  # 24h — a sane approval/wait SLA when the BizSpec didn't state one


def _step_id(index: int) -> str:
    return f"Step{index + 1}"  # STEP_ID_PATTERN: starts alpha, no dots


def _lower_effect(step: CompiledStep, sid: str, nxt: str) -> ActionStep:
    return ActionStep.model_validate({
        "id": sid,
        "type": "action",
        "use": step.verb,  # the resolved concrete verb
        "with": dict(step.args),
        "output": step.bind,
        "next": nxt,
    })


def _lower_control(step: CompiledStep, sid: str, nxt: str) -> object:
    kind = step.control
    if kind == "approval":
        return ApprovalStep(
            id=sid, type="approval",
            title={"en": f"Approve: {step.strategy}", "ar": f"اعتماد: {step.strategy}"},
            approver=step.approver or "owner",
            timeout_seconds=step.timeout_seconds or _DEFAULT_TIMEOUT,
            on_approve=nxt, on_reject=_TERMINAL_ID, on_timeout=_TERMINAL_ID,
        )
    if kind == "notify":
        return NotifyStep(id=sid, type="notify", message=step.message, next=nxt)
    if kind == "checkpoint":
        return CheckpointStep(id=sid, type="checkpoint", name=step.to, next=nxt)
    if kind == "wait":
        return WaitForEventStep(
            id=sid, type="wait_for_event", on_event=step.event, match=dict(step.match),
            timeout_seconds=step.timeout_seconds or _DEFAULT_TIMEOUT,
            on_timeout=_TERMINAL_ID, next=nxt,
        )
    raise CompileRefusal("UNSUPPORTED_STEP", f"control step {kind!r} cannot be lowered in v0.1")


def lower_to_flow(plan: CompiledPlan) -> Flow:
    """The plan's steps → a well-formed `Flow`. Linear: step i continues to step i+1, the last business
    step to the terminal. A `wait` with an `escalate` message (§14.5a) routes its timeout to a
    synthesized escalation notify (emit-and-halt), not the terminal — the non-linear branch cyc_order
    needs. Empty plan → just the terminal (a no-op flow)."""
    n = len(plan.steps)
    nodes: list[object] = []
    escalations: list[object] = []  # synthesized on-timeout escalation terminals, appended at the end
    for i, step in enumerate(plan.steps):
        sid = _step_id(i)
        nxt = _step_id(i + 1) if i + 1 < n else _TERMINAL_ID
        if step.kind == "effect":
            nodes.append(_lower_effect(step, sid, nxt))
        elif step.control == "wait" and step.escalate is not None:
            esc_id = f"Escalate{i + 1}"  # a distinct halt node this wait's timeout routes to
            escalations.append(
                NotifyStep(id=esc_id, type="notify", message=step.escalate, next=None)
            )
            nodes.append(WaitForEventStep(
                id=sid, type="wait_for_event", on_event=step.event, match=dict(step.match),
                timeout_seconds=step.timeout_seconds or _DEFAULT_TIMEOUT,
                on_timeout=esc_id, next=nxt,
            ))
        else:
            nodes.append(_lower_control(step, sid, nxt))
    # The terminal: a no-op notify that ends the flow, so every required target resolves.
    nodes.append(NotifyStep(id=_TERMINAL_ID, type="notify", message=_TERMINAL_MSG, next=None))
    nodes.extend(escalations)
    entry = _step_id(0) if n else _TERMINAL_ID
    return Flow(entry=entry, steps=tuple(nodes))
