"""render_plan — a deterministic, human-readable rendering of a CompiledPlan (Wave 4 §14.4c, part 1).

This is the L3 SURFACE a reviewer reads before approving: what the compiler resolved — each step's pinned
capability@version, the skill→verb it lowered to, the governed backend (D8), and the tier — plus the
plan's aggregate governance envelope (D5). Deterministic: same plan → same text (a stable audit artifact).

NOT the runnable `.nil` cycle grammar. Lowering a CompiledPlan into an executable `Cycle` AST is the
OTHER half of §14.4c and is design-gated — a BizSpec ControlStep is thinner than a runnable ApprovalStep/
WaitForEventStep (missing approver/on_approve, match/on_timeout, next-chaining), so the control-step model
must be enriched first. This renderer stands alone and needs none of that.
"""

from __future__ import annotations

from nilscript.compiler.models import CompiledPlan, CompiledStep


def _render_step(step: CompiledStep) -> str:
    if step.kind == "effect":
        head = f"  effect {step.capability}@{step.version} {step.skill} -> {step.verb} via {step.backend} ({step.tier})"
        if step.bind:
            head += f" bind {step.bind}"
        if step.args:
            # Deterministic arg order — sorted keys, so the rendering is stable/audit-comparable.
            args = ", ".join(f"{k}: {step.args[k]}" for k in sorted(step.args))
            head += f"\n    args {{{args}}}"
        return head
    # control
    tail = ""
    if step.strategy:
        tail = f" {step.strategy}"
    elif step.event:
        tail = f" {step.event}"
    elif step.to:
        tail = f" {step.to}"
    return f"  control {step.control}{tail}"


def render_plan(plan: CompiledPlan) -> str:
    """One CompiledPlan → its review text. Header names the Domain + intent + the aggregate envelope,
    then one line per lowered step."""
    env = plan.envelope
    effects = ", ".join(env.effects)
    lines = [
        f"plan in {plan.domain}",
        f'  intent "{plan.intent}"',
        f"  governance {env.tier} {env.reversibility} [{effects}]",
        *(_render_step(s) for s in plan.steps),
    ]
    return "\n".join(lines)
