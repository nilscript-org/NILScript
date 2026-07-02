"""Strategy AST + `.strategy.nil` surface — round-trip and parse-refusal tests (§A2).

Pins the bijection for every one of the MVP-5 forms (Auto/Approve/Seq/Quorum/Conditional), the
timeout grammar (`P2D -> escalate(role: X)` / `-> reject` / route-less), and the reserved-form
refusal: `par/weighted/dynamic/delegate/override` PARSE-REFUSE with `V9_UNSUPPORTED_FORM` — a
clear governance answer, not a generic syntax error.
"""

from __future__ import annotations

import pytest

from nilscript.strategy import (
    NilSyntaxError,
    NilUnsupportedFormError,
    Strategy,
    parse_strategy_nil,
    print_strategy_nil,
    strategy_content_hash,
)


def _finance_threshold() -> dict:
    """The spec's worked example: conditional over auto + seq with timeout escalation and SoD."""
    return {
        "nil": "strategy/0.1",
        "strategy_id": "FinanceThreshold",
        "workspace": "acme",
        "version": 1,
        "root": {
            "form": "conditional",
            "when": "amount < 5000",
            "then": {"form": "auto", "policy": "small_ops"},
            "else": {
                "form": "seq",
                "items": [
                    {
                        "form": "approve",
                        "unit": {
                            "by": "role",
                            "name": "Manager",
                            "timeout": {
                                "after": "P2D",
                                "then": {"kind": "escalate", "to": "Finance"},
                            },
                        },
                    },
                    {
                        "form": "approve",
                        "unit": {
                            "by": "role",
                            "name": "Finance",
                            "distinct_from": ["preparer"],
                        },
                    },
                ],
            },
        },
    }


def _customs_two_key() -> dict:
    """The spec's second worked example: a distinct two-key quorum."""
    return {
        "nil": "strategy/0.1",
        "strategy_id": "CustomsTwoKey",
        "workspace": "acme",
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


def _single_approve() -> dict:
    return {
        "nil": "strategy/0.1",
        "strategy_id": "OwnerGate",
        "workspace": "acme",
        "version": 3,
        "root": {
            "form": "approve",
            "unit": {
                "by": "person",
                "name": "rizgi",
                "timeout": {"after": "PT4H", "then": {"kind": "reject"}},
            },
        },
    }


def _plain_auto() -> dict:
    return {
        "nil": "strategy/0.1",
        "strategy_id": "SmallOps",
        "workspace": "acme",
        "version": 1,
        "root": {"form": "auto", "policy": "small_ops"},
    }


_FIXTURES = [_finance_threshold, _customs_two_key, _single_approve, _plain_auto]
_IDS = ["conditional_seq", "quorum", "approve_person", "auto"]


# --- 1. round-trip trust contract, one per algebra form ----------------------------------------


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_parse_of_print_round_trips_to_equal_ast(fixture):
    ast = Strategy.model_validate(fixture())
    assert parse_strategy_nil(print_strategy_nil(ast)) == ast


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_printing_is_idempotent_for_canonical_text(fixture):
    canonical = print_strategy_nil(Strategy.model_validate(fixture()))
    assert print_strategy_nil(parse_strategy_nil(canonical)) == canonical


def test_worked_example_fields_survive_round_trip():
    ast = Strategy.model_validate(_finance_threshold())
    out = parse_strategy_nil(print_strategy_nil(ast))
    assert out.root.form == "conditional" and out.root.when == "amount < 5000"
    assert out.root.then.form == "auto" and out.root.then.policy == "small_ops"
    seq = out.root.else_
    assert seq.form == "seq" and len(seq.items) == 2
    manager = seq.items[0].unit
    assert manager.by == "role" and manager.name == "Manager"
    assert manager.timeout.after == "P2D" and manager.timeout.then.to == "Finance"
    finance = seq.items[1].unit
    assert finance.distinct_from == ("preparer",)
    assert out == ast


def test_route_less_timeout_parses_for_v9_to_refuse():
    """A deadline with no route is a GRAMMAR-legal shape — V9 refuses it as governance, so the
    editor can point at the unit instead of the parser crashing at the brace."""
    text = (
        "strategy Slow v1 {\n"
        '  workspace "acme"\n'
        "  approve(role: Manager, timeout: P2D)\n"
        "}\n"
    )
    ast = parse_strategy_nil(text)
    assert ast.root.unit.timeout.after == "P2D"
    assert ast.root.unit.timeout.then is None
    canonical = print_strategy_nil(ast)
    assert print_strategy_nil(parse_strategy_nil(canonical)) == canonical


def test_content_hash_is_stable_and_content_sensitive():
    a = Strategy.model_validate(_customs_two_key())
    b = Strategy.model_validate(dict(reversed(list(_customs_two_key().items()))))
    assert strategy_content_hash(a) == strategy_content_hash(b)
    changed = _customs_two_key()
    changed["root"]["k"] = 1
    assert strategy_content_hash(Strategy.model_validate(changed)) != strategy_content_hash(a)


# --- 2. reserved forms PARSE-REFUSE with V9_UNSUPPORTED_FORM ------------------------------------


@pytest.mark.parametrize("form", ["par", "weighted", "dynamic", "delegate", "override"])
def test_reserved_form_refuses_with_v9_code(form):
    text = f'strategy X v1 {{\n  workspace "acme"\n  {form}(whatever)\n}}\n'
    with pytest.raises(NilUnsupportedFormError) as exc:
        parse_strategy_nil(text)
    assert exc.value.code == "V9_UNSUPPORTED_FORM"
    assert exc.value.form == form
    assert form in exc.value.message and "reserved" in exc.value.message
    assert exc.value.line == 3  # points at the form, not the file start


def test_reserved_form_refuses_even_nested_inside_seq():
    text = 'strategy X v1 {\n  workspace "acme"\n  seq(approve(role: A), par(x))\n}\n'
    with pytest.raises(NilUnsupportedFormError) as exc:
        parse_strategy_nil(text)
    assert exc.value.code == "V9_UNSUPPORTED_FORM"


# --- 3. malformed input refuses with structured positions --------------------------------------


def test_unknown_form_is_a_plain_syntax_error():
    with pytest.raises(NilSyntaxError) as exc:
        parse_strategy_nil('strategy X v1 {\n  workspace "acme"\n  teleport(now)\n}\n')
    assert "unknown strategy form" in exc.value.message
    assert not isinstance(exc.value, NilUnsupportedFormError)


def test_bad_version_refuses():
    with pytest.raises(NilSyntaxError) as exc:
        parse_strategy_nil("strategy X 1 {\n}\n")
    assert "expected a version" in exc.value.message


def test_bad_duration_refuses_as_invalid_strategy():
    text = 'strategy X v1 {\n  workspace "acme"\n  approve(role: A, timeout: soon)\n}\n'
    with pytest.raises(NilSyntaxError) as exc:
        parse_strategy_nil(text)
    assert "invalid strategy" in exc.value.message


def test_conditional_without_else_refuses():
    text = 'strategy X v1 {\n  workspace "acme"\n  when "x > 1" -> auto(policy: p)\n}\n'
    with pytest.raises(NilSyntaxError):
        parse_strategy_nil(text)
