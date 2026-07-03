"""The `.nil` text surface — printer/parser round-trip tests (docs/PLAN-cycle-ast-ssot.md Phase 4).

The `.nil` text is the SECOND authoring view over the frozen Cycle AST v0.2. `print_nil` DEFINES the
canonical form; `parse_nil` is its inverse. Two contracts pin the trust:

  - parse_nil(print_nil(ast)) == ast    — the printer loses nothing (the round-trip trust contract)
  - print_nil(parse_nil(text)) == text  — printing is stable / canonical (idempotent)

We also pin malformed input → `NilSyntaxError(line)`, and that EVERY field of the worked example
survives the round trip (tags, variables, role-bound context, named outputs, approval branches,
next pointers) — no AST field is unprintable, no surface construct is unmodelled.
"""

from __future__ import annotations

import pytest

from nilscript.cycle import Cycle, NilSyntaxError, parse_nil, print_nil


# --- the worked SalesLeadLifecycle (same v0.2 dict as tests/test_cycle_ast.py) ----------------


def _sales_lead_lifecycle() -> dict:
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
                    "use": "odoo.sale_create_quotation",
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


def _manual_with_decision() -> dict:
    """A manual-trigger cycle with a decision step, policies, and outcomes — the variant surfaces."""
    return {
        "nil": "cycle/0.2",
        "cycle_id": "ManualDecision",
        "workspace": "acme",
        "metadata": {"version": "1.0.0", "owner": "Ops"},
        "intent": {"ar": "قرار يدوي", "en": "Manual decision"},
        "trigger": {"type": "manual"},
        "policies": [
            {
                "policy_id": "big_deal",
                "applies_to": ["DoIt"],
                "condition": "amount > 100",
                "raises_tier": "HIGH",
            }
        ],
        "outcomes": [{"name": "approved"}, {"name": "won", "when": "true"}],
        "flow": {
            "entry": "Decide",
            "steps": [
                {
                    "id": "Decide",
                    "type": "decision",
                    "when": "amount > 0",
                    "on_true": "DoIt",
                    "on_false": "End",
                },
                {
                    "id": "DoIt",
                    "type": "action",
                    "use": "odoo.do_thing",
                    "with": {"count": 3, "ref": "a.b", "flag": True, "items": [1, 2], "obj": {"k": "v"}},
                    "next": "End",
                },
                {"id": "End", "type": "notify", "message": {"ar": "تم", "en": "Done"}},
            ],
        },
    }


def _schedule_with_query_and_doc() -> dict:
    """A schedule-trigger cycle with a query step, ar-only documentation, and a single-string title."""
    return {
        "nil": "cycle/0.2",
        "cycle_id": "NightlyScan",
        "workspace": "acme",
        "metadata": {"version": "2.1.0", "owner": "Ops", "tags": ["batch"]},
        "intent": {"ar": "مسح ليلي", "en": "Nightly scan"},
        "trigger": {"type": "schedule", "cron": "0 2 * * *", "timezone": "UTC"},
        "documentation": {"ar": "وثيقة داخلية"},  # ar-only → en is None
        "flow": {
            "entry": "Scan",
            "steps": [
                {"id": "Scan", "type": "query", "use": "odoo.read_overdue", "with": {}, "output": "rows"},
            ],
        },
    }


# --- 1. the round-trip trust contract: parse(print(ast)) == ast -------------------------------


@pytest.mark.parametrize(
    "fixture",
    [_sales_lead_lifecycle, _manual_with_decision, _schedule_with_query_and_doc],
    ids=["sales_lead", "manual_decision", "schedule_query"],
)
def test_parse_of_print_round_trips_to_equal_ast(fixture):
    ast = Cycle.model_validate(fixture())
    assert parse_nil(print_nil(ast)) == ast


# --- 2. printing is idempotent: print(parse(text)) == text ------------------------------------


def test_printing_is_idempotent_for_canonical_text():
    canonical = print_nil(Cycle.model_validate(_sales_lead_lifecycle()))
    assert print_nil(parse_nil(canonical)) == canonical


def test_idempotent_for_every_variant():
    for fixture in (_manual_with_decision, _schedule_with_query_and_doc):
        canonical = print_nil(Cycle.model_validate(fixture()))
        assert print_nil(parse_nil(canonical)) == canonical


# --- 3. grammar cap: every field of the worked example survives the round trip -----------------


def test_all_worked_example_fields_survive_round_trip():
    ast = Cycle.model_validate(_sales_lead_lifecycle())
    out = parse_nil(print_nil(ast))

    # metadata.tags
    assert out.metadata.tags == ("sales", "crm", "leads")
    assert out.metadata.description is not None
    assert out.metadata.description.ar == "دورة حياة العميل المحتمل"

    # variables (let payload = context.payload)
    assert out.variables == ast.variables
    assert out.variables[0].name == "payload" and out.variables[0].expression == "context.payload"

    # role-bound context actor
    approver = next(e for e in out.context if e.name == "approver")
    assert approver.entity_type == "User" and approver.role == "SalesManager"

    # named outputs + next pointers on action steps
    create = next(s for s in out.flow.steps if s.id == "CreateLead")
    assert create.output == "lead" and create.next == "AssignSalesRep"
    assert create.with_ == {"name": "payload.name", "email": "payload.email"}

    # approval on approve / on reject + timeout
    approval = next(s for s in out.flow.steps if s.id == "Approval")
    assert approval.on_approve == "CreateQuotation"
    assert approval.on_reject == "EndRejected"
    assert approval.timeout_seconds == 172800

    # entry pointer + outcomes
    assert out.flow.entry == "CreateLead"
    assert out.outcomes[0].name == "won" and out.outcomes[0].when == "true"

    # the whole object is identical
    assert out == ast


def test_bilingual_single_string_sets_both_ar_and_en():
    text = (
        'cycle Hi triggers manual {\n'
        '  workspace "acme"\n'
        '  intent "Just one language"\n'
        '  meta { version: "1.0.0"; owner: "Ops" }\n'
        '  flow entry N {\n'
        '    step N {\n'
        '      notify "ping"\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    cycle = parse_nil(text)
    assert cycle.intent.ar == "Just one language"
    assert cycle.intent.en == "Just one language"
    notify = cycle.flow.steps[0]
    assert notify.message.ar == "ping" and notify.message.en == "ping"


def test_decision_step_round_trips():
    ast = Cycle.model_validate(_manual_with_decision())
    out = parse_nil(print_nil(ast))
    decide = next(s for s in out.flow.steps if s.id == "Decide")
    assert decide.when == "amount > 0"
    assert decide.on_true == "DoIt" and decide.on_false == "End"


def test_policies_and_outcomes_round_trip():
    ast = Cycle.model_validate(_manual_with_decision())
    out = parse_nil(print_nil(ast))
    assert out.policies == ast.policies
    assert out.policies[0].raises_tier == "HIGH"
    assert out.policies[0].applies_to == ("DoIt",)
    assert out.outcomes == ast.outcomes


# --- 4. malformed input raises NilSyntaxError with a line number ------------------------------


def test_missing_closing_brace_raises_with_line():
    text = (
        'cycle Hi triggers manual {\n'
        '  workspace "acme"\n'
        '  intent "x"\n'
        '  meta { version: "1.0.0"; owner: "Ops" }\n'
        '  flow entry N {\n'
        '    step N {\n'
        '      notify "ping"\n'
        # missing closing braces
    )
    with pytest.raises(NilSyntaxError) as exc:
        parse_nil(text)
    assert exc.value.line >= 1


def test_unknown_step_type_raises_with_line():
    text = (
        'cycle Hi triggers manual {\n'
        '  workspace "acme"\n'
        '  intent "x"\n'
        '  meta { version: "1.0.0"; owner: "Ops" }\n'
        '  flow entry N {\n'
        '    step N {\n'
        '      teleport somewhere\n'  # not a real step keyword
        '    }\n'
        '  }\n'
        '}\n'
    )
    with pytest.raises(NilSyntaxError) as exc:
        parse_nil(text)
    assert "unknown step type" in exc.value.message
    assert exc.value.line == 7


def test_unterminated_string_raises_with_line():
    text = 'cycle Hi triggers manual {\n  workspace "acme\n'  # unterminated string on line 2
    with pytest.raises(NilSyntaxError) as exc:
        parse_nil(text)
    assert exc.value.line == 2


def test_bad_token_raises():
    with pytest.raises(NilSyntaxError):
        parse_nil("cycle Hi triggers manual {\n  workspace @bad\n}\n")


def test_unknown_section_raises_with_line():
    text = (
        'cycle Hi triggers manual {\n'
        '  surprise "nope"\n'  # not a section keyword
        '}\n'
    )
    with pytest.raises(NilSyntaxError) as exc:
        parse_nil(text)
    assert "unknown section" in exc.value.message
    assert exc.value.line == 2


# --- 5. error/compensation clauses on action steps (retry / on_error / compensate_with) --------
#
# ActionStep has carried `retry`, `on_error`, and `compensate` since the v0.2 freeze, but the
# printer never emitted them — a cycle using them broke parse(print(ast)) == ast, the SSOT trust
# contract. Canonical grammar (between the verb line and the output/next routing tail):
#
#   retry { max_attempts: 3; backoff: exponential; initial_seconds: 2.0 }
#   on_error route -> Cleanup          (the `-> target` only when `to` is set)
#   compensate_with odoo.refund { payment_id: pay.id }


def _action_cycle(**step_fields) -> Cycle:
    """A minimal one-action cycle whose action step carries `step_fields`."""
    return Cycle.model_validate(
        {
            "nil": "cycle/0.2",
            "cycle_id": "PayFlow",
            "workspace": "acme",
            "metadata": {"version": "1.0.0", "owner": "Ops"},
            "intent": {"ar": "دفع", "en": "Pay"},
            "trigger": {"type": "manual"},
            "flow": {
                "entry": "Pay",
                "steps": [
                    {
                        "id": "Pay",
                        "type": "action",
                        "use": "odoo.pay_invoice",
                        "with": {"amount": 500},
                        "output": "pay",
                        "next": "Done",
                        **step_fields,
                    },
                    {"id": "Cleanup", "type": "notify", "message": {"ar": "نظف", "en": "Clean"}},
                    {"id": "Done", "type": "notify", "message": {"ar": "تم", "en": "Done"}},
                ],
            },
        }
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"retry": {"max_attempts": 3}},  # defaults fill backoff/initial_seconds
        {"retry": {"max_attempts": 5, "backoff": "fixed", "initial_seconds": 1.5}},
        {"on_error": {"action": "halt"}},
        {"on_error": {"action": "continue"}},
        {"on_error": {"action": "route", "to": "Cleanup"}},
        {"on_error": {"action": "compensate"}},
        {"compensate": {"use": "odoo.refund_invoice", "with": {"payment_id": "pay.id"}}},
        {"compensate": {"use": "odoo.refund_invoice"}},  # empty args → `{}`
        {  # all three combined
            "retry": {"max_attempts": 3},
            "on_error": {"action": "route", "to": "Cleanup"},
            "compensate": {"use": "odoo.refund_invoice", "with": {"payment_id": "pay.id"}},
        },
    ],
    ids=[
        "retry_defaults",
        "retry_explicit",
        "on_error_halt",
        "on_error_continue",
        "on_error_route",
        "on_error_compensate",
        "compensate_with_args",
        "compensate_empty_args",
        "all_combined",
    ],
)
def test_error_clauses_round_trip(fields):
    ast = _action_cycle(**fields)
    assert parse_nil(print_nil(ast)) == ast
    # and printing is idempotent (the printed text IS canonical)
    canonical = print_nil(ast)
    assert print_nil(parse_nil(canonical)) == canonical


def test_error_clauses_print_in_canonical_form():
    ast = _action_cycle(
        retry={"max_attempts": 3},
        on_error={"action": "route", "to": "Cleanup"},
        compensate={"use": "odoo.refund_invoice", "with": {"payment_id": "pay.id"}},
    )
    text = print_nil(ast)
    assert "      retry { max_attempts: 3; backoff: exponential; initial_seconds: 2.0 }\n" in text
    assert "      on_error route -> Cleanup\n" in text
    assert '      compensate_with odoo.refund_invoice { payment_id: "pay.id" }\n' in text
    # the clauses sit between the verb line and the routing tail
    step_block = text.split("step Pay {", 1)[1].split("output pay", 1)[0]
    order = [step_block.index(k) for k in ("use ", "retry ", "on_error ", "compensate_with ")]
    assert order == sorted(order)


def test_on_error_without_target_prints_no_arrow():
    text = print_nil(_action_cycle(on_error={"action": "halt"}))
    assert "on_error halt\n" in text
    assert "->" not in text.split("on_error halt")[1].split("\n")[0]


def test_query_step_rejects_error_clauses():
    """The clauses are ActionStep-only; a query step carrying `retry` must not parse."""
    text = (
        'cycle Q triggers manual {\n'
        '  workspace "acme"\n'
        '  intent "q"\n'
        '  meta { version: "1.0.0"; owner: "Ops" }\n'
        '  flow entry Scan {\n'
        '    step Scan {\n'
        '      query odoo.read_rows {}\n'
        '      retry { max_attempts: 3; backoff: exponential; initial_seconds: 2.0 }\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    with pytest.raises(NilSyntaxError):
        parse_nil(text)


def test_unknown_retry_field_raises():
    text = (
        'cycle Q triggers manual {\n'
        '  workspace "acme"\n'
        '  intent "q"\n'
        '  meta { version: "1.0.0"; owner: "Ops" }\n'
        '  flow entry Pay {\n'
        '    step Pay {\n'
        '      use odoo.pay_invoice {}\n'
        '      retry { attempts: 3 }\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    with pytest.raises(NilSyntaxError) as exc:
        parse_nil(text)
    assert "unknown retry field" in exc.value.message


# --- 6. byte-stability regression: fields-absent cycles print EXACTLY as before ----------------
#
# The printer DEFINES canonical form and cycle/0.2 is FROZEN: adding the error-clause grammar must
# not move a single byte of any cycle that does not use the fields. These sha256 hashes were
# computed against the printer BEFORE the clauses existed — if one changes, the syntax choice
# broke the freeze (content-hash stability for every pre-existing cycle is non-negotiable).

_CANONICAL_SHA256 = {
    "sales_lead": "2be296097f3396000bc3c0e7c8b4839862e7eec8f9e4f432d799ea27c7512f6d",
    "manual_decision": "b31b60351cd3e310fdce56fc58dc6bf30e8c39ca25baea87626f30162bf00a1e",
    "schedule_query": "980e7468ad3a97ff60c90f5a48457225bffc843f547db805dbd058e76dde61eb",
}


@pytest.mark.parametrize(
    ("key", "fixture"),
    [
        ("sales_lead", _sales_lead_lifecycle),
        ("manual_decision", _manual_with_decision),
        ("schedule_query", _schedule_with_query_and_doc),
    ],
    ids=["sales_lead", "manual_decision", "schedule_query"],
)
def test_fields_absent_cycles_print_byte_identical_to_before(key, fixture):
    import hashlib

    text = print_nil(Cycle.model_validate(fixture()))
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == _CANONICAL_SHA256[key]
