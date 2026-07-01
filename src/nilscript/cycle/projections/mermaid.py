"""`to_mermaid` — the diagram projection of a Cycle's flow.

A pure function: Cycle → a Mermaid `flowchart TD` string. Each step is a node (approval → decision
diamond `{...}`, everything else → a box `[...]`); edges follow next/on_true/on_false/on_approve/
on_reject, labelled where the branch carries meaning. Output is deterministic (steps emitted in
declaration order). No execution, no control plane — a drawing of the AST, nothing more.
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
from nilscript.cycle.projections._shared import text


def _label(step: object) -> str:
    """A short human label: the step name + its verb (actions/queries) or type."""
    if isinstance(step, ActionStep | QueryStep):
        return f"{step.id}: {step.use}"  # name + verb
    if isinstance(step, ApprovalStep):
        return f"{step.id}: approve {text(step.title)}".rstrip()
    if isinstance(step, DecisionStep):
        return f"{step.id}: decide"
    if isinstance(step, NotifyStep):
        return f"{step.id}: notify"
    return getattr(step, "id", "?")


def _sanitize(label: str) -> str:
    """Mermaid node labels cannot carry the bracket/quote characters that close a node — strip them
    to keep the diagram parseable and deterministic."""
    return label.replace('"', "'").replace("[", "(").replace("]", ")").replace("{", "(").replace("}", ")")


def _node(step: object) -> str:
    """A node declaration: approval → diamond `{...}`, everything else → box `[...]`."""
    label = _sanitize(_label(step))
    if isinstance(step, ApprovalStep):
        return f'{step.id}{{"{label}"}}'
    return f'{step.id}["{label}"]'


def _edge(src: str, dst: str, label: str | None = None) -> str:
    return f"  {src} -->|{label}| {dst}" if label else f"  {src} --> {dst}"


def to_mermaid(cycle: Cycle) -> str:
    """Render the cycle's flow as a deterministic Mermaid `flowchart TD`."""
    lines: list[str] = ["flowchart TD"]
    edges: list[str] = []

    for step in cycle.flow.steps:
        lines.append(f"  {_node(step)}")
        if isinstance(step, ApprovalStep):
            edges.append(_edge(step.id, step.on_approve, "approve"))
            if step.on_reject is not None:
                edges.append(_edge(step.id, step.on_reject, "reject"))
        elif isinstance(step, DecisionStep):
            edges.append(_edge(step.id, step.on_true, "true"))
            if step.on_false is not None:
                edges.append(_edge(step.id, step.on_false, "false"))
        else:
            nxt = getattr(step, "next", None)
            if nxt is not None:
                edges.append(_edge(step.id, nxt))

    return "\n".join(lines + edges)


__all__ = ["to_mermaid"]
