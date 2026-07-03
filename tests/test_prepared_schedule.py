"""B7 `nil_schedule` — one-shot scheduled executions over the prepared-execution plane.

A schedule is a ROW (`scheduled_executions`), never an in-memory timer: registered via
POST /prepared/{id}/schedule (future ISO-8601 only — past timestamps refuse), swept by the same
/automations/tick clock that resumes parked runs and enforces signature deadlines, and fired
through the SAME execute path a manual commit uses. Outcomes are recorded, honest: a strategy
still unsatisfied at fire time settles the row `refused` with the NOT_APPROVED answer — never a
silent retry; a fired row never fires twice (the settle claim guard).
"""

from __future__ import annotations

import datetime as _dt

import pytest

pytest.importorskip("fastapi", reason="needs fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from nilscript.controlplane.app import create_app  # noqa: E402
from nilscript.controlplane.store import EventStore  # noqa: E402
from nilscript.kernel.executor import RunResult  # noqa: E402

WS = "ws1"


def _capability(
    *, capability_id: str = "IssueInvoice", risk: str = "HIGH", strategy: str = "CustomsTwoKey"
) -> dict:
    return {
        "nil": "capability/0.1",
        "capability_id": capability_id,
        "workspace": WS,
        "version": "2.3",
        "domain": "Finance",
        "owner_role": "Finance",
        "intent": {"en": "Issue a customer invoice", "ar": "إصدار فاتورة عميل"},
        "inputs": [
            {"name": "customer", "type": {"kind": "entity", "of": "Party"}, "required": True},
            {"name": "amount", "type": {"kind": "scalar", "of": "Money"}},
        ],
        "risk": risk,
        "strategy": strategy,
        "compensation": "CancelInvoice",
        "implemented_by": {"default": "IssueInvoiceCycle"},
    }


def _two_key() -> dict:
    return {
        "nil": "strategy/0.1",
        "strategy_id": "CustomsTwoKey",
        "workspace": WS,
        "version": 1,
        "root": {
            "form": "quorum",
            "k": 2,
            "distinct": True,
            "of": [
                {"form": "approve", "unit": {"by": "role", "name": "Finance"}},
                {"form": "approve", "unit": {"by": "role", "name": "Admin"}},
            ],
        },
    }


def _auto() -> dict:
    return {
        "nil": "strategy/0.1",
        "strategy_id": "AutoSmall",
        "workspace": WS,
        "version": 1,
        "root": {"form": "auto", "policy": "small_ops"},
    }


def _register(store: EventStore) -> None:
    from nilscript.capability import Capability, capability_content_hash
    from nilscript.strategy import Strategy, strategy_content_hash

    for cap_dict in (
        _capability(),
        _capability(capability_id="SmallRefund", risk="MEDIUM", strategy="AutoSmall"),
    ):
        cap = Capability.model_validate(cap_dict)
        store.register_capability(
            workspace=WS,
            capability_id=cap.capability_id,
            content_hash=capability_content_hash(cap),
            body=cap.model_dump(by_alias=True, mode="json"),
        )
    for strat_dict in (_two_key(), _auto()):
        strat = Strategy.model_validate(strat_dict)
        store.register_strategy(
            workspace=WS,
            strategy_id=strat.strategy_id,
            content_hash=strategy_content_hash(strat),
            body=strat.model_dump(by_alias=True, mode="json"),
        )
    store.register_automation(
        workspace=WS,
        automation_id="issueinvoicecycle",
        content_hash="h1",
        name={"en": "Issue invoice"},
        plan={"workspace": WS, "pipeline": []},
        trigger={"type": "manual"},
        state="active",
        kind="cycle",
        source={"flow": {"steps": [{"id": "Create", "type": "action", "use": "odoo.invoice_create"}]}},
    )


class _Runs:
    def __init__(self) -> None:
        self.fired: list[dict] = []

    async def __call__(self, plan, *, run_id, resume=None, input=None):
        self.fired.append({"run_id": run_id, "input": input})
        return RunResult(completed=True, context={})


@pytest.fixture()
def cp():
    store = EventStore(":memory:")
    _register(store)
    runs = _Runs()
    client = TestClient(create_app(store, secret="", runner=runs))
    return store, client, runs


def _prepare(client, capability_id: str = "IssueInvoice") -> dict:
    r = client.post(
        "/prepared",
        json={
            "workspace": WS,
            "capability_id": capability_id,
            "inputs": {"customer": "ACME", "amount": 100},
            "prepared_by": "agent-1",
        },
    )
    assert r.status_code == 200
    return r.json()["prepared"]


def _future() -> str:
    return (_dt.datetime.now(_dt.UTC) + _dt.timedelta(hours=1)).isoformat()


# ── POST /prepared/{id}/schedule — registration + refusals ───────────────────────────────────


def test_schedule_pending_card_registers_a_one_shot_row(cp):
    store, client, _ = cp
    pid = _prepare(client)["prepared_id"]
    when = _future()
    r = client.post(f"/prepared/{pid}/schedule", json={"workspace": WS, "when": when})
    assert r.status_code == 200
    sched = r.json()["scheduled"]
    assert sched["prepared_id"] == pid and sched["status"] == "pending"
    assert sched["fire_at"] == when
    assert store.get_scheduled_execution(sched["schedule_id"]) is not None


def test_schedule_same_card_same_when_is_idempotent(cp):
    _, client, _ = cp
    pid = _prepare(client)["prepared_id"]
    when = _future()
    a = client.post(f"/prepared/{pid}/schedule", json={"workspace": WS, "when": when}).json()
    b = client.post(f"/prepared/{pid}/schedule", json={"workspace": WS, "when": when}).json()
    assert a["scheduled"]["schedule_id"] == b["scheduled"]["schedule_id"]


def test_schedule_past_timestamp_refuses(cp):
    _, client, _ = cp
    pid = _prepare(client)["prepared_id"]
    past = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(minutes=5)).isoformat()
    r = client.post(f"/prepared/{pid}/schedule", json={"workspace": WS, "when": past})
    assert r.status_code == 400
    assert r.json()["refusal"]["code"] == "PAST_SCHEDULE"


def test_schedule_unparseable_when_refuses(cp):
    _, client, _ = cp
    pid = _prepare(client)["prepared_id"]
    r = client.post(f"/prepared/{pid}/schedule", json={"workspace": WS, "when": "tomorrow-ish"})
    assert r.status_code == 400
    assert r.json()["refusal"]["code"] == "INVALID_WHEN"


def test_schedule_rejected_card_refuses(cp):
    _, client, _ = cp
    pid = _prepare(client)["prepared_id"]
    signed = client.post(
        f"/prepared/{pid}/sign",
        json={"workspace": WS, "status": "rejected", "actor": "rizgi", "role": "Finance"},
    )
    assert signed.json()["status"] == "rejected"
    r = client.post(f"/prepared/{pid}/schedule", json={"workspace": WS, "when": _future()})
    assert r.status_code == 409
    assert r.json()["refusal"]["code"] == "ALREADY_DECIDED"


def test_schedule_is_workspace_pinned_fail_closed(cp):
    _, client, _ = cp
    pid = _prepare(client)["prepared_id"]
    r = client.post(f"/prepared/{pid}/schedule", json={"workspace": "other", "when": _future()})
    assert r.status_code == 404


# ── the tick sweep — same clock, same execute path ───────────────────────────────────────────


def test_tick_fires_a_due_approved_schedule_through_the_execute_path(cp):
    store, client, runs = cp
    prepared = _prepare(client, capability_id="SmallRefund")  # auto strategy → approved, uncommitted
    assert prepared["status"] == "approved"
    pid = prepared["prepared_id"]
    store.create_scheduled_execution(
        "sched-due-1", prepared_id=pid, workspace=WS, fire_at="2020-01-01T00:00:00+00:00"
    )
    out = client.post("/automations/tick").json()
    assert out["scheduled"] == [
        {
            "schedule_id": "sched-due-1",
            "prepared_id": pid,
            "status": "fired",
            "execution": out["scheduled"][0]["execution"],
        }
    ]
    assert out["scheduled"][0]["execution"]["committed"] is True
    assert len(runs.fired) == 1  # the default implementing cycle actually ran
    assert store.get_prepared(pid, WS)["status"] == "committed"
    assert store.get_scheduled_execution("sched-due-1")["status"] == "fired"


def test_tick_refuses_an_unsatisfied_strategy_honestly_never_retries(cp):
    store, client, runs = cp
    pid = _prepare(client)["prepared_id"]  # two-key, zero signatures
    store.create_scheduled_execution(
        "sched-due-2", prepared_id=pid, workspace=WS, fire_at="2020-01-01T00:00:00+00:00"
    )
    out = client.post("/automations/tick").json()
    assert out["scheduled"][0]["status"] == "refused"
    assert out["scheduled"][0]["refusal"]["code"] == "NOT_APPROVED"
    assert runs.fired == []  # nothing executed
    assert store.get_prepared(pid, WS)["status"] == "pending"  # the card is untouched
    row = store.get_scheduled_execution("sched-due-2")
    assert row["status"] == "refused" and row["result"]["code"] == "NOT_APPROVED"
    # settled = claimed: the next tick does NOT retry the refused schedule
    assert client.post("/automations/tick").json()["scheduled"] == []


def test_tick_fires_each_schedule_exactly_once(cp):
    store, client, _ = cp
    pid = _prepare(client, capability_id="SmallRefund")["prepared_id"]
    store.create_scheduled_execution(
        "sched-due-3", prepared_id=pid, workspace=WS, fire_at="2020-01-01T00:00:00+00:00"
    )
    first = client.post("/automations/tick").json()
    assert first["scheduled"][0]["status"] == "fired"
    assert client.post("/automations/tick").json()["scheduled"] == []


def test_future_schedule_does_not_fire_early(cp):
    store, client, runs = cp
    pid = _prepare(client, capability_id="SmallRefund")["prepared_id"]
    client.post(f"/prepared/{pid}/schedule", json={"workspace": WS, "when": _future()})
    out = client.post("/automations/tick").json()
    assert out["scheduled"] == [] and runs.fired == []
    assert store.get_prepared(pid, WS)["status"] == "approved"  # still waiting for its moment
