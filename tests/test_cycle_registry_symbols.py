"""The Protocol Registry — symbol layer over a Cycle AST (LSP spine: go-to-def, find-refs,
completion, dead-reference). These tests pin the symbol contract against the worked
`SalesLeadLifecycle` v0.2 example (copied from tests/test_cycle_ast.py).
"""

from __future__ import annotations

from nilscript.cycle import Cycle, ProtocolRegistry, Symbol
from nilscript.kernel.context import SkillSpec, ValidationContext


# --- fixtures: the worked SalesLeadLifecycle (copied from tests/test_cycle_ast.py) ------------


def _ctx() -> ValidationContext:
    verbs = {
        "odoo.crm_create_lead",
        "sales.assign_rep",
        "odoo.sale_create_quotation",
        "whatsapp.send_message",
        "audit.log_event",
    }
    by_skill: dict[str, set[str]] = {}
    for v in verbs:
        by_skill.setdefault(v.split(".", 1)[0], set()).add(v)
    return ValidationContext(
        skills={
            name: SkillSpec(required_verbs=frozenset(group), hint_schema={"additionalProperties": True})
            for name, group in by_skill.items()
        },
        read_verbs=frozenset(),
        workspaces={"acme": frozenset(verbs)},
    )


def _sales_lead_lifecycle(*, opportunity_verb: str = "odoo.sale_create_quotation") -> dict:
    return {
        "nil": "cycle/0.2",
        "cycle_id": "SalesLeadLifecycle",
        "workspace": "acme",
        "metadata": {
            "version": "1.3.2",
            "owner": "Sales Team",
            "description": {"ar": "دورة حياة العميل المحتمل", "en": "Lead lifecycle"},
            "tags": ["sales", "crm", "leads"],
        },
        "intent": {"ar": "من إنشاء العميل إلى عرض السعر والمتابعة", "en": "Lead to quotation and follow-up"},
        "trigger": {"type": "event", "on_verb": "odoo.crm_create_lead"},
        "context": [
            {"name": "lead", "entity_type": "Lead"},
            {"name": "customer", "entity_type": "Customer"},
            {"name": "quotation", "entity_type": "Quotation"},
            {"name": "approver", "entity_type": "User", "role": "SalesManager"},
        ],
        "variables": [{"name": "payload", "expression": "context.payload"}],
        "roles": [{"role": "SalesManager"}],
        "policies": [],
        "resources": ["odoo.crm_create_lead", "sales.assign_rep", "odoo.sale_create_quotation"],
        "outcomes": [{"name": "won", "when": "true"}],
        "flow": {
            "entry": "CreateLead",
            "steps": [
                {
                    "id": "CreateLead",
                    "type": "action",
                    "use": "odoo.crm_create_lead",
                    "with": {"name": "payload.name", "email": "payload.email"},
                    "output": "lead",
                    "next": "AssignSalesRep",
                },
                {
                    "id": "AssignSalesRep",
                    "type": "action",
                    "use": "sales.assign_rep",
                    "with": {"lead_id": "lead.id", "ruleset": "default"},
                    "output": "lead",
                    "next": "Approval",
                },
                {
                    "id": "Approval",
                    "type": "approval",
                    "title": {"ar": "اعتماد", "en": "Approve lead & proceed?"},
                    "description": {"ar": "راجع العميل واعتمد", "en": "Review lead details and approve"},
                    "approver": "approver",
                    "timeout_seconds": 172800,
                    "on_approve": "CreateQuotation",
                    "on_reject": "EndRejected",
                },
                {
                    "id": "CreateQuotation",
                    "type": "action",
                    "use": opportunity_verb,
                    "with": {"lead_id": "lead.id"},
                    "output": "quotation",
                    "next": "NotifyCustomer",
                },
                {
                    "id": "NotifyCustomer",
                    "type": "action",
                    "use": "whatsapp.send_message",
                    "with": {"to": "customer.phone"},
                    "next": "LogActivity",
                },
                {
                    "id": "LogActivity",
                    "type": "action",
                    "use": "audit.log_event",
                    "with": {"event": "quotation_sent"},
                },
                {
                    "id": "EndRejected",
                    "type": "notify",
                    "message": {"ar": "رُفض", "en": "Rejected"},
                },
            ],
        },
    }


def _registry(ctx: ValidationContext | None = None, raw: dict | None = None) -> ProtocolRegistry:
    cycle = Cycle.model_validate(raw or _sales_lead_lifecycle())
    return ProtocolRegistry.from_cycle(cycle, ctx)


# --- 1. resolve: go-to-definition for each kind ----------------------------------------------


def test_resolve_step_symbol():
    sym = _registry().resolve("CreateLead")
    assert isinstance(sym, Symbol)
    assert sym.kind == "step"
    assert sym.defined_at == "CreateLead"
    assert "odoo.crm_create_lead" in sym.detail


def test_resolve_context_entity_with_role():
    sym = _registry().resolve("approver")
    assert sym is not None
    assert sym.kind == "context_entity"
    assert sym.defined_at == "context"
    assert "User" in sym.detail
    assert "SalesManager" in sym.detail


def test_resolve_output_keeps_last_producer():
    """`lead` is the output of CreateLead AND AssignSalesRep — most-recent producer wins."""
    sym = _registry().resolve("lead")
    assert sym is not None
    assert sym.kind == "output"
    assert sym.defined_at == "AssignSalesRep"
    assert "output of" in sym.detail


def test_resolve_variable():
    sym = _registry().resolve("payload")
    assert sym is not None
    assert sym.kind == "variable"
    assert sym.defined_at == "variables"


def test_resolve_role_policy_outcome():
    reg = _registry()
    assert reg.resolve("SalesManager").kind == "role"
    assert reg.resolve("won").kind == "outcome"


def test_resolve_unknown_returns_none():
    assert _registry().resolve("DoesNotExist") is None


# --- 2. references: find-references -----------------------------------------------------------


def test_references_step_target_includes_branch():
    """CreateQuotation is the on_approve target of Approval."""
    refs = _registry().references("CreateQuotation")
    assert "Approval" in refs


def test_references_output_includes_consuming_steps():
    """Steps consuming `lead.id` reference `lead`."""
    refs = _registry().references("lead")
    assert "AssignSalesRep" in refs  # with.lead_id = lead.id
    assert "CreateQuotation" in refs  # with.lead_id = lead.id


def test_references_approver_context_entity():
    """The Approval step's `approver` references the `approver` context entity."""
    assert "Approval" in _registry().references("approver")


def test_references_next_target():
    """AssignSalesRep is CreateLead's `next`."""
    assert "CreateLead" in _registry().references("AssignSalesRep")


# --- 3. completions / verb catalog -----------------------------------------------------------


def test_completions_step_returns_all_seven_steps():
    steps = _registry().completions("step")
    names = {s.name for s in steps}
    assert names == {
        "CreateLead",
        "AssignSalesRep",
        "Approval",
        "CreateQuotation",
        "NotifyCustomer",
        "LogActivity",
        "EndRejected",
    }
    assert all(s.kind == "step" for s in steps)


def test_completions_verb_lists_catalog_verbs():
    verbs = _registry(_ctx()).completions("verb")
    names = {s.name for s in verbs}
    assert "odoo.crm_create_lead" in names
    assert "whatsapp.send_message" in names
    assert all(s.kind == "verb" for s in verbs)


def test_completions_unfiltered_returns_all_kinds():
    syms = _registry(_ctx()).completions()
    kinds = {s.kind for s in syms}
    assert {"step", "variable", "context_entity", "role", "output", "outcome", "verb"} <= kinds


def test_verbs_for_prefix_filters():
    reg = _registry(_ctx())
    odoo = reg.verbs_for("odoo.")
    assert set(odoo) == {"odoo.crm_create_lead", "odoo.sale_create_quotation"}
    assert reg.verbs_for("whatsapp.") == ["whatsapp.send_message"]


def test_verb_grant_state_in_detail():
    """With full grants, a verb is 'granted'; restrict scopes and it is 'known (not granted)'."""
    reg = _registry(_ctx())
    assert "granted" in reg.resolve("odoo.crm_create_lead").detail

    restricted = ValidationContext(
        skills=_ctx().skills,
        read_verbs=frozenset(),
        workspaces={"acme": frozenset({"odoo.crm_create_lead"})},
    )
    reg2 = _registry(restricted)
    assert "not granted" in reg2.resolve("whatsapp.send_message").detail


def test_no_catalog_means_no_verbs():
    assert _registry(None).completions("verb") == []
    assert _registry(None).verbs_for("odoo.") == []


# --- 4. dead-reference detection --------------------------------------------------------------


def test_dead_reference_flags_missing_next_target():
    raw = _sales_lead_lifecycle()
    # inject a step whose `next` points at a step that does not exist
    raw["flow"]["steps"].append(
        {
            "id": "Orphan",
            "type": "notify",
            "message": {"ar": "x", "en": "x"},
            "next": "NoSuchStep",
        }
    )
    findings = _registry(raw=raw).dead_references()
    problems = {(f.name, f.problem) for f in findings}
    assert ("NoSuchStep", "undefined_step") in problems


def test_dead_reference_flags_unused_variable():
    raw = _sales_lead_lifecycle()
    raw["variables"].append({"name": "unusedvar", "expression": "context.extra"})
    findings = _registry(raw=raw).dead_references()
    problems = {(f.name, f.problem) for f in findings}
    assert ("unusedvar", "unused_variable") in problems


def test_dead_reference_flags_undefined_value_ref():
    raw = _sales_lead_lifecycle()
    # reference a name that is no value source (not output/variable/context/role)
    raw["flow"]["steps"][0]["with"]["ghost"] = "phantom.field"
    findings = _registry(raw=raw).dead_references()
    problems = {(f.name, f.problem) for f in findings}
    assert ("phantom", "undefined_ref") in problems


def test_clean_cycle_has_no_undefined_references():
    """The worked example resolves cleanly: no undefined steps or value refs."""
    findings = _registry(_ctx()).dead_references()
    undefined = [f for f in findings if f.problem in ("undefined_step", "undefined_ref")]
    assert undefined == []


def test_literal_value_is_not_a_dead_reference():
    """`ruleset: "default"` and `event: "quotation_sent"` are literals, never flagged."""
    findings = _registry().dead_references()
    names = {f.name for f in findings if f.problem == "undefined_ref"}
    assert "default" not in names
    assert "quotation_sent" not in names
