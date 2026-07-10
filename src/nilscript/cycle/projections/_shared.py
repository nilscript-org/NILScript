"""Shared, side-effect-free helpers for the Cycle projections.

A projection is a pure, read-only view over the Cycle AST — it never executes, never touches the
control plane, and adds no new source of truth. These helpers keep the four projections DRY:
bilingual text selection (prefer en, fall back ar) and the step kind/verb vocabulary.
"""

from __future__ import annotations

from nilscript.cycle.models import (
    ActionStep,
    ApprovalStep,
    Cycle,
    CycleStepType,
    DecisionStep,
    NotifyStep,
    QueryStep,
)
from nilscript.kernel.models import BilingualText


def text(value: BilingualText | None) -> str:
    """Bilingual-aware text: prefer English, fall back to Arabic, empty if absent."""
    if value is None:
        return ""
    return value.en or value.ar


def step_kind(step: CycleStepType) -> str:
    """The step's discriminator (`action`/`query`/`decision`/`approval`/`notify`)."""
    return step.type


def step_verb(step: CycleStepType) -> str | None:
    """The verb an action/query step calls (`odoo.crm_create_lead`); None for non-effecting steps."""
    if isinstance(step, ActionStep | QueryStep):
        return step.use
    return None


def step_map(cycle: Cycle) -> dict[str, CycleStepType]:
    """Name → step, for following branch targets without re-scanning the tuple."""
    return {s.id: s for s in cycle.flow.steps}


__all__ = [
    "text",
    "step_kind",
    "step_verb",
    "step_map",
    "ActionStep",
    "ApprovalStep",
    "DecisionStep",
    "NotifyStep",
    "QueryStep",
]
