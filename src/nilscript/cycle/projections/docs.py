"""`to_markdown` — the human-documentation projection of a Cycle.

A pure function: Cycle → a Markdown string a non-engineer can read. Title, metadata block, trigger,
a Context table (entity → type → role), a numbered Steps section that says in plain language what
each step does, and the declared Outcomes. Bilingual-aware (prefer en, fall back ar). No execution.
"""

from __future__ import annotations

from nilscript.automation.models import EventTrigger, ManualTrigger, ScheduleTrigger
from nilscript.cycle.models import (
    ActionStep,
    ApprovalStep,
    Cycle,
    DecisionStep,
    NotifyStep,
    QueryStep,
)
from nilscript.cycle.projections._shared import text


def _trigger_line(cycle: Cycle) -> str:
    trigger = cycle.trigger
    if isinstance(trigger, EventTrigger):
        return f"On event `{trigger.on_verb}`"
    if isinstance(trigger, ScheduleTrigger):
        if trigger.cron:
            return f"On schedule (cron `{trigger.cron}`)"
        return f"On schedule (every {trigger.interval_seconds}s)"
    if isinstance(trigger, ManualTrigger):
        return "Manual start"
    return "Unknown trigger"


def _step_sentence(step: object) -> str:
    """A one-line, plain-language description of what a step does."""
    if isinstance(step, ActionStep):
        return f"Calls `{step.use}`" + (f", binding the result to `{step.output}`" if step.output else "")
    if isinstance(step, QueryStep):
        return f"Reads via `{step.use}`" + (f", binding the result to `{step.output}`" if step.output else "")
    if isinstance(step, ApprovalStep):
        target = f" → approved goes to **{step.on_approve}**" + (
            f", rejected goes to **{step.on_reject}**" if step.on_reject else ""
        )
        return f"Waits for {{{step.approver}}} approval: {text(step.title)}{target}"
    if isinstance(step, DecisionStep):
        false_target = f", else **{step.on_false}**" if step.on_false else ""
        return f"Decides `{step.when}` → if true **{step.on_true}**{false_target}"
    if isinstance(step, NotifyStep):
        return f"Notifies: {text(step.message)}"
    return ""


def _steps_section(cycle: Cycle) -> list[str]:
    lines = ["## Steps", ""]
    for i, step in enumerate(cycle.flow.steps, start=1):
        lines.append(f"{i}. **{step.id}** — {_step_sentence(step)}")
    return lines


def to_markdown(cycle: Cycle) -> str:
    """Render the cycle as human-readable Markdown documentation."""
    meta = cycle.metadata
    lines: list[str] = [
        f"# {cycle.cycle_id} — {text(cycle.intent)}",
        "",
        f"- **Version:** {meta.version}",
        f"- **Owner:** {meta.owner}",
        f"- **Workspace:** {cycle.workspace}",
        f"- **Tags:** {', '.join(meta.tags) if meta.tags else '—'}",
        "",
        f"**Trigger:** {_trigger_line(cycle)}",
        "",
    ]

    lines += ["## Context", "", "| Entity | Type | Role |", "| --- | --- | --- |"]
    if cycle.context:
        for ref in cycle.context:
            lines.append(f"| {ref.name} | {ref.entity_type} | {ref.role or '—'} |")
    else:
        lines.append("| — | — | — |")
    lines.append("")

    lines += _steps_section(cycle)
    lines.append("")

    lines += ["## Outcomes", ""]
    if cycle.outcomes:
        for outcome in cycle.outcomes:
            cond = f" (when `{outcome.when}`)" if outcome.when else ""
            lines.append(f"- **{outcome.name}**{cond}")
    else:
        lines.append("- —")

    return "\n".join(lines)


__all__ = ["to_markdown"]
