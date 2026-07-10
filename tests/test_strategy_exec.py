"""B3 — the strategy interpreter over signature-slot rows (Gate M3, interpreter layer).

Proves the MVP-5 algebra as a state machine over `strategy_signatures`: a two-key quorum commits
only at 2 DISTINCT signatures; the preparer's signature refuses (SOD_VIOLATION — a refusal, never
an exception); Seq materializes stepwise and a rejection anywhere cancels the rest; Conditional
routes by the prepared inputs through the kernel's OWN guard evaluator; Auto records a
``policy:<id>`` decision row and refuses above MEDIUM; a unit deadline escalates or rejects via
the same sweep clock as /automations/tick; a material edit voids collected signatures
(`superseded`) and re-holds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from nilscript.controlplane import strategy_exec as sx
from nilscript.controlplane.store import EventStore


def _store() -> EventStore:
    return EventStore(":memory:")


def _quorum(k: int = 2, *, distinct: bool = True) -> dict:
    return {
        "nil": "strategy/0.1",
        "strategy_id": "CustomsTwoKey",
        "workspace": "ws1",
        "version": 1,
        "root": {
            "form": "quorum",
            "k": k,
            "distinct": distinct,
            "of": [
                {"form": "approve", "unit": {"by": "role", "name": "Finance"}},
                {"form": "approve", "unit": {"by": "role", "name": "Admin"}},
            ],
        },
    }


def _seq(*, timeout: dict | None = None) -> dict:
    first: dict = {"by": "role", "name": "Manager"}
    if timeout is not None:
        first["timeout"] = timeout
    return {
        "nil": "strategy/0.1",
        "strategy_id": "TwoStep",
        "workspace": "ws1",
        "version": 1,
        "root": {
            "form": "seq",
            "items": [
                {"form": "approve", "unit": first},
                {"form": "approve", "unit": {"by": "role", "name": "Finance"}},
            ],
        },
    }


def _conditional() -> dict:
    return {
        "nil": "strategy/0.1",
        "strategy_id": "SmallOpsAuto",
        "workspace": "ws1",
        "version": 1,
        "root": {
            "form": "conditional",
            "when": "$.input.amount < 5000",
            "then": {"form": "auto", "policy": "small_ops"},
            "else": {"form": "approve", "unit": {"by": "role", "name": "Finance"}},
        },
    }


# ── quorum: one subject, k distinct signatures ────────────────────────────────────────────────


def test_two_key_collects_two_distinct_signatures_then_approves():
    s = _store()
    out = sx.begin(s, "x1", _quorum(), inputs={}, risk="HIGH", workspace="ws1")
    assert out["status"] == "pending"
    st = sx.state(s, "x1", _quorum(), inputs={})
    assert len(st["pending"]) == 2 and st["signed"] == []

    one = sx.sign(s, "x1", _quorum(), inputs={}, actor="rizgi", role="Finance",
                  prepared_by="agent-1")
    assert one["status"] == "pending"  # 1 of 2 — NOT approved yet
    two = sx.sign(s, "x1", _quorum(), inputs={}, actor="admin-b", role="Admin",
                  prepared_by="agent-1")
    assert two["status"] == "approved"
    st = sx.state(s, "x1", _quorum(), inputs={})
    assert st["signed"] == ["rizgi", "admin-b"] and st["status"] == "approved"


def test_same_actor_cannot_supply_both_quorum_signatures():
    s = _store()
    sx.begin(s, "x1", _quorum(), inputs={}, risk="HIGH", workspace="ws1")
    sx.sign(s, "x1", _quorum(), inputs={}, actor="rizgi", role="Finance", prepared_by="p")
    again = sx.sign(s, "x1", _quorum(), inputs={}, actor="rizgi", role="Admin", prepared_by="p")
    assert again["refusal"]["code"] == "DUPLICATE_SIGNATURE"
    assert sx.state(s, "x1", _quorum(), inputs={})["status"] == "pending"


def test_preparer_signature_refuses_with_sod_violation():
    s = _store()
    sx.begin(s, "x1", _quorum(), inputs={}, risk="HIGH", workspace="ws1")
    out = sx.sign(s, "x1", _quorum(), inputs={}, actor="agent-1", role="Finance",
                  prepared_by="agent-1")
    assert out["refusal"]["code"] == "SOD_VIOLATION"
    assert sx.state(s, "x1", _quorum(), inputs={})["signed"] == []  # nothing recorded


def test_distinct_from_role_violation_refuses():
    strategy = {
        "nil": "strategy/0.1", "strategy_id": "S", "workspace": "ws1", "version": 1,
        "root": {
            "form": "seq",
            "items": [
                {"form": "approve", "unit": {"by": "role", "name": "Manager"}},
                {"form": "approve",
                 "unit": {"by": "role", "name": "Finance", "distinct_from": ["Manager"]}},
            ],
        },
    }
    s = _store()
    sx.begin(s, "x1", strategy, inputs={}, risk="HIGH", workspace="ws1")
    sx.sign(s, "x1", strategy, inputs={}, actor="rizgi", role="Manager", prepared_by="p")
    # rizgi signed as Manager; the Finance unit demands an identity distinct from Manager's.
    out = sx.sign(s, "x1", strategy, inputs={}, actor="rizgi", role="Finance", prepared_by="p")
    assert out["refusal"]["code"] == "SOD_VIOLATION"


def test_rejection_by_any_listed_unit_rejects_the_whole_subject():
    s = _store()
    sx.begin(s, "x1", _quorum(), inputs={}, risk="HIGH", workspace="ws1")
    sx.sign(s, "x1", _quorum(), inputs={}, actor="rizgi", role="Finance", prepared_by="p")
    out = sx.sign(s, "x1", _quorum(), inputs={}, actor="admin-b", role="Admin",
                  decision="rejected", prepared_by="p")
    assert out["status"] == "rejected"
    assert sx.state(s, "x1", _quorum(), inputs={})["status"] == "rejected"
    # Nothing left live to sign — a late signature refuses as already decided.
    late = sx.sign(s, "x1", _quorum(), inputs={}, actor="c", role="Finance", prepared_by="p")
    assert late["refusal"]["code"] == "ALREADY_DECIDED"


# ── seq: stepwise materialization (the dependent-plan grammar) ────────────────────────────────


def test_seq_materializes_item_n_plus_1_only_on_item_n_approval():
    s = _store()
    sx.begin(s, "x1", _seq(), inputs={}, risk="HIGH", workspace="ws1")
    st = sx.state(s, "x1", _seq(), inputs={})
    assert [u["name"] for u in st["pending"]] == ["Manager"]  # stage 1 NOT yet actionable
    # Signing stage 1 before it is held refuses — the slot is planned, not pending.
    early = sx.sign(s, "x1", _seq(), inputs={}, actor="fin", role="Finance", prepared_by="p")
    assert early["refusal"]["code"] == "NO_PENDING_UNIT"
    out = sx.sign(s, "x1", _seq(), inputs={}, actor="mgr", role="Manager", prepared_by="p")
    assert out["status"] == "pending"
    st = sx.state(s, "x1", _seq(), inputs={})
    assert [u["name"] for u in st["pending"]] == ["Finance"]  # materialized stepwise
    out = sx.sign(s, "x1", _seq(), inputs={}, actor="fin", role="Finance", prepared_by="p")
    assert out["status"] == "approved"


def test_seq_rejection_cancels_the_rest():
    s = _store()
    sx.begin(s, "x1", _seq(), inputs={}, risk="HIGH", workspace="ws1")
    out = sx.sign(s, "x1", _seq(), inputs={}, actor="mgr", role="Manager",
                  decision="rejected", prepared_by="p")
    assert out["status"] == "rejected"
    slots = {r["unit_key"]: r["status"] for r in s.signature_slots("x1")}
    assert slots["s0.a"] == "rejected" and slots["s1.a"] == "cancelled"  # no orphan


# ── conditional: routed by the prepared inputs, kernel guard evaluator ────────────────────────


def test_conditional_small_amount_routes_to_auto_and_records_policy_decision():
    s = _store()
    out = sx.begin(s, "x1", _conditional(), inputs={"amount": 1200}, risk="MEDIUM",
                   workspace="ws1")
    assert out["status"] == "approved" and out["branch"] == "then"
    slots = s.signature_slots("x1")
    assert len(slots) == 1 and slots[0]["actor"] == "policy:small_ops"
    assert slots[0]["status"] == "signed"  # the decision row, actor "policy:<id>"


def test_conditional_large_amount_routes_to_the_human_gate():
    s = _store()
    out = sx.begin(s, "x1", _conditional(), inputs={"amount": 9000}, risk="MEDIUM",
                   workspace="ws1")
    assert out["status"] == "pending" and out["branch"] == "else"
    st = sx.state(s, "x1", _conditional(), inputs={"amount": 9000})
    assert [u["name"] for u in st["pending"]] == ["Finance"]


def test_conditional_that_cannot_evaluate_refuses_fail_closed():
    s = _store()
    out = sx.begin(s, "x1", _conditional(), inputs={}, risk="MEDIUM", workspace="ws1")
    assert out["refusal"]["code"] == "CONDITION_UNRESOLVED"
    assert s.signature_slots("x1") == []  # nothing materialized on a refusal


# ── auto: lawful only at ≤ MEDIUM ─────────────────────────────────────────────────────────────


def test_auto_refuses_above_medium_risk_at_runtime():
    strategy = {
        "nil": "strategy/0.1", "strategy_id": "A", "workspace": "ws1", "version": 1,
        "root": {"form": "auto", "policy": "small_ops"},
    }
    s = _store()
    out = sx.begin(s, "x1", strategy, inputs={}, risk="HIGH", workspace="ws1")
    assert out["refusal"]["code"] == "V9_AUTO_FORBIDDEN"
    ok = sx.begin(s, "x2", strategy, inputs={}, risk="MEDIUM", workspace="ws1")
    assert ok["status"] == "approved"


# ── timeouts: the tick sweep (parked_runs deadline pattern) ───────────────────────────────────


def test_timeout_escalates_to_the_declared_role_via_the_sweep():
    strategy = _seq(timeout={"after": "P2D", "then": {"kind": "escalate", "to": "Director"}})
    s = _store()
    past = datetime.now(UTC) - timedelta(days=3)  # held 3 days ago; P2D deadline has passed
    sx.begin(s, "x1", strategy, inputs={}, risk="HIGH", workspace="ws1", now=past)
    actions = sx.sweep_due(s, now=datetime.now(UTC))
    assert actions == [{"execution_id": "x1", "unit_idx": 0, "action": "escalated",
                        "to": "Director"}]
    st = sx.state(s, "x1", strategy, inputs={})
    assert st["status"] == "pending"
    assert [u["name"] for u in st["pending"]] == ["Director"]  # re-addressed, same unit
    # The Director's signature satisfies the escalated unit and advances the Seq.
    out = sx.sign(s, "x1", strategy, inputs={}, actor="dir", role="Director", prepared_by="p")
    assert out["status"] == "pending"
    assert [u["name"] for u in sx.state(s, "x1", strategy, inputs={})["pending"]] == ["Finance"]
    # The sweep is idempotent — the escalated slot never fires twice.
    assert sx.sweep_due(s, now=datetime.now(UTC)) == []


def test_timeout_reject_route_rejects_the_whole_subject():
    strategy = _seq(timeout={"after": "PT1H", "then": {"kind": "reject"}})
    s = _store()
    past = datetime.now(UTC) - timedelta(hours=2)
    sx.begin(s, "x1", strategy, inputs={}, risk="HIGH", workspace="ws1", now=past)
    actions = sx.sweep_due(s, now=datetime.now(UTC))
    assert actions[0]["action"] == "rejected"
    assert sx.state(s, "x1", strategy, inputs={})["status"] == "rejected"
    slots = {r["unit_key"]: r["status"] for r in s.signature_slots("x1")}
    assert slots["s1.a"] == "cancelled"  # the rest of the Seq is cancelled, no orphan


def test_undue_deadlines_do_not_sweep():
    strategy = _seq(timeout={"after": "P2D", "then": {"kind": "escalate", "to": "Director"}})
    s = _store()
    sx.begin(s, "x1", strategy, inputs={}, risk="HIGH", workspace="ws1")
    assert sx.sweep_due(s, now=datetime.now(UTC)) == []


# ── material edits: void + re-hold ────────────────────────────────────────────────────────────


def test_rehold_voids_collected_signatures_and_reholds_the_units():
    s = _store()
    sx.begin(s, "x1", _quorum(), inputs={}, risk="HIGH", workspace="ws1")
    sx.sign(s, "x1", _quorum(), inputs={}, actor="rizgi", role="Finance", prepared_by="p")
    out = sx.rehold(s, "x1", _quorum(), inputs={}, risk="HIGH", workspace="ws1")
    assert out["status"] == "pending" and out["superseded"] == 1
    # The voided signature stays on the audit trail; both units are re-held fresh.
    slots = s.signature_slots("x1")
    voided = [r for r in slots if r["status"] == "superseded"]
    assert len(voided) == 1 and voided[0]["actor"] == "rizgi"
    st = sx.state(s, "x1", _quorum(), inputs={})
    assert st["signed"] == [] and len(st["pending"]) == 2
    # rizgi may sign the EDITED subject again — the void was about the old content.
    assert sx.sign(s, "x1", _quorum(), inputs={}, actor="rizgi", role="Finance",
                   prepared_by="p")["status"] == "pending"


def test_rehold_reroutes_a_conditional_when_the_edit_flips_the_guard():
    s = _store()
    sx.begin(s, "x1", _conditional(), inputs={"amount": 9000}, risk="MEDIUM", workspace="ws1")
    sx.sign(s, "x1", _conditional(), inputs={"amount": 9000}, actor="fin", role="Finance",
            prepared_by="p")
    # The edit drops the amount below the threshold → the auto branch now governs.
    out = sx.rehold(s, "x1", _conditional(), inputs={"amount": 1200}, risk="MEDIUM",
                    workspace="ws1")
    assert out["status"] == "approved" and out["branch"] == "then"
    assert out["superseded"] == 1


# ── duration parsing ──────────────────────────────────────────────────────────────────────────


def test_duration_seconds():
    assert sx.duration_seconds("P2D") == 172800
    assert sx.duration_seconds("PT1H") == 3600
    assert sx.duration_seconds("P1DT12H") == 129600
    assert sx.duration_seconds("PT0S") == 0
    assert sx.duration_seconds("garbage") == 0  # fail closed: immediate deadline
