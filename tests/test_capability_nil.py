"""Capability AST + `.capability.nil` surface — round-trip, hash-stability, refusal tests (§A1).

Pins the same two contracts the cycle surface proves:

  - parse_capability_nil(print_capability_nil(ast)) == ast   — the printer loses nothing
  - print_capability_nil(parse_capability_nil(text)) == text — printing is canonical/idempotent

plus the version lock (`capability_content_hash` is stable across authoring key order) and the
refusals-as-answers rule: an invalid shape refuses with a structured `NilSyntaxError`, never a bare
pydantic traceback.
"""

from __future__ import annotations

import pytest

from nilscript.capability import (
    Capability,
    NilSyntaxError,
    capability_content_hash,
    parse_capability_nil,
    print_capability_nil,
)


def _issue_invoice() -> dict:
    """The spec's worked example (§A1) — every optional section populated."""
    return {
        "nil": "capability/0.1",
        "capability_id": "IssueInvoice",
        "workspace": "acme",
        "version": "2.3",
        "domain": "Finance",
        "owner_role": "Finance",
        "intent": {"ar": "إصدار فاتورة عميل", "en": "Issue a customer invoice"},
        "aliases": ["bill customer", "send invoice", "فوترة العميل"],
        "examples": ["Issue an invoice for ACME's June order"],
        "inputs": [
            {"name": "customer", "type": {"kind": "entity", "of": "Party"}, "required": True},
            {"name": "items", "type": {"kind": "list", "of": "OrderLine"}, "required": True},
            {"name": "tax", "type": {"kind": "scalar", "of": "Money"}},
        ],
        "outputs": [{"name": "invoice", "type": {"kind": "entity", "of": "Invoice"}}],
        "risk": "MEDIUM",
        "strategy": "FinanceThreshold",
        "compensation": "CancelInvoice",
        "requires": ["ContractSigned"],
        "creates": ["Invoice"],
        "enables": ["PaymentCollection"],
        "exposure": {"ai": True, "roles": ["Finance", "Sales"]},
        "sod": {"preparer_not_approver": True},
        "archetype": "Fulfillment",
        "metrics": {"sla": "P2D"},
        "implemented_by": {"default": "IssueInvoiceCycle"},
    }


def _minimal() -> dict:
    """The smallest valid capability — every optional section at its default (a wrapped v0 shape:
    no archetype, no metrics, ai:false)."""
    return {
        "nil": "capability/0.1",
        "capability_id": "PingCheck",
        "workspace": "acme",
        "version": "0.1",
        "domain": "General",
        "owner_role": "owner",
        "intent": {"ar": "فحص", "en": "Ping check"},
        "risk": "LOW",
        "strategy": "PingCheckApproval",
        "implemented_by": {"default": "PingCheckCycle"},
    }


# --- 1. round-trip trust contract --------------------------------------------------------------


@pytest.mark.parametrize("fixture", [_issue_invoice, _minimal], ids=["worked", "minimal"])
def test_parse_of_print_round_trips_to_equal_ast(fixture):
    ast = Capability.model_validate(fixture())
    assert parse_capability_nil(print_capability_nil(ast)) == ast


@pytest.mark.parametrize("fixture", [_issue_invoice, _minimal], ids=["worked", "minimal"])
def test_printing_is_idempotent_for_canonical_text(fixture):
    canonical = print_capability_nil(Capability.model_validate(fixture()))
    assert print_capability_nil(parse_capability_nil(canonical)) == canonical


def test_every_worked_example_field_survives_round_trip():
    ast = Capability.model_validate(_issue_invoice())
    out = parse_capability_nil(print_capability_nil(ast))
    assert out.version == "2.3"
    assert out.owner_role == "Finance"
    assert out.aliases == ("bill customer", "send invoice", "فوترة العميل")
    customer = next(f for f in out.inputs if f.name == "customer")
    assert customer.type.kind == "entity" and customer.type.of == "Party" and customer.required
    tax = next(f for f in out.inputs if f.name == "tax")
    assert tax.type.kind == "scalar" and tax.type.of == "Money" and not tax.required
    assert out.outputs[0].type.kind == "entity"
    assert out.risk == "MEDIUM" and out.strategy == "FinanceThreshold"
    assert out.compensation == "CancelInvoice"
    assert out.requires == ("ContractSigned",) and out.enables == ("PaymentCollection",)
    assert out.exposure.ai is True and out.exposure.roles == ("Finance", "Sales")
    assert out.sod.preparer_not_approver is True
    assert out.archetype == "Fulfillment"
    assert out.metrics is not None and out.metrics.sla == "P2D"
    assert out.implemented_by == {"default": "IssueInvoiceCycle"}
    assert out == ast


def test_archetype_is_optional_and_absent_means_none():
    """Auto-wrapped v0 capabilities omit the tag rather than guess semantics (fail closed)."""
    out = parse_capability_nil(print_capability_nil(Capability.model_validate(_minimal())))
    assert out.archetype is None
    assert "archetype" not in print_capability_nil(out)


def test_multiple_implementations_preserve_order():
    raw = _issue_invoice()
    raw["implemented_by"] = {"default": "IssueInvoiceCycle", "manual": "ManualInvoiceCycle"}
    ast = Capability.model_validate(raw)
    out = parse_capability_nil(print_capability_nil(ast))
    assert list(out.implemented_by) == ["default", "manual"]
    assert out == ast


def test_single_string_intent_sets_both_languages():
    text = print_capability_nil(Capability.model_validate(_minimal())).replace(
        'intent { ar: "فحص"; en: "Ping check" }', 'intent "One language"'
    )
    out = parse_capability_nil(text)
    assert out.intent.ar == "One language" and out.intent.en == "One language"


# --- 2. the version lock: hash stability -------------------------------------------------------


def test_content_hash_is_stable_across_authoring_key_order():
    raw = _issue_invoice()
    shuffled = dict(reversed(list(raw.items())))  # same content, different key insertion order
    a = Capability.model_validate(raw)
    b = Capability.model_validate(shuffled)
    assert capability_content_hash(a) == capability_content_hash(b)
    assert len(capability_content_hash(a)) == 64


def test_content_hash_changes_with_content():
    a = Capability.model_validate(_issue_invoice())
    changed = _issue_invoice()
    changed["risk"] = "HIGH"
    b = Capability.model_validate(changed)
    assert capability_content_hash(a) != capability_content_hash(b)


def test_hash_survives_the_text_round_trip():
    ast = Capability.model_validate(_issue_invoice())
    assert capability_content_hash(parse_capability_nil(print_capability_nil(ast))) == (
        capability_content_hash(ast)
    )


# --- 3. invalid shapes refuse with structured errors --------------------------------------------


def test_unknown_archetype_refuses():
    text = print_capability_nil(Capability.model_validate(_issue_invoice())).replace(
        "archetype Fulfillment", "archetype Teleportation"
    )
    with pytest.raises(NilSyntaxError) as exc:
        parse_capability_nil(text)
    assert "invalid capability" in exc.value.message


def test_missing_default_implementation_refuses():
    raw = _minimal()
    raw["implemented_by"] = {"manual": "SomeCycle"}
    with pytest.raises(ValueError, match='requires a "default"'):
        Capability.model_validate(raw)


def test_bad_version_token_refuses_with_position():
    with pytest.raises(NilSyntaxError) as exc:
        parse_capability_nil("capability X 2.3 {\n}\n")
    assert "expected a version" in exc.value.message
    assert exc.value.line == 1


def test_unknown_section_refuses_with_line():
    text = 'capability X v1.0 {\n  surprise "nope"\n}\n'
    with pytest.raises(NilSyntaxError) as exc:
        parse_capability_nil(text)
    assert "unknown section" in exc.value.message
    assert exc.value.line == 2


def test_missing_required_sections_refuse():
    with pytest.raises(NilSyntaxError) as exc:
        parse_capability_nil('capability X v1.0 {\n  workspace "acme"\n}\n')
    assert "invalid capability" in exc.value.message


def test_non_identifier_refs_refuse():
    raw = _minimal()
    raw["requires"] = ["has space"]
    with pytest.raises(ValueError, match="identifiers"):
        Capability.model_validate(raw)


def test_unknown_member_is_unrepresentable():
    raw = _minimal()
    raw["surprise"] = True
    with pytest.raises(ValueError):
        Capability.model_validate(raw)
