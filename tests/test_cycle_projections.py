"""Projection generators over the Cycle AST v0.2 (docs/PLAN-cycle-ast-ssot.md §5).

Each projection is a PURE, read-only view of one `Cycle` — no execution, no control plane, no new
source of truth. These tests pin all four against the worked `SalesLeadLifecycle` example:

  - to_mermaid        — a `flowchart TD` with the approval drawn as a diamond and labelled edges
  - to_markdown       — human documentation (title, approver role, numbered steps)
  - simulate          — an ordered happy-path dry-run (approve, NOT reject)
  - governance_report — gates / approvals / honest reversibility
"""

from __future__ import annotations

from nilscript.cycle import (
    Cycle,
    governance_report,
    simulate,
    to_markdown,
    to_mermaid,
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


def _cycle() -> Cycle:
    return Cycle.model_validate(_sales_lead_lifecycle())


# --- to_mermaid -------------------------------------------------------------------------------


def test_mermaid_is_a_flowchart_td():
    assert to_mermaid(_cycle()).startswith("flowchart TD")


def test_mermaid_draws_approval_as_a_diamond():
    out = to_mermaid(_cycle())
    # an approval node is a decision diamond `{...}`, not a box
    assert "Approval{" in out


def test_mermaid_labels_approve_and_reject_edges():
    out = to_mermaid(_cycle())
    assert "Approval -->|approve| CreateQuotation" in out
    assert "Approval -->|reject| EndRejected" in out


def test_mermaid_is_deterministic():
    cycle = _cycle()
    assert to_mermaid(cycle) == to_mermaid(cycle)


# --- to_markdown ------------------------------------------------------------------------------


def test_markdown_contains_title():
    out = to_markdown(_cycle())
    assert "SalesLeadLifecycle" in out
    assert "Lead to quotation and follow-up" in out  # intent.en


def test_markdown_contains_approver_role():
    out = to_markdown(_cycle())
    assert "SalesManager" in out  # the approver's role in the Context table


def test_markdown_has_numbered_create_lead_step():
    out = to_markdown(_cycle())
    assert "1. **CreateLead**" in out
    assert "`odoo.crm_create_lead`" in out


# --- simulate ---------------------------------------------------------------------------------


def test_simulate_walks_the_happy_path_not_the_reject_branch():
    walk = simulate(_cycle())
    names = [entry["step"] for entry in walk]
    assert names == [
        "CreateLead",
        "AssignSalesRep",
        "Approval",
        "CreateQuotation",
        "NotifyCustomer",
        "LogActivity",
    ]
    assert "EndRejected" not in names  # happy path takes on_approve, not on_reject


def test_simulate_marks_the_approval_step():
    walk = simulate(_cycle())
    approval = next(e for e in walk if e["step"] == "Approval")
    assert approval["requires_approval"] is True
    assert approval["approver"] == "approver"


def test_simulate_proposes_actions_without_executing():
    walk = simulate(_cycle())
    create = next(e for e in walk if e["step"] == "CreateLead")
    assert create["requires_approval"] is False
    assert create["verb"] == "odoo.crm_create_lead"
    assert create["proposes"] == "odoo.crm_create_lead"


def test_simulate_is_capped_and_raises_nothing():
    walk = simulate(_cycle())
    assert len(walk) <= len(_cycle().flow.steps)


# --- governance_report ------------------------------------------------------------------------


def test_governance_gates_include_the_approval():
    report = governance_report(_cycle())
    assert "Approval" in report["gates"]
    assert report["total_steps"] == 7


def test_governance_approvals_carry_approver_and_timeout():
    report = governance_report(_cycle())
    assert report["approvals"] == [
        {"step": "Approval", "approver": "approver", "timeout_seconds": 172800}
    ]


def test_governance_reversibility_is_honest_no_compensation_declared():
    report = governance_report(_cycle())
    # every action step is listed; none declares `compensate`, so none is provably reversible
    action_names = {"CreateLead", "AssignSalesRep", "CreateQuotation", "NotifyCustomer", "LogActivity"}
    listed = {r["step"] for r in report["reversibility"]}
    assert listed == action_names
    assert all(r["reversible"] is False for r in report["reversibility"])


def test_governance_policy_high_tier_also_gates_its_target():
    raw = _sales_lead_lifecycle()
    raw["policies"] = [{"policy_id": "big_deal", "applies_to": ["CreateQuotation"], "raises_tier": "HIGH"}]
    report = governance_report(Cycle.model_validate(raw))
    assert "CreateQuotation" in report["gates"]
    assert "Approval" in report["gates"]
