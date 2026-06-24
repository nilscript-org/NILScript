"""State-witness (TOCTOU) — bind a proposal to the SSOT state it previewed, recheck at commit.

A delayed approval can land against a world that changed between propose and commit. The witness is
a canonical hash of the fields the write will touch, captured at propose and re-captured at commit;
a drift fails closed (PRECONDITION_FAILED) instead of writing against stale reality. Pure given the
state snapshot, so the helper is unit-tested without a backend; adapters supply the snapshot.
"""

from nilscript.sdk.witness import compute_witness, witness_changed


def test_same_state_same_witness():
    a = compute_witness({"country_id": 224, "name": "AHMED"})
    b = compute_witness({"name": "AHMED", "country_id": 224})  # order-independent
    assert a == b and a != ""


def test_changed_value_changes_witness():
    before = compute_witness({"stage_id": 1})
    after = compute_witness({"stage_id": 2})
    assert before != after


def test_empty_state_is_no_precondition():
    # A create (no prior record) has no state to bind — witness is empty and never blocks.
    assert compute_witness({}) == ""
    assert witness_changed("", "anything") is False


def test_witness_changed_detects_drift():
    bound = compute_witness({"stage_id": 1})
    current_same = compute_witness({"stage_id": 1})
    current_drifted = compute_witness({"stage_id": 2})
    assert witness_changed(bound, current_same) is False
    assert witness_changed(bound, current_drifted) is True


def test_empty_bound_never_blocks_even_if_current_present():
    # No witness was bound at propose (e.g. create) → commit must not be blocked.
    assert witness_changed("", compute_witness({"x": 1})) is False
