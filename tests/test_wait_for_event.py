"""`wait_for_event` — Cycle DSL v0.3 + runtime (P0).

The step is ADDITIVE: cycle/0.2 stays frozen; the dialect is content-determined (a wait_for_event
step ⇔ "cycle/0.3"), which keeps the .nil printer/parser an exact bijection with no surface
version marker. The step lowers to its own IR node (V1/V2 gate the timeout and route), and at run
time the run PARKS row-backed: the ledger-event dispatch path resumes it on a matching event with
the payload bound as the step's output; the deadline routes it to `on_timeout`. Restart-safe.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from nilscript.automation.dispatch import fire_manual
from nilscript.automation.scheduler import dispatch_event, resume_due_waits
from nilscript.cycle import Cycle, compile_cycle, parse_nil, print_nil
from nilscript.kernel import ValidationContext, validate
from nilscript.kernel.executor import LocalExecutor

pytest.importorskip("fastapi", reason="the control-plane store tests need fastapi extras")

from nilscript.controlplane.store import EventStore  # noqa: E402

# ── fixtures ───────────────────────────────────────────────────────────────────────────────────


def _wait_cycle() -> dict:
    """A v0.3 cycle: send a PO, wait for the supplier's mail (matched on the PO ref), then parse —
    or escalate when a week passes."""
    return {
        "nil": "cycle/0.3",
        "cycle_id": "SupplierReply",
        "workspace": "acme",
        "metadata": {"version": "1.0.0", "owner": "Procurement"},
        "intent": {"ar": "انتظار رد المورد", "en": "Await supplier reply"},
        "trigger": {"type": "manual"},
        "variables": [{"name": "po", "expression": "context.po"}],
        "flow": {
            "entry": "AwaitReply",
            "steps": [
                {
                    "id": "AwaitReply",
                    "type": "wait_for_event",
                    "on_event": "mail.received",
                    "match": {"order_ref": "$po"},
                    "timeout_seconds": 604800,
                    "on_timeout": "Escalate",
                    "next": "Parse",
                },
                {"id": "Parse", "type": "notify", "message": {"ar": "وصل الرد", "en": "reply in"}},
                {"id": "Escalate", "type": "notify", "message": {"ar": "تصعيد", "en": "escalate"}},
            ],
        },
    }


def _ctx() -> ValidationContext:
    return ValidationContext(skills={}, read_verbs=frozenset(), workspaces={"acme": frozenset()})


# The IR plan the cycle lowers to — also used directly by the runtime tests.
WAIT_PLAN = {
    "wosool": "0.1",
    "workspace": "ws1",
    "entry": "step_1",
    "pipeline": [
        {"id": "step_1", "type": "wait_for_event", "on_event": "mail.received",
         "match": {"order_ref": "PO-9"}, "timeout_seconds": 604800, "on_timeout": "step_3",
         "next": "step_2"},
        {"id": "step_2", "type": "notify", "message": {"ar": "وصل", "en": "reply in"}},
        {"id": "step_3", "type": "notify", "message": {"ar": "تصعيد", "en": "escalate"}},
    ],
}


class _NoClient:
    def __getattr__(self, name):  # pragma: no cover - only reached on a bug
        raise AssertionError(f"wait_for_event must not call the adapter ({name})")


# ── 1. the .nil surface: exact bijection ───────────────────────────────────────────────────────


def test_round_trip_parse_of_print_is_identity():
    ast = Cycle.model_validate(_wait_cycle())
    assert parse_nil(print_nil(ast)) == ast


def test_printing_is_idempotent_for_canonical_text():
    canonical = print_nil(Cycle.model_validate(_wait_cycle()))
    assert print_nil(parse_nil(canonical)) == canonical


def test_task_grammar_snippet_parses_with_bare_dollar_ref():
    text = (
        'cycle SupplierReply triggers manual {\n'
        '  workspace "acme"\n'
        '  intent "await reply"\n'
        '  meta { version: "1.0.0"; owner: "Procurement" }\n'
        '  let po = context.po;\n'
        '  flow entry AwaitReply {\n'
        '    step AwaitReply {\n'
        '      wait_for_event {\n'
        '        on_event: "mail.received";\n'
        '        match { order_ref: $po };\n'
        '        timeout_seconds: 604800 -> route Escalate\n'
        '      }\n'
        '      next Parse\n'
        '    }\n'
        '    step Parse { notify "in" }\n'
        '    step Escalate { notify "up" }\n'
        '  }\n'
        '}\n'
    )
    cycle = parse_nil(text)
    assert cycle.nil == "cycle/0.3"  # dialect inferred from content — no surface marker needed
    step = cycle.flow.steps[0]
    assert step.type == "wait_for_event" and step.on_event == "mail.received"
    assert step.match == {"order_ref": "$po"}
    assert step.timeout_seconds == 604800 and step.on_timeout == "Escalate"
    assert step.next == "Parse"
    # canonical print round-trips the same AST (bare $po canonicalizes to the quoted string)
    assert parse_nil(print_nil(cycle)) == cycle


# ── 2. the dialect seam: 0.2 stays frozen ───────────────────────────────────────────────────────


def test_wait_for_event_is_refused_in_the_frozen_02_dialect():
    raw = _wait_cycle()
    raw["nil"] = "cycle/0.2"
    with pytest.raises(ValueError, match="cycle/0.3"):
        Cycle.model_validate(raw)


def test_03_without_a_wait_step_is_refused():
    raw = _wait_cycle()
    raw["flow"]["entry"] = "Parse"
    raw["flow"]["steps"] = raw["flow"]["steps"][1:]  # drop the wait step
    with pytest.raises(ValueError, match="cycle/0.2"):
        Cycle.model_validate(raw)


# ── 3. compile: lowering + $var match resolution ────────────────────────────────────────────────


def test_compile_lowers_to_ir_node_and_resolves_dollar_refs():
    result = compile_cycle(Cycle.model_validate(_wait_cycle()), _ctx())
    assert result.ok, result.diagnostics
    node = result.program.nodes["step_1"]
    assert node.type == "wait_for_event" and node.on_event == "mail.received"
    assert node.match == {"order_ref": "$.input.po"}  # $po → the variable's IR data reference
    assert node.timeout_seconds == 604800
    assert node.on_timeout == "step_3" and node.next == "step_2"


def test_compile_refuses_an_unknown_timeout_route():
    raw = _wait_cycle()
    raw["flow"]["steps"][0]["on_timeout"] = "Nowhere"
    result = compile_cycle(Cycle.model_validate(raw), _ctx())
    assert not result.ok
    assert any(d.code == "V1_SCHEMA" for d in result.diagnostics.diagnostics)


# ── 4. V-code refusals on the IR ────────────────────────────────────────────────────────────────


def _ir(node_overrides: dict) -> dict:
    plan = {**WAIT_PLAN, "workspace": "acme"}
    plan["pipeline"] = [dict(plan["pipeline"][0], **node_overrides)] + plan["pipeline"][1:]
    return plan


def test_missing_route_target_is_a_v2_dangling_ref():
    result = validate(_ir({"on_timeout": "step_9"}), _ctx())
    assert not result.ok
    assert any(d.code == "V2_DANGLING_REF" for d in result.diagnostics)


def test_nonpositive_timeout_is_a_v1_refusal():
    result = validate(_ir({"timeout_seconds": 0}), _ctx())
    assert not result.ok
    assert any(d.code == "V1_SCHEMA" for d in result.diagnostics)


def test_missing_timeout_route_is_a_v1_refusal():
    plan = _ir({})
    del plan["pipeline"][0]["on_timeout"]
    result = validate(plan, _ctx())
    assert not result.ok
    assert any(d.code == "V1_SCHEMA" for d in result.diagnostics)


def test_admitted_plan_validates_clean():
    assert validate(_ir({}), _ctx()).ok


# ── 5. runtime: park → event-match → resume; deadline → route; restart-safe ────────────────────


async def test_executor_parks_with_the_resolved_match():
    plan = _ir({"match": {"order_ref": "$.input.po"}})
    result = await LocalExecutor(_NoClient(), run_id="r1").execute(plan, input={"po": "PO-9"})
    assert result.completed is False
    assert result.waiting == {
        "kind": "event", "node": "step_1", "on_event": "mail.received",
        "match": {"order_ref": "PO-9"},  # the reference resolved from the run context AT PARK TIME
        "timeout_seconds": 604800,
    }


def _runner():
    async def runner(plan, *, run_id, resume=None):
        return await LocalExecutor(_NoClient(), run_id=run_id).execute(plan, resume=resume)

    return runner


def _armed_store(tmp_path, name="cp.db"):
    store = EventStore(path=str(tmp_path / name))
    store.register_automation(
        workspace="ws1", automation_id="await-reply", content_hash="h1",
        name={"ar": "انتظار", "en": "Await"}, plan=WAIT_PLAN, trigger={"type": "manual"},
        state="active",
    )
    return store


def _mail(order_ref: str, eid: str = "ev-1") -> dict:
    return {
        "nil": "0.1", "id": eid, "performative": "EVENT", "grant": "mail-adapter",
        "workspace": "ws1",
        "body": {"event": "mail.received", "verb": "mail.receive", "args": {"order_ref": order_ref}},
    }


async def test_park_then_matching_event_resumes_at_next_with_the_payload_bound(tmp_path):
    store = _armed_store(tmp_path)
    out = await fire_manual(store, workspace="ws1", automation_id="await-reply",
                            idempotency_key="fire-1", runner=_runner())
    assert out["run"]["state"] == "waiting_event"
    run_id = out["run"]["run_id"]

    # A NON-matching event (wrong order_ref) must not wake the run.
    await dispatch_event(store, _mail("PO-OTHER", "ev-0"), runner=_runner())
    assert store.get_run(run_id)["state"] == "waiting_event"

    resumed = await dispatch_event(store, _mail("PO-9"), runner=_runner())
    assert any(r.get("resumed") for r in resumed)
    final = store.get_run(run_id)
    assert final["state"] == "completed"
    out_bound = final["trace"]["context"]["step_1"]["output"]
    assert out_bound["args"] == {"order_ref": "PO-9"}  # the event payload IS the step output
    assert final["trace"]["notifications"] == [{"ar": "وصل", "en": "reply in"}]  # took `next`


async def test_deadline_passage_resumes_at_the_timeout_route(tmp_path):
    store = _armed_store(tmp_path)
    out = await fire_manual(store, workspace="ws1", automation_id="await-reply",
                            idempotency_key="fire-1", runner=_runner())
    run_id = out["run"]["run_id"]
    # The park row carries a real deadline (now + 604800s); sweep with a clock past it.
    later = datetime.now(UTC) + timedelta(seconds=604801)
    timed = await resume_due_waits(store, runner=_runner(), now=later)
    assert len(timed) == 1 and timed[0]["state"] == "completed"
    final = store.get_run(run_id)
    assert final["trace"]["notifications"] == [{"ar": "تصعيد", "en": "escalate"}]  # on_timeout ran
    # settled — the sweep (and any late event) finds nothing to resume
    assert await resume_due_waits(store, runner=_runner(), now=later) == []
    assert await dispatch_event(store, _mail("PO-9"), runner=_runner()) == []


async def test_event_resume_survives_a_process_restart(tmp_path):
    store1 = _armed_store(tmp_path)
    out = await fire_manual(store1, workspace="ws1", automation_id="await-reply",
                            idempotency_key="fire-1", runner=_runner())
    run_id = out["run"]["run_id"]
    # "Restart": a brand-new store handle over the SAME database file — the park is a row.
    store2 = EventStore(path=str(tmp_path / "cp.db"))
    resumed = await dispatch_event(store2, _mail("PO-9"), runner=_runner())
    assert any(r.get("resumed") for r in resumed)
    assert store2.get_run(run_id)["state"] == "completed"


async def test_event_waits_are_workspace_scoped(tmp_path):
    store = _armed_store(tmp_path)
    out = await fire_manual(store, workspace="ws1", automation_id="await-reply",
                            idempotency_key="fire-1", runner=_runner())
    envelope = _mail("PO-9")
    envelope["workspace"] = "ws2"  # another tenant's identical event
    await dispatch_event(store, envelope, runner=_runner())
    assert store.get_run(out["run"]["run_id"])["state"] == "waiting_event"
