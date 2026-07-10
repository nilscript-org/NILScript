"""Auto-derive: adapter verbs -> fail-closed draft capabilities (plan B8+)."""

from __future__ import annotations

from nilscript.capability.derive import AUTO_PREFIX, derive_from_skeleton, synthesize_cycle


def test_derives_one_draft_per_uncovered_verb() -> None:
    sk = {"verbs": ["a.one", "b.two", "c.three"], "verb_details": []}
    derived = derive_from_skeleton("ws", sk, covered_verbs={"b.two"})
    ids = [d.wrapped.capability.capability_id for d in derived]
    assert ids == ["auto_a_one", "auto_c_three"]  # b.two skipped (already covered)


def test_undeclared_verb_floors_at_high_declared_is_honoured() -> None:
    sk = {"verbs": ["x.declared", "y.undeclared"], "verb_details": [{"verb": "x.declared", "tier": "MEDIUM"}]}
    by_id = {d.wrapped.capability.capability_id: d.wrapped.capability for d in derive_from_skeleton("ws", sk)}
    assert by_id["auto_x_declared"].risk == "MEDIUM"
    assert by_id["auto_y_undeclared"].risk == "HIGH"  # never guess — fail closed


def test_derived_capability_is_fail_closed_and_owner_gated() -> None:
    (d,) = derive_from_skeleton("ws", {"verbs": ["z.act"], "verb_details": []})
    cap = d.wrapped.capability
    assert cap.exposure.ai is False  # exposing is a deliberate governed act
    assert cap.implemented_by["default"] == "auto_z_act"
    assert d.wrapped.strategy.strategy_id == "auto_z_actApproval"


def test_synthesize_is_deterministic() -> None:
    a = synthesize_cycle("ws", "m.n")
    b = synthesize_cycle("ws", "m.n")
    assert a.model_dump() == b.model_dump()
    assert a.cycle_id == f"{AUTO_PREFIX}m_n"


def test_reads_verbs_from_verb_details_when_no_verbs_list() -> None:
    sk = {"verb_details": [{"verb": "only.here", "tier": "LOW"}]}
    (d,) = derive_from_skeleton("ws", sk)
    assert d.wrapped.capability.capability_id == "auto_only_here"
    assert d.wrapped.capability.risk == "LOW"
