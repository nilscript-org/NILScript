"""B8 auto-wrap — `wrap_cycle` (pure) + POST /capabilities/wrap (registered, idempotent).

Pins the fail-closed derivation: risk = max over DECLARED step-verb tiers with undeclared -> HIGH,
exposure ai:false, archetype omitted (never guessed), strategy = seq(approve(role: owner))
registered alongside, implemented_by {default: cycle_id}; and determinism — re-wrapping an
unchanged cycle produces the same content-hash, so the registry no-ops (no duplicate version).
"""

from __future__ import annotations

import pytest

from nilscript.capability import capability_content_hash, wrap_cycle
from nilscript.cycle import Cycle, cycle_content_hash, cycle_slug
from nilscript.strategy import strategy_content_hash, validate_strategy


def _cycle_raw() -> dict:
    return {
        "nil": "cycle/0.2",
        "cycle_id": "InvoiceChase",
        "workspace": "acme",
        "metadata": {"version": "1.0.0", "owner": "Finance Team"},
        "intent": {"ar": "متابعة الفواتير", "en": "Chase overdue invoices"},
        "trigger": {"type": "manual"},
        "context": [
            {"name": "invoice", "entity_type": "Invoice"},
            {"name": "customer", "entity_type": "Customer"},
        ],
        "flow": {
            "entry": "FindOverdue",
            "steps": [
                {
                    "id": "FindOverdue",
                    "type": "query",
                    "use": "odoo.read_overdue",
                    "with": {},
                    "next": "Remind",
                },
                {
                    "id": "Remind",
                    "type": "action",
                    "use": "whatsapp.send_message",
                    "with": {"to": "customer.phone"},
                    "next": "Done",
                },
                {"id": "Done", "type": "notify", "message": {"ar": "تم", "en": "Done"}},
            ],
        },
    }


_DECLARED = {
    "odoo.read_overdue": {"verb": "odoo.read_overdue", "type": "query", "tier": "LOW"},
    "whatsapp.send_message": {"verb": "whatsapp.send_message", "type": "write", "tier": "MEDIUM"},
}


def _wrap(lookup=None):
    table = _DECLARED if lookup is None else lookup
    return wrap_cycle(Cycle.model_validate(_cycle_raw()), table.get)


# --- the pure generator --------------------------------------------------------------------------


def test_wrapped_capability_shape():
    wrapped = _wrap()
    cap = wrapped.capability
    assert cap.capability_id == "InvoiceChase" and cap.workspace == "acme"
    assert cap.version == "0.1"
    assert cap.intent.en == "Chase overdue invoices"  # intent comes from the cycle
    assert cap.implemented_by == {"default": "InvoiceChase"}
    assert [(f.name, f.type.of) for f in cap.inputs] == [
        ("invoice", "Invoice"),
        ("customer", "Customer"),
    ]  # inputs inferred from context entities


def test_risk_is_max_of_declared_tiers():
    assert _wrap().capability.risk == "MEDIUM"  # LOW query + MEDIUM write -> MEDIUM


def test_undeclared_verb_counts_as_high_fail_closed():
    partial = {"odoo.read_overdue": _DECLARED["odoo.read_overdue"]}  # whatsapp undeclared
    assert _wrap(partial).capability.risk == "HIGH"
    assert _wrap({}).capability.risk == "HIGH"  # nothing declared at all


def test_garbage_tier_counts_as_high_fail_closed():
    garbage = dict(_DECLARED)
    garbage["whatsapp.send_message"] = {"verb": "whatsapp.send_message", "tier": "SEVERE"}
    assert _wrap(garbage).capability.risk == "HIGH"


def test_exposure_is_ai_false_and_archetype_omitted():
    cap = _wrap().capability
    assert cap.exposure.ai is False and cap.exposure.roles == ()
    assert cap.archetype is None  # never guess semantics
    assert cap.metrics is None


def test_generated_strategy_is_one_owner_gate_and_well_formed():
    wrapped = _wrap()
    strategy = wrapped.strategy
    assert strategy.strategy_id == "InvoiceChaseApproval"
    assert wrapped.capability.strategy == strategy.strategy_id  # linked by id
    assert strategy.root.form == "seq" and len(strategy.root.items) == 1
    unit = strategy.root.items[0].unit
    assert unit.by == "role" and unit.name == "owner"
    assert validate_strategy(strategy, wrapped.capability).ok  # V9-clean by construction


def test_wrap_is_deterministic_same_hashes():
    a, b = _wrap(), _wrap()
    assert capability_content_hash(a.capability) == capability_content_hash(b.capability)
    assert strategy_content_hash(a.strategy) == strategy_content_hash(b.strategy)


# --- the control-plane endpoint -------------------------------------------------------------------


pytest.importorskip("fastapi", reason="needs fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from nilscript.controlplane.app import create_app  # noqa: E402
from nilscript.controlplane.store import EventStore  # noqa: E402


def _store_with_cycle() -> EventStore:
    store = EventStore(":memory:")
    cycle = Cycle.model_validate(_cycle_raw())
    store.register_automation(
        workspace="acme",
        automation_id=cycle_slug(cycle.cycle_id),
        content_hash=cycle_content_hash(cycle),
        kind="cycle",
        name=cycle.intent.model_dump(),
        plan={},  # the lowered program is irrelevant to wrapping (source is the SSOT)
        trigger=cycle.trigger.model_dump(),
        source=cycle.model_dump(by_alias=True, mode="json"),
    )
    return store


def _client(store: EventStore, *, skeleton: dict | None):
    async def provider(_ws: str):
        return skeleton

    return TestClient(create_app(store, skeleton_provider=provider))


_SKELETON = {"verbs": sorted(_DECLARED), "verb_details": list(_DECLARED.values())}


def test_wrap_endpoint_registers_capability_and_strategy():
    client = _client(_store_with_cycle(), skeleton=_SKELETON)
    res = client.post("/capabilities/wrap", json={"workspace": "acme", "cycle_id": "InvoiceChase"})
    assert res.status_code == 200
    out = res.json()
    assert out["capability"]["body"]["risk"] == "MEDIUM"
    assert out["capability"]["body"]["exposure"]["ai"] is False
    assert out["strategy"]["strategy_id"] == "InvoiceChaseApproval"
    # the catalog now lists it
    listed = client.get("/capabilities", params={"workspace": "acme"}).json()["capabilities"]
    assert [r["capability_id"] for r in listed] == ["InvoiceChase"]


def test_wrap_endpoint_is_idempotent_no_duplicate_version():
    client = _client(_store_with_cycle(), skeleton=_SKELETON)
    first = client.post("/capabilities/wrap", json={"workspace": "acme", "cycle_id": "InvoiceChase"}).json()
    again = client.post("/capabilities/wrap", json={"workspace": "acme", "cycle_id": "InvoiceChase"}).json()
    assert first["capability"]["version"] == again["capability"]["version"] == 1
    assert first["capability"]["content_hash"] == again["capability"]["content_hash"]
    assert again["strategy"]["version"] == 1


def test_wrap_endpoint_fails_closed_without_a_reachable_adapter():
    """No skeleton means no declared metadata: every verb is undeclared, so the floor is HIGH —
    the wrap still succeeds (the catalog populates), it just never under-reports risk."""
    client = _client(_store_with_cycle(), skeleton=None)
    res = client.post("/capabilities/wrap", json={"workspace": "acme", "cycle_id": "InvoiceChase"})
    assert res.status_code == 200
    assert res.json()["capability"]["body"]["risk"] == "HIGH"


def test_wrap_endpoint_refuses_unknown_cycle_and_missing_args():
    client = _client(_store_with_cycle(), skeleton=_SKELETON)
    assert client.post("/capabilities/wrap", json={"workspace": "acme"}).status_code == 400
    missing = client.post("/capabilities/wrap", json={"workspace": "acme", "cycle_id": "Nope"})
    assert missing.status_code == 404
    other_tenant = client.post(
        "/capabilities/wrap", json={"workspace": "rival", "cycle_id": "InvoiceChase"}
    )
    assert other_tenant.status_code == 404  # workspace-pinned, fail closed
