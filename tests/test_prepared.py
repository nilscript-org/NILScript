"""B2 — PreparedExecution + the deterministic Permission Card (Gate M3, end to end).

The gate's acceptance, over the real endpoints: a two-key card collects 2 DISTINCT signatures
and only then commits (by firing the default implementing cycle — the ONLY effect path); the
preparer's signature refuses with SOD_VIOLATION; a material edit inside `modifiable` voids the
collected signatures (superseded) and re-holds; edits outside `modifiable` refuse; the card
JSON is BYTE-deterministic (same registry state + same inputs ⇒ identical bytes — timestamps
and ids live in the envelope, never the body); a unit timeout escalates/rejects via the same
/automations/tick sweep that resumes parked runs; inputs that miss the typed contract refuse
with the offending fields listed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="needs fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from nilscript.controlplane import prepared as prepared_cards  # noqa: E402
from nilscript.controlplane.app import create_app  # noqa: E402
from nilscript.controlplane.store import EventStore  # noqa: E402
from nilscript.kernel.executor import RunResult  # noqa: E402

WS = "ws1"


def _capability(*, risk: str = "HIGH", strategy: str = "CustomsTwoKey") -> dict:
    return {
        "nil": "capability/0.1",
        "capability_id": "IssueInvoice",
        "workspace": WS,
        "version": "2.3",
        "domain": "Finance",
        "owner_role": "Finance",
        "intent": {"en": "Issue a customer invoice", "ar": "إصدار فاتورة عميل"},
        "inputs": [
            {"name": "customer", "type": {"kind": "entity", "of": "Party"}, "required": True},
            {"name": "amount", "type": {"kind": "scalar", "of": "Money"}},
            {"name": "items", "type": {"kind": "list", "of": "OrderLine"}},
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


def _register(store: EventStore, *, capability: dict | None = None,
              strategy: dict | None = None) -> None:
    """Pin identical registry state: capability + strategy + the default implementing cycle
    (an ACTIVE automation whose source steps name their adapters) + one registered adapter."""
    from nilscript.capability import Capability, capability_content_hash
    from nilscript.strategy import Strategy, strategy_content_hash

    cap = Capability.model_validate(capability or _capability())
    store.register_capability(
        workspace=WS, capability_id=cap.capability_id,
        content_hash=capability_content_hash(cap),
        body=cap.model_dump(by_alias=True, mode="json"),
    )
    strat = Strategy.model_validate(strategy or _two_key())
    store.register_strategy(
        workspace=WS, strategy_id=strat.strategy_id,
        content_hash=strategy_content_hash(strat),
        body=strat.model_dump(by_alias=True, mode="json"),
    )
    store.register_automation(
        workspace=WS, automation_id="issueinvoicecycle", content_hash="h1",
        name={"en": "Issue invoice"}, plan={"workspace": WS, "pipeline": []},
        trigger={"type": "manual"}, state="active", kind="cycle",
        source={"flow": {"steps": [
            {"id": "Create", "type": "action", "use": "odoo.invoice_create"},
            {"id": "Record", "type": "action", "use": "daftra.record_entry"},
        ]}},
    )
    store.register_adapter(WS, "odoo", label="Odoo ERP", url="https://odoo/nil", system="odoo")


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


def _prepare(client, inputs=None, prepared_by="agent-1"):
    return client.post("/prepared", json={
        "workspace": WS, "capability_id": "IssueInvoice",
        "inputs": inputs if inputs is not None else {"customer": "ACME", "amount": 18400},
        "prepared_by": prepared_by,
    })


# ── prepare: typed-contract refusals + the deterministic card ─────────────────────────────────


def test_prepare_unknown_capability_refuses(cp):
    _, client, _ = cp
    r = client.post("/prepared", json={"workspace": WS, "capability_id": "Nope",
                                       "inputs": {}, "prepared_by": "a"})
    assert r.status_code == 400 and r.json()["refusal"]["code"] == "UNKNOWN_CAPABILITY"


def test_prepare_contract_refusal_lists_offending_fields(cp):
    _, client, _ = cp
    r = client.post("/prepared", json={
        "workspace": WS, "capability_id": "IssueInvoice", "prepared_by": "a",
        "inputs": {"amount": ["not", "a", "scalar"], "ghost": 1},  # and customer missing
    })
    assert r.status_code == 400
    refusal = r.json()["refusal"]
    assert refusal["code"] == "INPUT_CONTRACT"
    assert refusal["missing"] == ["customer"]
    assert refusal["wrong_type"] == ["amount"]
    assert refusal["unknown"] == ["ghost"]


def test_prepare_dangling_strategy_refuses(cp):
    store, client, _ = cp
    cap = _capability(strategy="GhostStrategy")
    _register(store, capability=cap)  # re-register with a strategy id nothing provides
    r = client.post("/prepared", json={"workspace": WS, "capability_id": "IssueInvoice",
                                       "inputs": {"customer": "ACME"}, "prepared_by": "a"})
    assert r.status_code == 400 and r.json()["refusal"]["code"] == "UNKNOWN_STRATEGY"


def test_prepare_without_preparer_refuses_fail_closed(cp):
    _, client, _ = cp
    r = _prepare(client, prepared_by="")
    assert r.status_code == 400 and r.json()["refusal"]["code"] == "PREPARER_REQUIRED"


def test_card_assembles_every_field_from_deterministic_sources(cp):
    _, client, _ = cp
    card = _prepare(client).json()["prepared"]["card"]
    assert card["capability"]["id"] == "IssueInvoice"
    assert card["capability"]["version"] == "2.3"
    assert len(card["capability"]["content_hash"]) == 64
    assert card["inputs"] == {"customer": "ACME", "amount": 18400}
    assert card["modifiable"] == ["amount", "items"]  # required inputs are LOCKED
    assert card["risk"] == "HIGH"
    assert card["reversibility"] == "REVERSIBLE"
    assert card["compensation"] == {"via": "CancelInvoice", "covered": True}
    # Affected systems: the implementing cycle's step adapters, labelled via the registry.
    assert card["affected_systems"] == ["Odoo ERP", "daftra"]
    assert card["prepared_by"] == "agent-1"
    state = card["strategy"]["state"]
    assert state["status"] == "pending" and len(state["pending"]) == 2
    assert state["stages"][0]["k"] == 2 and state["stages"][0]["distinct"] is True


def test_card_json_is_byte_deterministic_across_stores():
    """Same registry state + same inputs ⇒ IDENTICAL card bytes — timestamps, prepared ids and
    signature rows live in the envelope, never inside the hashed body."""
    def one_card() -> dict:
        store = EventStore(":memory:")
        _register(store)
        client = TestClient(create_app(store, secret="", runner=_Runs()))
        return _prepare(client).json()["prepared"]

    a, b = one_card(), one_card()
    assert a["prepared_id"] != b["prepared_id"]  # distinct subjects…
    assert prepared_cards.canonical_card(a["card"]) == prepared_cards.canonical_card(b["card"])
    assert a["card_hash"] == b["card_hash"]  # …one deterministic card


def test_get_card_is_workspace_pinned_fail_closed(cp):
    _, client, _ = cp
    pid = _prepare(client).json()["prepared"]["prepared_id"]
    assert client.get(f"/prepared/{pid}", params={"workspace": "rival"}).status_code == 404
    assert client.get(f"/prepared/{pid}").status_code == 400  # no workspace, no card
    assert client.get(f"/prepared/{pid}", params={"workspace": WS}).status_code == 200


# ── the two-key gate: 2 distinct signatures, then (and only then) the commit ─────────────────


def test_two_key_card_commits_only_at_two_distinct_signatures(cp):
    _, client, runs = cp
    pid = _prepare(client).json()["prepared"]["prepared_id"]

    # The preparer cannot sign their own card — visibly and structurally.
    r = client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "agent-1", "role": "Finance", "status": "approved"})
    assert r.status_code == 403 and r.json()["refusal"]["code"] == "SOD_VIOLATION"

    # First key: 1 of 2 — NO effect fires.
    r = client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "rizgi", "role": "Finance", "status": "approved"})
    assert r.json()["status"] == "pending" and runs.fired == []

    # Execute before the quorum is satisfied refuses — the strategy is the only way forward.
    r = client.post(f"/prepared/{pid}/execute", json={"workspace": WS})
    assert r.status_code == 409 and r.json()["refusal"]["code"] == "NOT_APPROVED"
    assert runs.fired == []

    # The same actor cannot supply the second key.
    r = client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "rizgi", "role": "Admin", "status": "approved"})
    assert r.status_code == 409 and r.json()["refusal"]["code"] == "DUPLICATE_SIGNATURE"

    # Second DISTINCT key → approved → the commit fires the implementing cycle, inputs bound.
    r = client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "admin-b", "role": "Admin", "status": "approved"})
    body = r.json()
    assert body["status"] == "approved" and body["execution"]["committed"] is True
    assert len(runs.fired) == 1
    assert runs.fired[0]["input"] == {"customer": "ACME", "amount": 18400}
    assert runs.fired[0]["run_id"] == f"issueinvoicecycle:v1:prep:{pid}"  # idempotent key
    card = client.get(f"/prepared/{pid}", params={"workspace": WS}).json()
    assert card["status"] == "committed"
    assert card["card"]["strategy"]["state"]["signed"] == ["rizgi", "admin-b"]

    # A late signature refuses — the subject is settled.
    r = client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "late", "role": "Finance", "status": "approved"})
    assert r.status_code == 409 and r.json()["refusal"]["code"] == "ALREADY_DECIDED"


def test_rejection_by_one_key_rejects_the_card(cp):
    _, client, runs = cp
    pid = _prepare(client).json()["prepared"]["prepared_id"]
    client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "rizgi", "role": "Finance", "status": "approved"})
    r = client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "admin-b", "role": "Admin", "status": "rejected"})
    assert r.json()["status"] == "rejected" and runs.fired == []
    assert client.get(f"/prepared/{pid}", params={"workspace": WS}).json()["status"] == "rejected"


# ── material edits: void collected signatures, re-hold ───────────────────────────────────────


def test_material_edit_voids_collected_signatures_and_reholds(cp):
    _, client, runs = cp
    pid = _prepare(client).json()["prepared"]["prepared_id"]
    client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "rizgi", "role": "Finance", "status": "approved"})

    # The second signer amends a MODIFIABLE field → rizgi's signature is VOIDED, the units
    # re-hold, and the editor's signature lands on the EDITED card: 1 of 2 again, no commit.
    r = client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "admin-b", "role": "Admin", "status": "approved",
        "edits": {"amount": 21000}})
    body = r.json()
    assert body["superseded"] == 1 and body["status"] == "pending"
    assert runs.fired == []
    card = body["prepared"]["card"]
    assert card["inputs"]["amount"] == 21000  # the card now shows the amended subject
    assert card["strategy"]["state"]["signed"] == ["admin-b"]
    voided = [s for s in body["prepared"]["signatures"] if s["status"] == "superseded"]
    assert [s["actor"] for s in voided] == ["rizgi"]  # the void is an explicit audit row

    # Re-collect on the edited card → now it commits, with the EDITED inputs bound.
    r = client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "rizgi", "role": "Finance", "status": "approved"})
    assert r.json()["status"] == "approved" and len(runs.fired) == 1
    assert runs.fired[0]["input"]["amount"] == 21000


def test_edit_outside_modifiable_refuses(cp):
    _, client, runs = cp
    pid = _prepare(client).json()["prepared"]["prepared_id"]
    r = client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "admin-b", "role": "Admin", "status": "approved",
        "edits": {"customer": "EVIL CORP"}})  # `customer` is required → LOCKED
    assert r.status_code == 409
    assert r.json()["refusal"]["code"] == "FIELD_NOT_MODIFIABLE"
    assert r.json()["refusal"]["fields"] == ["customer"]
    assert runs.fired == []


def test_identical_edits_are_not_material(cp):
    _, client, _ = cp
    pid = _prepare(client).json()["prepared"]["prepared_id"]
    client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "rizgi", "role": "Finance", "status": "approved"})
    # "Edits" that change nothing supersede nothing — a plain signature.
    r = client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "admin-b", "role": "Admin", "status": "approved",
        "edits": {"amount": 18400}})
    assert r.json()["superseded"] == 0 and r.json()["status"] == "approved"


# ── auto + conditional: prepare → execute (no signatures) ─────────────────────────────────────


def _auto_conditional() -> dict:
    return {
        "nil": "strategy/0.1", "strategy_id": "CustomsTwoKey", "workspace": WS, "version": 1,
        "root": {
            "form": "conditional",
            "when": "$.input.amount < 5000",
            "then": {"form": "auto", "policy": "small_ops"},
            "else": {"form": "approve", "unit": {"by": "role", "name": "Finance"}},
        },
    }


def test_auto_branch_prepares_approved_and_execute_commits():
    store = EventStore(":memory:")
    _register(store, capability=_capability(risk="MEDIUM"), strategy=_auto_conditional())
    runs = _Runs()
    client = TestClient(create_app(store, secret="", runner=runs))
    out = _prepare(client, inputs={"customer": "ACME", "amount": 1200}).json()["prepared"]
    assert out["status"] == "approved"  # routed to auto — approved with NO human gate…
    state = out["card"]["strategy"]["state"]
    assert state["branch"] == "then"
    assert state["signed"] == ["policy:small_ops"]  # …and the decision row names the policy
    assert runs.fired == []  # prepare NEVER fires the effect
    r = client.post(f"/prepared/{out['prepared_id']}/execute", json={"workspace": WS})
    assert r.json()["ok"] is True and len(runs.fired) == 1
    # A second execute refuses — committed once, exactly.
    r = client.post(f"/prepared/{out['prepared_id']}/execute", json={"workspace": WS})
    assert r.status_code == 409 and r.json()["refusal"]["code"] == "ALREADY_COMMITTED"
    assert len(runs.fired) == 1


def test_conditional_routes_large_amounts_to_the_human_gate():
    store = EventStore(":memory:")
    _register(store, capability=_capability(risk="MEDIUM"), strategy=_auto_conditional())
    client = TestClient(create_app(store, secret="", runner=_Runs()))
    out = _prepare(client, inputs={"customer": "ACME", "amount": 9000}).json()["prepared"]
    assert out["status"] == "pending"
    state = out["card"]["strategy"]["state"]
    assert state["branch"] == "else"
    assert [u["name"] for u in state["pending"]] == ["Finance"]


# ── timeouts: enforced by the SAME /automations/tick sweep as parked runs ─────────────────────


def _timed(route: dict) -> dict:
    return {
        "nil": "strategy/0.1", "strategy_id": "CustomsTwoKey", "workspace": WS, "version": 1,
        "root": {"form": "approve",
                 "unit": {"by": "role", "name": "Manager",
                          "timeout": {"after": "PT0S", "then": route}}},
    }


def test_timeout_escalates_via_the_tick_sweep():
    store = EventStore(":memory:")
    _register(store, strategy=_timed({"kind": "escalate", "to": "Director"}))
    # The active cycle automation would fire on the tick's schedule scan — it is manual, so no.
    client = TestClient(create_app(store, secret="", runner=_Runs()))
    pid = _prepare(client).json()["prepared"]["prepared_id"]
    tick = client.post("/automations/tick").json()
    assert tick["signatures"] == [
        {"execution_id": pid, "unit_idx": 0, "action": "escalated", "to": "Director"}]
    card = client.get(f"/prepared/{pid}", params={"workspace": WS}).json()
    assert card["status"] == "pending"
    assert [u["name"] for u in card["card"]["strategy"]["state"]["pending"]] == ["Director"]
    # The Director's signature approves the escalated card.
    r = client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "dir", "role": "Director", "status": "approved"})
    assert r.json()["status"] == "approved"


def test_timeout_reject_route_rejects_the_card_via_the_tick_sweep():
    store = EventStore(":memory:")
    _register(store, strategy=_timed({"kind": "reject"}))
    client = TestClient(create_app(store, secret="", runner=_Runs()))
    pid = _prepare(client).json()["prepared"]["prepared_id"]
    tick = client.post("/automations/tick").json()
    assert tick["signatures"][0]["action"] == "rejected"
    assert client.get(f"/prepared/{pid}", params={"workspace": WS}).json()["status"] == "rejected"


# ── list + rejection-reason audit (C4 live-mode follow-up) ────────────────────────────────────


def test_list_prepared_is_workspace_pinned_and_status_filterable(cp):
    _, client, _ = cp
    a = _prepare(client).json()["prepared"]["prepared_id"]
    b = _prepare(client, inputs={"customer": "Beta"}).json()["prepared"]["prepared_id"]
    client.post(f"/prepared/{a}/sign", json={"workspace": WS, "actor": "fin-1",
                                             "role": "Finance", "status": "rejected",
                                             "reason": "wrong customer"})

    # The Decisions feed: newest first, envelopes with cards.
    r = client.get("/prepared", params={"workspace": WS})
    assert r.status_code == 200
    ids = [p["prepared_id"] for p in r.json()["prepared"]]
    assert set(ids) == {a, b}
    assert all("card" in p and "card_hash" in p for p in r.json()["prepared"])

    # Status filter narrows; a foreign workspace sees NOTHING (fail closed).
    pending = client.get("/prepared", params={"workspace": WS, "status": "pending"}).json()
    assert [p["prepared_id"] for p in pending["prepared"]] == [b]
    assert client.get("/prepared", params={"workspace": "ws-other"}).json() == {"prepared": []}
    assert client.get("/prepared").status_code == 400  # no workspace, no feed


def test_rejection_reason_is_persisted_and_surfaced(cp):
    _, client, _ = cp
    pid = _prepare(client).json()["prepared"]["prepared_id"]
    r = client.post(f"/prepared/{pid}/sign", json={"workspace": WS, "actor": "fin-1",
                                                   "role": "Finance", "status": "rejected",
                                                   "reason": "amount disputed"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    card = client.get(f"/prepared/{pid}", params={"workspace": WS}).json()
    assert card["status"] == "rejected"
    assert card["reason"] == "amount disputed"
