"""V9 strategy well-formedness — every rule tested in BOTH directions (§A4-V9).

Each rule gets a violating strategy (the refusal, with its code and location) and a passing
sibling (no diagnostics) — refusals are answers: `validate_strategy` returns the kernel's
structured `ValidationResult`, it never raises.
"""

from __future__ import annotations

from nilscript.capability import Capability
from nilscript.strategy import Strategy, validate_strategy


def _capability(**overrides) -> Capability:
    raw = {
        "nil": "capability/0.1",
        "capability_id": "IssueInvoice",
        "workspace": "acme",
        "version": "1.0",
        "domain": "Finance",
        "owner_role": "Finance",
        "intent": {"ar": "فاتورة", "en": "Invoice"},
        "risk": "MEDIUM",
        "strategy": "FinanceThreshold",
        "sod": {"preparer_not_approver": True},
        "implemented_by": {"default": "IssueInvoiceCycle"},
    }
    raw.update(overrides)
    return Capability.model_validate(raw)


def _strategy(root: dict) -> Strategy:
    return Strategy.model_validate(
        {
            "nil": "strategy/0.1",
            "strategy_id": "FinanceThreshold",
            "workspace": "acme",
            "version": 1,
            "root": root,
        }
    )


def _approve(name: str, *, distinct_from: list[str] | None = None, timeout: dict | None = None):
    unit: dict = {"by": "role", "name": name}
    if distinct_from is not None:
        unit["distinct_from"] = distinct_from
    if timeout is not None:
        unit["timeout"] = timeout
    return {"form": "approve", "unit": unit}


def _codes(result) -> list[str]:
    return [d.code for d in result.diagnostics]


# --- V9_SELF_APPROVAL ----------------------------------------------------------------------------


def test_self_approval_hole_refused_under_sod():
    strategy = _strategy({"form": "seq", "items": [_approve("Manager"), _approve("Finance")]})
    result = validate_strategy(strategy, _capability())
    assert not result.ok
    assert _codes(result) == ["V9_SELF_APPROVAL", "V9_SELF_APPROVAL"]
    assert result.diagnostics[0].location == "root.items[0]"
    assert "preparer" in result.diagnostics[0].message


def test_distinct_from_preparer_satisfies_sod():
    strategy = _strategy(
        {
            "form": "seq",
            "items": [
                _approve("Manager", distinct_from=["preparer"]),
                _approve("Finance", distinct_from=["preparer"]),
            ],
        }
    )
    assert validate_strategy(strategy, _capability()).ok


def test_sod_rule_needs_the_capability_context():
    """Without the owning capability the SoD rule cannot judge — capability-independent rules
    still run, but no self-approval finding is invented (fail closed happens at bind time)."""
    strategy = _strategy(_approve("Manager"))
    assert validate_strategy(strategy).ok


def test_no_sod_declared_means_no_self_approval_finding():
    capability = _capability(sod={"preparer_not_approver": False})
    assert validate_strategy(_strategy(_approve("Manager")), capability).ok


def test_quorum_members_are_checked_for_sod_too():
    strategy = _strategy({"form": "quorum", "k": 1, "of": [_approve("Finance")]})
    result = validate_strategy(strategy, _capability())
    assert _codes(result) == ["V9_SELF_APPROVAL"]
    assert result.diagnostics[0].location == "root.of[0]"


# --- V9_QUORUM_UNSATISFIABLE / V9_QUORUM_DISTINCT -------------------------------------------------


def test_quorum_k_beyond_offered_units_refused():
    strategy = _strategy({"form": "quorum", "k": 3, "of": [_approve("A"), _approve("B")]})
    result = validate_strategy(strategy)
    assert _codes(result) == ["V9_QUORUM_UNSATISFIABLE"]
    assert "3" in result.diagnostics[0].message


def test_quorum_k_equal_to_offered_units_is_satisfiable():
    strategy = _strategy(
        {"form": "quorum", "k": 2, "distinct": True, "of": [_approve("A"), _approve("B")]}
    )
    assert validate_strategy(strategy).ok


def test_distinct_quorum_over_duplicate_roles_refused():
    strategy = _strategy(
        {"form": "quorum", "k": 2, "distinct": True, "of": [_approve("A"), _approve("A")]}
    )
    result = validate_strategy(strategy)
    assert _codes(result) == ["V9_QUORUM_DISTINCT"]


def test_non_distinct_quorum_over_duplicate_roles_is_fine():
    strategy = _strategy(
        {"form": "quorum", "k": 2, "distinct": False, "of": [_approve("A"), _approve("A")]}
    )
    assert validate_strategy(strategy).ok


# --- V9_TIMEOUT_NO_ROUTE --------------------------------------------------------------------------


def test_timeout_without_route_refused():
    strategy = _strategy(_approve("Manager", timeout={"after": "P2D"}))
    result = validate_strategy(strategy)
    assert _codes(result) == ["V9_TIMEOUT_NO_ROUTE"]
    assert "P2D" in result.diagnostics[0].message


def test_timeout_with_escalate_route_passes():
    strategy = _strategy(
        _approve("Manager", timeout={"after": "P2D", "then": {"kind": "escalate", "to": "Finance"}})
    )
    assert validate_strategy(strategy).ok


def test_timeout_with_reject_route_passes():
    strategy = _strategy(_approve("Manager", timeout={"after": "P2D", "then": {"kind": "reject"}}))
    assert validate_strategy(strategy).ok


# --- V9_AUTO_FORBIDDEN ----------------------------------------------------------------------------


def test_auto_refused_when_capability_risk_above_medium():
    strategy = _strategy({"form": "auto", "policy": "small_ops"})
    for risk in ("HIGH", "CRITICAL"):
        result = validate_strategy(strategy, _capability(risk=risk))
        assert _codes(result) == ["V9_AUTO_FORBIDDEN"], risk
        assert risk in result.diagnostics[0].message


def test_auto_allowed_at_or_below_medium():
    strategy = _strategy({"form": "auto", "policy": "small_ops"})
    for risk in ("LOW", "MEDIUM"):
        assert validate_strategy(strategy, _capability(risk=risk)).ok, risk


def test_auto_inside_conditional_branch_is_still_caught():
    strategy = _strategy(
        {
            "form": "conditional",
            "when": "amount < 5000",
            "then": {"form": "auto", "policy": "small_ops"},
            "else": _approve("Finance", distinct_from=["preparer"]),
        }
    )
    result = validate_strategy(strategy, _capability(risk="HIGH"))
    assert "V9_AUTO_FORBIDDEN" in _codes(result)
    assert result.diagnostics[0].location == "root.then"


# --- multiple findings accumulate (refusal LISTS, not first-error) --------------------------------


def test_multiple_findings_accumulate_in_one_result():
    strategy = _strategy(
        {
            "form": "seq",
            "items": [
                _approve("Manager", timeout={"after": "P2D"}),  # no route + no distinct_from
                {"form": "quorum", "k": 5, "of": [_approve("A", distinct_from=["preparer"])]},
            ],
        }
    )
    result = validate_strategy(strategy, _capability())
    codes = _codes(result)
    assert "V9_SELF_APPROVAL" in codes
    assert "V9_TIMEOUT_NO_ROUTE" in codes
    assert "V9_QUORUM_UNSATISFIABLE" in codes
