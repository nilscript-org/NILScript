"""Automation Registry: conversation-authored, deterministically-lowered, SSOT-stored workflows.

An *automation* is a named, versioned, content-hashed `WosoolProgram` plus a trigger and a
lifecycle state. The agent drafts it (untrusted); the kernel validator lowers-or-rejects it
(deterministic); a human approves it; it lives in the control-plane store with its own version lock.

See `docs/PLAN-dynamic-automation-ssot.md`. P1 ships the SSOT spine (models, content hash, draft
gate, persistence, lifecycle); schedule/event triggers and the dispatcher are P2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nilscript.automation.models import (
    AutomationDefinition,
    AutomationState,
    EventTrigger,
    ManualTrigger,
    ScheduleTrigger,
    TriggerSpec,
    content_hash,
    parse_trigger,
)

if TYPE_CHECKING:  # pragma: no cover — types only; runtime imports are lazy (see __getattr__)
    from nilscript.automation.authoring import DraftResult, draft_automation, register
    from nilscript.automation.compose import (
        ComposedPlan,
        ComposedResult,
        Stage,
        composed_hash,
        parse_composed,
        run_composed,
        validate_composed,
    )
    from nilscript.automation.dispatch import (
        Runner,
        fire_composed,
        fire_manual,
        resume_on_decision,
        resume_parked_run,
    )
    from nilscript.automation.scheduler import dispatch_event, resume_due_waits, run_due_schedules
    from nilscript.automation.skeleton import context_from_skeleton

# Which lazy attribute lives in which submodule (PEP 562). Only `models` is imported eagerly:
# nilscript.cycle.models needs TriggerSpec at class-build time, but pulling authoring/compose/
# dispatch here closes an import loop (compose → kernel.executor → runtime → command_bus →
# cycle.models → THIS package) that crashes any entrypoint reaching cycle.models before the
# runtime (e.g. the brain's api module). Deferring the executor-adjacent halves breaks the loop
# while `from nilscript.automation import run_composed` keeps working unchanged.
_LAZY: dict[str, str] = {
    "DraftResult": "authoring", "draft_automation": "authoring", "register": "authoring",
    "ComposedPlan": "compose", "ComposedResult": "compose", "Stage": "compose",
    "composed_hash": "compose", "parse_composed": "compose", "run_composed": "compose",
    "validate_composed": "compose",
    "Runner": "dispatch", "fire_composed": "dispatch", "fire_manual": "dispatch",
    "resume_on_decision": "dispatch", "resume_parked_run": "dispatch",
    "dispatch_event": "scheduler", "resume_due_waits": "scheduler", "run_due_schedules": "scheduler",
    "context_from_skeleton": "skeleton",
}


def __getattr__(name: str) -> Any:
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(f"nilscript.automation.{submodule}"), name)

__all__ = [
    "AutomationDefinition",
    "AutomationState",
    "ComposedPlan",
    "ComposedResult",
    "DraftResult",
    "Stage",
    "EventTrigger",
    "ManualTrigger",
    "Runner",
    "ScheduleTrigger",
    "TriggerSpec",
    "composed_hash",
    "content_hash",
    "context_from_skeleton",
    "dispatch_event",
    "draft_automation",
    "fire_composed",
    "fire_manual",
    "parse_composed",
    "parse_trigger",
    "register",
    "resume_due_waits",
    "resume_on_decision",
    "resume_parked_run",
    "run_composed",
    "run_due_schedules",
    "validate_composed",
]
