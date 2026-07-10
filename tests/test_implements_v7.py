"""`implements` clause + V7 conformance (CAPABILITY-SHIFT plan A3 + A4-V7, Gate M4).

The clause is ADDITIVE on the one v0.3 seam: `implements` alone forces the cycle/0.3 dialect
(content-determined both ways, no surface marker), the .nil printer/parser stay an exact
bijection, and V7 — a pure validator sharing the V1–V6 ValidationResult shape — refuses a cycle
that cannot honour its declared capability contract: unproducible required inputs, unbound
outputs, a weakened risk floor (I3), or missing compensation coverage. The control plane runs V7
on /cycles/register with a WORKSPACE-PINNED registry lookup; a missing target refuses
(V7_UNKNOWN_CAPABILITY) and stores nothing.
"""

from __future__ import annotations

import pytest

from nilscript.capability import Capability, validate_implements
from nilscript.cycle import Cycle, parse_nil, print_nil

# ── fixtures ───────────────────────────────────────────────────────────────────────────────────


def _cycle_raw(**over) -> dict:
    """An implementing cycle: create an invoice for `customer`, binding the `invoice` output."""
    raw = {
        "nil": "cycle/0.3",
        "cycle_id": "IssueInvoiceCycle",
        "implements": {"capability_id": "IssueInvoice", "version": "2.3"},
        "workspace": "acme",
        "metadata": {"version": "1.0.0", "owner": "Finance"},
        "intent": {"ar": "إصدار فاتورة", "en": "Issue an invoice"},
        "trigger": {"type": "manual"},
        "context": [{"name": "customer", "entity_type": "Party"}],
        "variables": [{"name": "amount", "expression": "context.amount"}],
        "flow": {
            "entry": "Create",
            "steps": [
                {
                    "id": "Create",
                    "type": "action",
                    "use": "billing.create_invoice",
                    "with": {"client": "customer.id"},
                    "output": "invoice",
                },
            ],
        },
    }
    raw.update(over)
    return raw


def _capability_raw(**over) -> dict:
    raw = {
        "nil": "capability/0.1",
        "capability_id": "IssueInvoice",
        "workspace": "acme",
        "version": "2.3",
        "domain": "Finance",
        "owner_role": "Finance",
        "intent": {"ar": "إصدار فاتورة", "en": "Issue an invoice"},
        "inputs": [
            {"name": "customer", "type": {"kind": "entity", "of": "Party"}, "required": True},
            {"name": "amount", "type": {"kind": "scalar", "of": "Money"}, "required": True},
        ],
        "outputs": [{"name": "invoice", "type": {"kind": "entity", "of": "Invoice"}}],
        "risk": "MEDIUM",
        "strategy": "FinanceThreshold",
        "implemented_by": {"default": "IssueInvoiceCycle"},
    }
    raw.update(over)
    return raw


def _cycle(**over) -> Cycle:
    return Cycle.model_validate(_cycle_raw(**over))


def _capability(**over) -> Capability:
    return Capability.model_validate(_capability_raw(**over))


def _codes(result) -> list[str]:
    return [d.code for d in result.diagnostics]


# ── 1. grammar: parse/print bijection ──────────────────────────────────────────────────────────


def test_implements_clause_parses_from_nil_text():
    text = (
        "cycle IssueInvoiceCycle implements IssueInvoice@2.3 triggers manual {\n"
        '  workspace "acme"\n'
        '  intent "invoice"\n'
        '  meta { version: "1.0.0"; owner: "Finance" }\n'
        "  flow entry Create {\n"
        "    step Create { use billing.create_invoice { client: \"c1\" } output invoice }\n"
        "  }\n"
        "}\n"
    )
    cycle = parse_nil(text)
    assert cycle.nil == "cycle/0.3"  # implements alone forces the v0.3 dialect
    assert cycle.implements is not None
    assert cycle.implements.capability_id == "IssueInvoice"
    assert cycle.implements.version == "2.3"


def test_round_trip_parse_of_print_is_identity():
    ast = _cycle()
    assert parse_nil(print_nil(ast)) == ast


def test_printing_is_idempotent_for_canonical_text():
    canonical = print_nil(_cycle())
    assert print_nil(parse_nil(canonical)) == canonical
    assert "implements IssueInvoice@2.3" in canonical.splitlines()[0]


def test_patch_version_round_trips():
    ast = _cycle(implements={"capability_id": "IssueInvoice", "version": "2.3.1"})
    assert parse_nil(print_nil(ast)) == ast


# ── 2. the dialect seam: implements is a v0.3 construct ────────────────────────────────────────


def test_implements_is_refused_in_the_frozen_02_dialect():
    with pytest.raises(ValueError, match="cycle/0.3"):
        _cycle(nil="cycle/0.2")


def test_03_without_any_v03_construct_is_refused():
    with pytest.raises(ValueError, match="cycle/0.2"):
        _cycle(implements=None)


def test_02_cycle_without_implements_still_validates():
    cycle = _cycle(nil="cycle/0.2", implements=None)
    assert cycle.nil == "cycle/0.2" and cycle.implements is None


# ── 3. V7: unknown capability ───────────────────────────────────────────────────────────────────


def test_missing_registry_target_refuses_v7_unknown_capability():
    result = validate_implements(_cycle(), None)
    assert not result.ok
    assert _codes(result) == ["V7_UNKNOWN_CAPABILITY"]


def test_version_mismatch_refuses_v7_unknown_capability():
    result = validate_implements(_cycle(), _capability(version="1.0"))
    assert not result.ok
    assert _codes(result) == ["V7_UNKNOWN_CAPABILITY"]
    assert "1.0" in result.diagnostics[0].message  # says what the registry actually has


def test_cycle_without_implements_passes_vacuously():
    result = validate_implements(_cycle(nil="cycle/0.2", implements=None), None)
    assert result.ok


# ── 4. V7 (a): required inputs producible ──────────────────────────────────────────────────────


def test_matching_contract_passes():
    assert validate_implements(_cycle(), _capability()).ok


def test_missing_required_input_refuses_with_the_field():
    result = validate_implements(_cycle(variables=[]), _capability())  # `amount` gone
    assert not result.ok
    assert _codes(result) == ["V7_INPUT_UNPRODUCIBLE"]
    assert result.diagnostics[0].location == "inputs.amount"


def test_optional_input_may_be_absent():
    cap = _capability(
        inputs=[
            {"name": "customer", "type": {"kind": "entity", "of": "Party"}, "required": True},
            {"name": "notes", "type": {"kind": "scalar", "of": "Text"}, "required": False},
        ]
    )
    assert validate_implements(_cycle(), cap).ok


def test_event_trigger_match_fields_count_as_producible():
    cycle = _cycle(
        variables=[],
        trigger={"type": "event", "on_verb": "billing.create_invoice", "match": {"amount": 5}},
    )
    assert validate_implements(cycle, _capability()).ok


# ── 5. V7 (b): outputs bound ────────────────────────────────────────────────────────────────────


def test_unbound_output_refuses_with_the_field():
    raw = _cycle_raw()
    raw["flow"]["steps"][0].pop("output")
    result = validate_implements(Cycle.model_validate(raw), _capability())
    assert not result.ok
    assert _codes(result) == ["V7_OUTPUT_UNBOUND"]
    assert result.diagnostics[0].location == "outputs.invoice"


def test_output_bound_by_any_step_passes():
    assert validate_implements(_cycle(), _capability()).ok


# ── 6. V7 (c): the floor only rises ─────────────────────────────────────────────────────────────


def _approval_cycle() -> Cycle:
    raw = _cycle_raw()
    raw["context"].append({"name": "approver", "entity_type": "User", "role": "Finance"})
    raw["flow"]["steps"][0]["next"] = "Gate"
    raw["flow"]["steps"].append(
        {
            "id": "Gate",
            "type": "approval",
            "title": {"ar": "موافقة", "en": "Approve"},
            "approver": "approver",
            "on_approve": "Create",
        }
    )
    # keep the graph simple: gate loops back on paper but V7 never walks edges
    return Cycle.model_validate(raw)


def test_high_floor_with_a_declared_low_verb_refuses_at_the_step():
    lookup = {"billing.create_invoice": {"tier": "LOW"}}.get
    result = validate_implements(
        _cycle(), _capability(risk="HIGH"), verb_metadata_lookup=lookup
    )
    assert not result.ok
    assert _codes(result) == ["V7_FLOOR_WEAKENED"]
    assert result.diagnostics[0].node == "Create"  # the refusal lands at the offending step


def test_high_floor_with_an_approval_step_passes():
    lookup = {"billing.create_invoice": {"tier": "LOW"}}.get
    result = validate_implements(
        _approval_cycle(), _capability(risk="HIGH"), verb_metadata_lookup=lookup
    )
    assert result.ok


def test_high_floor_with_an_undeclared_verb_passes_fail_closed():
    # An undeclared verb is HIGH by the fail-closed floor (I2) — the runtime gate parks it.
    assert validate_implements(_cycle(), _capability(risk="HIGH")).ok


def test_critical_floor_with_an_undeclared_verb_refuses():
    result = validate_implements(_cycle(), _capability(risk="CRITICAL"))
    assert not result.ok
    assert _codes(result) == ["V7_FLOOR_WEAKENED"]


def test_critical_floor_with_a_declared_critical_verb_passes():
    lookup = {"billing.create_invoice": {"tier": "CRITICAL"}}.get
    result = validate_implements(
        _cycle(), _capability(risk="CRITICAL"), verb_metadata_lookup=lookup
    )
    assert result.ok


def test_policy_raising_the_tier_satisfies_the_floor():
    cycle = _cycle(
        policies=[{"policy_id": "big_amounts", "applies_to": ["Create"], "raises_tier": "CRITICAL"}]
    )
    lookup = {"billing.create_invoice": {"tier": "LOW"}}.get
    result = validate_implements(
        cycle, _capability(risk="CRITICAL"), verb_metadata_lookup=lookup
    )
    assert result.ok


def test_medium_floor_needs_no_gate():
    lookup = {"billing.create_invoice": {"tier": "LOW"}}.get
    assert validate_implements(_cycle(), _capability(), verb_metadata_lookup=lookup).ok


# ── 7. V7 (d): compensation coverage ───────────────────────────────────────────────────────────


def test_promised_compensation_with_covered_writes_passes():
    raw = _cycle_raw()
    raw["flow"]["steps"][0]["compensate"] = {
        "use": "billing.void_invoice",
        "with": {"ref": "invoice.id"},
    }
    result = validate_implements(
        Cycle.model_validate(raw), _capability(compensation="VoidInvoice")
    )
    assert result.ok


def test_promised_compensation_with_an_uncovered_write_refuses_at_the_step():
    result = validate_implements(_cycle(), _capability(compensation="VoidInvoice"))
    assert not result.ok
    assert _codes(result) == ["V7_COMPENSATION_MISSING"]
    assert result.diagnostics[0].node == "Create"


def test_no_promised_compensation_needs_no_coverage():
    assert validate_implements(_cycle(), _capability()).ok


# ── 8. control plane: /cycles/register runs V7 (workspace-pinned) ──────────────────────────────

pytest.importorskip("fastapi", reason="the control-plane tests need fastapi extras")

from fastapi.testclient import TestClient  # noqa: E402

from nilscript.capability import capability_content_hash  # noqa: E402
from nilscript.controlplane.app import create_app  # noqa: E402
from nilscript.controlplane.store import EventStore  # noqa: E402


def _client(store: EventStore) -> TestClient:
    async def provider(workspace: str):
        return {
            "reachable": True,
            "conformant": True,
            "verbs": ["billing.create_invoice", "billing.void_invoice"],
            "targets": {},
            "verb_details": [
                {"verb": "billing.create_invoice", "tier": "MEDIUM"},
                {"verb": "billing.void_invoice", "tier": "MEDIUM"},
            ],
        }

    return TestClient(create_app(store, secret="", skeleton_provider=provider))


def _register_capability(store: EventStore, **over) -> None:
    capability = Capability.model_validate(_capability_raw(**over))
    store.register_capability(
        workspace=capability.workspace,
        capability_id=capability.capability_id,
        content_hash=capability_content_hash(capability),
        body=capability.model_dump(by_alias=True, mode="json"),
    )


def test_register_with_a_registered_capability_passes_v7():
    store = EventStore(":memory:")
    _register_capability(store)
    r = _client(store).post("/cycles/register", json={"cycle": _cycle_raw()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["definition"]["source"]["implements"] == {
        "capability_id": "IssueInvoice",
        "version": "2.3",
    }


def test_register_with_a_missing_capability_refuses_and_stores_nothing():
    store = EventStore(":memory:")
    r = _client(store).post("/cycles/register", json={"cycle": _cycle_raw()})
    assert r.status_code == 400
    refusal = r.json()["refusal"]
    assert [d["code"] for d in refusal] == ["V7_UNKNOWN_CAPABILITY"]
    assert store.list_automations("acme") == []  # refused, never stored


def test_registry_lookup_is_workspace_pinned():
    store = EventStore(":memory:")
    _register_capability(store, workspace="other")  # same id, ANOTHER tenant
    r = _client(store).post("/cycles/register", json={"cycle": _cycle_raw()})
    assert r.status_code == 400
    assert [d["code"] for d in r.json()["refusal"]] == ["V7_UNKNOWN_CAPABILITY"]


def test_register_refuses_a_weakened_floor_inline():
    store = EventStore(":memory:")
    _register_capability(store, risk="CRITICAL")
    r = _client(store).post("/cycles/register", json={"cycle": _cycle_raw()})
    assert r.status_code == 400
    diags = r.json()["refusal"]
    assert [d["code"] for d in diags] == ["V7_FLOOR_WEAKENED"]
    assert diags[0]["node"] == "Create"  # rendered at the offending step, like V1–V6


def test_draft_stays_v7_free():
    # /cycles/draft is the no-side-effect preview; V7 (a registry concern) gates REGISTER.
    store = EventStore(":memory:")
    r = _client(store).post("/cycles/draft", json={"cycle": _cycle_raw()})
    assert r.status_code == 200 and r.json()["ok"] is True
