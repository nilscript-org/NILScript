"""The scheduler: turn ledger events and clock ticks into automation fires.

Two seams, both single-instance and Temporal-free (the durable cloud sibling is the upgrade):
- `dispatch_event` — called when an event lands in the ledger; fires active EventTrigger automations
  whose filter matches. A loop guard skips events that a control-plane-fired run itself produced.
- `run_due_schedules` — called by an external clock (cron/Temporal hitting `POST /automations/tick`);
  fires active interval ScheduleTrigger automations that are due.

Both reuse `fire_manual`, so triggered runs inherit the same governance gate (must be `active`),
version pinning, idempotency, and recorded trace as a manual run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from nilscript.automation.dispatch import Runner, fire_manual, resume_parked_run
from nilscript.automation.models import EventTrigger, ScheduleTrigger, parse_trigger
from nilscript.automation.triggers import (
    event_fire_key,
    event_matches,
    schedule_due,
    schedule_fire_key,
    wait_matches,
)

# A control-plane-fired run's own events carry this grant; never let them re-trigger automations.
_CP_GRANT = "control-plane"


async def dispatch_event(
    store: Any, envelope: dict[str, Any], *, runner: Runner, fired_by: str = "event"
) -> list[dict[str, Any]]:
    """Fire every active EventTrigger automation in the event's workspace whose filter matches,
    and RESUME every parked `wait_for_event` run the event satisfies — one ledger dispatch path,
    same loop guard, so a waiting run wakes exactly where a trigger would fire."""
    if (envelope.get("grant") or "") == _CP_GRANT:
        return []  # loop guard — this event came from a triggered run
    workspace = envelope.get("workspace", "") or ""
    fired: list[dict[str, Any]] = []
    for auto in store.active_automations():
        if auto["workspace"] != workspace:
            continue
        trigger = parse_trigger(auto["trigger"])
        if not isinstance(trigger, EventTrigger) or not event_matches(trigger, envelope):
            continue
        fired.append(
            await fire_manual(
                store, workspace=workspace, automation_id=auto["automation_id"],
                idempotency_key=event_fire_key(envelope), runner=runner, fired_by=fired_by,
            )
        )
    fired.extend(await resume_event_waits(store, envelope, runner=runner))
    return fired


async def resume_event_waits(
    store: Any, envelope: dict[str, Any], *, runner: Runner
) -> list[dict[str, Any]]:
    """Resume every WAITING `wait_for_event` park in the envelope's workspace that the event
    satisfies (event-name equality + shallow `match` field-equality). The event body is bound as
    the parked step's output, so downstream steps read `$.step_N.output.args.<field>`."""
    workspace = envelope.get("workspace", "") or ""
    body = envelope.get("body") or {}
    resumed: list[dict[str, Any]] = []
    for park in store.waiting_parks(kind="event", workspace=workspace):
        if not wait_matches(park.get("on_event"), park.get("match") or {}, envelope):
            continue
        resumed.append(await resume_parked_run(store, park, runner=runner, output=dict(body)))
    return resumed


async def resume_due_waits(
    store: Any, *, runner: Runner, now: datetime
) -> list[dict[str, Any]]:
    """Resume every parked run whose deadline has passed: a `wait_for_event` park takes its
    timeout route (`{"timed_out": True}` routes to `on_timeout`); an `await_approval` park takes
    its `on_timeout` branch (output "timeout"). Called by the same external clock as schedules."""
    out: list[dict[str, Any]] = []
    for park in store.due_parks(now.isoformat()):
        if park.get("kind") == "event":
            out.append(
                await resume_parked_run(store, park, runner=runner, output={"timed_out": True})
            )
        else:
            out.append(await resume_parked_run(store, park, runner=runner, output="timeout"))
    return out


async def run_due_schedules(
    store: Any, *, runner: Runner, now: datetime, fired_by: str = "schedule"
) -> list[dict[str, Any]]:
    """Fire every active interval-ScheduleTrigger automation that is due as of `now`."""
    fired: list[dict[str, Any]] = []
    for auto in store.active_automations():
        trigger = parse_trigger(auto["trigger"])
        if not isinstance(trigger, ScheduleTrigger):
            continue
        recent = store.list_runs(auto["workspace"], auto["automation_id"], limit=1)
        last = recent[0]["started_at"] if recent else None
        if not schedule_due(trigger, last, now):
            continue
        fired.append(
            await fire_manual(
                store, workspace=auto["workspace"], automation_id=auto["automation_id"],
                idempotency_key=schedule_fire_key(trigger, now), runner=runner, fired_by=fired_by,
            )
        )
    return fired
