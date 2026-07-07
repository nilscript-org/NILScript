"""Capability + strategy registries (plan B1) — store disciplines and control-plane endpoints.

Pins the automation-registry disciplines on the new tables: idempotent register on the same
content-hash, supersede (never edit) on a new hash, workspace-pinned fail-closed reads, and the
draft -> published lifecycle. API tests cover the GET/POST trios, tenant isolation, auth gating,
and the V9 admission gate on strategy registration (a failing strategy is refused, never stored).
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="needs fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from nilscript.capability import Capability, capability_content_hash  # noqa: E402
from nilscript.controlplane.app import create_app  # noqa: E402
from nilscript.controlplane.store import EventStore  # noqa: E402
from nilscript.strategy import Strategy, strategy_content_hash  # noqa: E402


def _store() -> EventStore:
    return EventStore(":memory:")


def _capability_raw(*, workspace: str = "acme", version: str = "1.0", risk: str = "MEDIUM") -> dict:
    return {
        "nil": "capability/0.1",
        "capability_id": "IssueInvoice",
        "workspace": workspace,
        "version": version,
        "domain": "Finance",
        "owner_role": "Finance",
        "intent": {"ar": "إصدار فاتورة", "en": "Issue an invoice"},
        "risk": risk,
        "strategy": "FinanceThreshold",
        "implemented_by": {"default": "IssueInvoiceCycle"},
    }


def _strategy_raw(*, workspace: str = "acme", k: int = 2) -> dict:
    return {
        "nil": "strategy/0.1",
        "strategy_id": "CustomsTwoKey",
        "workspace": workspace,
        "version": 1,
        "root": {
            "form": "quorum",
            "k": k,
            "distinct": True,
            "of": [
                {"form": "approve", "unit": {"by": "role", "name": "Finance"}},
                {"form": "approve", "unit": {"by": "role", "name": "Admin"}},
            ],
        },
    }


def _register_cap(store: EventStore, raw: dict) -> dict:
    capability = Capability.model_validate(raw)
    return store.register_capability(
        workspace=capability.workspace,
        capability_id=capability.capability_id,
        content_hash=capability_content_hash(capability),
        body=capability.model_dump(by_alias=True, mode="json"),
    )


# --- store disciplines --------------------------------------------------------------------------


def test_register_lands_as_draft_version_1():
    rec = _register_cap(_store(), _capability_raw())
    assert rec["version"] == 1 and rec["state"] == "draft"
    assert rec["body"]["capability_id"] == "IssueInvoice"
    assert len(rec["content_hash"]) == 64


def test_same_hash_register_is_idempotent_no_new_version():
    s = _store()
    first = _register_cap(s, _capability_raw())
    again = _register_cap(s, _capability_raw())
    assert again["version"] == first["version"] == 1
    assert again["content_hash"] == first["content_hash"]
    assert len(s.list_capabilities("acme")) == 1


def test_new_hash_supersedes_never_edits():
    s = _store()
    _register_cap(s, _capability_raw())
    v2 = _register_cap(s, _capability_raw(version="1.1"))
    assert v2["version"] == 2 and v2["superseded_by"] is None
    v1 = s.get_capability("acme", "IssueInvoice", 1)
    assert v1["superseded_by"] == 2 and v1["state"] == "deprecated"  # archived, not rewritten
    assert s.get_capability("acme", "IssueInvoice")["version"] == 2  # latest wins


def test_reads_are_workspace_pinned_fail_closed():
    s = _store()
    _register_cap(s, _capability_raw(workspace="acme"))
    assert s.get_capability("rival", "IssueInvoice") is None
    assert s.list_capabilities("rival") == []
    assert s.set_capability_state("rival", "IssueInvoice", 1, "published") is False


def test_register_without_workspace_refuses():
    with pytest.raises(ValueError, match="workspace"):
        _store().register_capability(
            workspace="", capability_id="X", content_hash="0" * 64, body={}
        )


def test_publish_lifecycle():
    s = _store()
    _register_cap(s, _capability_raw())
    assert s.set_capability_state("acme", "IssueInvoice", 1, "published") is True
    assert s.get_capability("acme", "IssueInvoice")["state"] == "published"
    with pytest.raises(ValueError):
        s.set_capability_state("acme", "IssueInvoice", 1, "armed")  # not a lifecycle state


def test_strategy_registry_shares_the_disciplines():
    s = _store()
    strategy = Strategy.model_validate(_strategy_raw())
    kwargs = dict(
        workspace="acme",
        strategy_id="CustomsTwoKey",
        content_hash=strategy_content_hash(strategy),
        body=strategy.model_dump(by_alias=True, mode="json"),
    )
    first = s.register_strategy(**kwargs)
    assert first["version"] == 1 and first["state"] == "draft"
    assert s.register_strategy(**kwargs)["version"] == 1  # idempotent
    changed = Strategy.model_validate(_strategy_raw(k=1))
    v2 = s.register_strategy(
        workspace="acme",
        strategy_id="CustomsTwoKey",
        content_hash=strategy_content_hash(changed),
        body=changed.model_dump(by_alias=True, mode="json"),
    )
    assert v2["version"] == 2
    assert s.get_strategy("acme", "CustomsTwoKey", 1)["superseded_by"] == 2
    assert s.get_strategy("rival", "CustomsTwoKey") is None  # tenant-pinned


# --- endpoints ----------------------------------------------------------------------------------


def _client(store: EventStore | None = None, *, registry_token: str | None = None) -> TestClient:
    return TestClient(create_app(store or _store(), registry_token=registry_token))


def test_capability_endpoint_register_list_get_publish():
    c = _client()
    res = c.post("/capabilities", json={"capability": _capability_raw()})
    assert res.status_code == 200 and res.json()["ok"] is True
    assert res.json()["definition"]["state"] == "draft"

    listed = c.get("/capabilities", params={"workspace": "acme"}).json()["capabilities"]
    assert [r["capability_id"] for r in listed] == ["IssueInvoice"]

    got = c.get("/capabilities/IssueInvoice", params={"workspace": "acme"}).json()
    assert got["version"] == 1 and got["body"]["risk"] == "MEDIUM"

    pub = c.post("/capabilities/IssueInvoice/publish", json={"workspace": "acme"})
    assert pub.status_code == 200 and pub.json()["definition"]["state"] == "published"


def test_capability_endpoint_accepts_nil_text():
    from nilscript.capability import print_capability_nil

    text = print_capability_nil(Capability.model_validate(_capability_raw()))
    c = _client()
    res = c.post("/capabilities", json={"text": text})
    assert res.status_code == 200
    assert res.json()["definition"]["body"]["capability_id"] == "IssueInvoice"


def test_capability_endpoint_hash_idempotency_and_supersede():
    c = _client()
    assert c.post("/capabilities", json={"capability": _capability_raw()}).json()["definition"]["version"] == 1
    assert c.post("/capabilities", json={"capability": _capability_raw()}).json()["definition"]["version"] == 1
    v2 = c.post("/capabilities", json={"capability": _capability_raw(risk="HIGH")}).json()
    assert v2["definition"]["version"] == 2
    v1 = c.get("/capabilities/IssueInvoice", params={"workspace": "acme", "version": 1}).json()
    assert v1["superseded_by"] == 2 and v1["state"] == "deprecated"


def test_capability_endpoints_are_tenant_isolated_and_fail_closed():
    c = _client()
    c.post("/capabilities", json={"capability": _capability_raw(workspace="acme")})
    assert c.get("/capabilities").status_code == 400  # no workspace -> refused, not global
    assert c.get("/capabilities", params={"workspace": "rival"}).json()["capabilities"] == []
    assert c.get("/capabilities/IssueInvoice", params={"workspace": "rival"}).status_code == 404
    assert c.post("/capabilities/IssueInvoice/publish", json={"workspace": "rival"}).status_code == 404


def test_capability_register_refuses_invalid_shape():
    c = _client()
    bad = _capability_raw()
    bad["implemented_by"] = {"manual": "SomeCycle"}  # no "default"
    res = c.post("/capabilities", json={"capability": bad})
    assert res.status_code == 400 and "invalid capability" in res.json()["error"]


def test_registry_writes_are_auth_gated():
    c = _client(registry_token="s3cret")
    assert c.post("/capabilities", json={"capability": _capability_raw()}).status_code == 401
    ok = c.post(
        "/capabilities",
        json={"capability": _capability_raw()},
        headers={"Authorization": "Bearer s3cret"},
    )
    assert ok.status_code == 200
    assert c.post("/strategies", json={"strategy": _strategy_raw()}).status_code == 401


def test_strategy_endpoint_trio_and_v9_admission_gate():
    c = _client()
    res = c.post("/strategies", json={"strategy": _strategy_raw()})
    assert res.status_code == 200 and res.json()["definition"]["version"] == 1

    listed = c.get("/strategies", params={"workspace": "acme"}).json()["strategies"]
    assert [r["strategy_id"] for r in listed] == ["CustomsTwoKey"]
    got = c.get("/strategies/CustomsTwoKey", params={"workspace": "acme"}).json()
    assert got["body"]["root"]["k"] == 2

    pub = c.post("/strategies/CustomsTwoKey/publish", json={"workspace": "acme"})
    assert pub.json()["definition"]["state"] == "published"

    # V9 admission: an unsatisfiable quorum is refused with structured diagnostics, never stored
    bad = _strategy_raw(k=3)
    refused = c.post("/strategies", json={"strategy": bad})
    assert refused.status_code == 400
    codes = [d["code"] for d in refused.json()["refusal"]]
    assert codes == ["V9_QUORUM_UNSATISFIABLE"]


def test_strategy_endpoint_reserved_form_refusal_passes_through():
    c = _client()
    text = 'strategy X v1 {\n  workspace "acme"\n  par(approve(role: A))\n}\n'
    res = c.post("/strategies", json={"text": text})
    assert res.status_code == 400
    assert "V9_UNSUPPORTED_FORM" in res.json()["error"]
    assert res.json()["line"] == 3


# --- Wave 4 §14.2b: registry-gate on the register endpoint (DAG the model can't catch) -----------


def _dep_cap(cid: str, *, requires=(), workspace: str = "acme", version: str = "1.0") -> dict:
    return {
        "nil": "capability/0.1",
        "capability_id": cid,
        "workspace": workspace,
        "version": version,
        "domain": "Finance",
        "owner_role": "Finance",
        "intent": {"ar": "س", "en": "x"},
        "risk": "MEDIUM",
        "strategy": "FinanceThreshold",
        "requires": list(requires),
        "implemented_by": {"default": "GenericCycle"},
    }


def test_registry_gate_rejects_a_dependency_cycle():
    c = _client()
    # A requires B — fine while B is unknown (the edge only forms once B exists).
    assert c.post("/capabilities", json={"capability": _dep_cap("CapA", requires=["CapB"])}).status_code == 200
    # Registering B (requires A) closes the loop A→B→A — the gate refuses with a witness.
    res = c.post("/capabilities", json={"capability": _dep_cap("CapB", requires=["CapA"])})
    assert res.status_code == 409
    body = res.json()
    assert body["error"] == "registry invariant violation"
    assert any(v["code"] == "dependency_cycle" for v in body["violations"])
    # And B was NOT stored — the registry stays acyclic.
    assert c.get("/capabilities", params={"workspace": "acme"}).json()["capabilities"]  # A only
    assert all(cap["capability_id"] != "CapB"
               for cap in c.get("/capabilities", params={"workspace": "acme"}).json()["capabilities"])


def test_registry_gate_allows_acyclic_dependencies():
    c = _client()
    assert c.post("/capabilities", json={"capability": _dep_cap("CapBase")}).status_code == 200
    assert c.post("/capabilities", json={"capability": _dep_cap("CapDependent", requires=["CapBase"])}).status_code == 200


def test_registry_gate_allows_supersede_of_same_id():
    # Re-registering an id with new content must NOT self-collide (candidate replaces its own version).
    c = _client()
    assert c.post("/capabilities", json={"capability": _dep_cap("CapX")}).status_code == 200
    assert c.post("/capabilities", json={"capability": _dep_cap("CapX", version="1.1")}).status_code == 200
