"""`checkpoint` step + per-phase rollback (CAPABILITY-SHIFT plan A3 + B5, Gate M5).

The step is ADDITIVE on the one v0.3 seam (a checkpoint step ⇒ cycle/0.3; v0.2 stays frozen).
Walking it emits a ROW-BACKED ledger marker (run_checkpoints: {run_id, name, at, committed
snapshot}) with NO pause. `POST /runs/{id}/rollback {to_checkpoint}` builds the REVERSE
compensation chain of every write committed AFTER the marker — each step's own `compensate_with`,
the same declared inverse the kernel saga unwind executes — held as ONE governed proposal; the
owner's approval commits the compensations in reverse order with `rb-{run_id}-{n}` idempotency
keys. A committed write with no compensation refuses honestly (IRREVERSIBLE_SEGMENT).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nilscript.cycle import Cycle, compile_cycle, parse_nil, print_nil
from nilscript.kernel import ValidationContext, validate
from nilscript.kernel.context import SkillSpec
from nilscript.kernel.executor import LocalExecutor, looks_committed
from nilscript.sdk.sentences import StatusBody

pytest.importorskip("fastapi", reason="the control-plane tests need fastapi extras")

from fastapi.testclient import TestClient  # noqa: E402

import nilscript.controlplane.app as cp_app  # noqa: E402
from nilscript.automation.dispatch import fire_manual  # noqa: E402
from nilscript.controlplane.app import create_app  # noqa: E402
from nilscript.controlplane.store import EventStore  # noqa: E402

# ── fixtures ───────────────────────────────────────────────────────────────────────────────────


def _checkpoint_cycle() -> dict:
    """Place an order, mark the phase boundary, then record the payment — the B5 shape."""
    return {
        "nil": "cycle/0.3",
        "cycle_id": "OrderFlow",
        "workspace": "acme",
        "metadata": {"version": "1.0.0", "owner": "Ops"},
        "intent": {"ar": "طلب", "en": "Order"},
        "trigger": {"type": "manual"},
        "flow": {
            "entry": "Place",
            "steps": [
                {"id": "Place", "type": "action", "use": "commerce.create_order",
                 "with": {"sku": "A-1"}, "output": "order", "next": "Phase1Done"},
                {"id": "Phase1Done", "type": "checkpoint", "name": "order-placed",
                 "next": "Track"},
                {"id": "Track", "type": "notify",
                 "message": {"ar": "تتبع", "en": "tracking"}},
            ],
        },
    }


def _ctx() -> ValidationContext:
    verbs = frozenset(
        {
            "commerce.create_order",
            "commerce.record_payment",
            "commerce.reserve_stock",
        }
    )
    return ValidationContext(
        skills={"commerce": SkillSpec(required_verbs=verbs, hint_schema={})},
        read_verbs=frozenset(),
        workspaces={"acme": frozenset({"commerce.*"}), "ws1": frozenset({"commerce.*"})},
    )


# The IR plan: write → checkpoint → two more writes (all with declared inverses).
def _plan(*, comp3: bool = True, comp4: bool = True) -> dict:
    def action(nid, verb, args, comp, nxt):
        node = {"id": nid, "type": "action", "skill": verb.split(".")[0], "verb": verb,
                "args": args, "next": nxt}
        if comp is not None:
            node["compensate_with"] = comp
        return node

    return {
        "wosool": "0.1",
        "workspace": "ws1",
        "entry": "step_1",
        "pipeline": [
            action("step_1", "commerce.create_order", {"sku": "A-1"},
                   {"verb": "commerce.cancel_order", "args": {"ref": "$.step_1.output.proposal"}},
                   "step_2"),
            {"id": "step_2", "type": "checkpoint", "name": "order-placed", "next": "step_3"},
            action("step_3", "commerce.record_payment", {"amount": 5},
                   {"verb": "commerce.process_refund",
                    "args": {"ref": "$.step_3.output.proposal"}} if comp3 else None,
                   "step_4"),
            action("step_4", "commerce.reserve_stock", {"sku": "A-1"},
                   {"verb": "commerce.release_stock",
                    "args": {"sku": "A-1"}} if comp4 else None,
                   None),
        ],
    }


class _CommitClient:
    """A NIL client whose every propose commits cleanly — records the commit order + keys."""

    def __init__(self) -> None:
        self.commits: list[tuple[str, str | None]] = []

    async def propose(self, verb, args, *, session_id=None, request_timestamp=None):
        pid = f"p-{verb.replace('.', '-')}-0001"
        return SimpleNamespace(is_refusal=False, id=pid, code=None)

    async def commit(self, proposal_id, *, idempotency_key=None):
        self.commits.append((proposal_id, idempotency_key))
        return StatusBody(proposal=proposal_id, state="executed")


def _runner(client: _CommitClient):
    async def runner(plan, *, run_id, resume=None, input=None):
        return await LocalExecutor(client, run_id=run_id).execute(
            plan, resume=resume, input=input
        )

    return runner


# ── 1. the .nil surface: bijection + dialect + uniqueness ─────────────────────────────────────


def test_round_trip_parse_of_print_is_identity():
    ast = Cycle.model_validate(_checkpoint_cycle())
    assert parse_nil(print_nil(ast)) == ast


def test_printing_is_idempotent_for_canonical_text():
    canonical = print_nil(Cycle.model_validate(_checkpoint_cycle()))
    assert print_nil(parse_nil(canonical)) == canonical


def test_task_grammar_snippet_parses():
    text = (
        "cycle OrderFlow triggers manual {\n"
        '  workspace "acme"\n'
        '  intent "order"\n'
        '  meta { version: "1.0.0"; owner: "Ops" }\n'
        "  flow entry Phase1Done {\n"
        '    step Phase1Done { checkpoint "order-placed" next Track }\n'
        "    step Track { notify \"tracking\" }\n"
        "  }\n"
        "}\n"
    )
    cycle = parse_nil(text)
    assert cycle.nil == "cycle/0.3"  # a checkpoint step forces the v0.3 dialect
    step = cycle.flow.steps[0]
    assert step.type == "checkpoint" and step.name == "order-placed" and step.next == "Track"


def test_checkpoint_is_refused_in_the_frozen_02_dialect():
    raw = _checkpoint_cycle()
    raw["nil"] = "cycle/0.2"
    with pytest.raises(ValueError, match="cycle/0.3"):
        Cycle.model_validate(raw)


def test_duplicate_checkpoint_names_are_refused():
    raw = _checkpoint_cycle()
    raw["flow"]["steps"][1]["next"] = "Again"
    raw["flow"]["steps"].insert(
        2, {"id": "Again", "type": "checkpoint", "name": "order-placed", "next": "Track"}
    )
    with pytest.raises(ValueError, match="duplicate checkpoint names"):
        Cycle.model_validate(raw)


def test_compile_lowers_checkpoint_to_its_ir_node():
    result = compile_cycle(Cycle.model_validate(_checkpoint_cycle()), _ctx())
    assert result.ok, result.diagnostics
    node = result.program.nodes["step_2"]
    assert node.type == "checkpoint" and node.name == "order-placed" and node.next == "step_3"
    assert validate(_plan(), _ctx()).ok  # the IR node passes V1–V6 unchanged


# ── 2. runtime: the marker row, no pause ───────────────────────────────────────────────────────


async def test_walking_a_checkpoint_snapshots_committed_and_continues():
    client = _CommitClient()
    result = await LocalExecutor(client, run_id="r1").execute(_plan())
    assert result.completed  # no pause — control continued to step_3/step_4
    assert len(result.checkpoints) == 1
    marker = result.checkpoints[0]
    assert marker["name"] == "order-placed" and marker["node"] == "step_2"
    assert marker["committed"] == ["step_1"]  # only the pre-checkpoint write
    assert marker["at"]
    assert result.context["step_2"]["output"] == {"name": "order-placed"}
    assert looks_committed(result.context["step_3"]["output"])


def _armed_store(tmp_path, plan, name="cp.db"):
    store = EventStore(path=str(tmp_path / name))
    store.register_automation(
        workspace="ws1", automation_id="order-flow", content_hash="h1",
        name={"ar": "طلب", "en": "Order"}, plan=plan, trigger={"type": "manual"},
        state="active",
    )
    return store


async def _fire(store, client) -> str:
    out = await fire_manual(
        store, workspace="ws1", automation_id="order-flow",
        idempotency_key="fire-1", runner=_runner(client),
    )
    assert out["ok"] and out["run"]["state"] == "completed"
    return out["run"]["run_id"]


async def test_marker_rows_are_written_row_backed(tmp_path):
    store = _armed_store(tmp_path, _plan())
    run_id = await _fire(store, _CommitClient())
    rows = store.list_checkpoints(run_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "order-placed" and row["node_id"] == "step_2"
    assert row["committed"] == ["step_1"] and row["workspace"] == "ws1" and row["at"]
    # A "restart": a fresh store handle over the same file still sees the marker (a row, not RAM).
    assert EventStore(path=str(tmp_path / "cp.db")).get_checkpoint(run_id, "order-placed")


# ── 3. rollback: preview → one governed proposal → approval commits in reverse ────────────────


async def _aclose():
    return None


_CP_PROPOSES: list[tuple[str, dict]] = []
_CP_COMMITS: list[tuple[str, str | None]] = []


class _FakeCPClient:
    """Fakes the control plane's rollback commits (`_execute_rollback`), recording order/keys."""

    def __init__(self, *a, **k):
        pass

    async def propose(self, verb, args, *, session_id=None, request_timestamp=None):
        _CP_PROPOSES.append((verb, args))
        return SimpleNamespace(
            is_refusal=False, id=f"cpp-{len(_CP_PROPOSES):04d}", code=None, message=None
        )

    async def commit(self, proposal_id, *, idempotency_key=None):
        _CP_COMMITS.append((proposal_id, idempotency_key))
        return SimpleNamespace(state="executed")


def _make(tmp_path, monkeypatch, plan):
    _CP_PROPOSES.clear()
    _CP_COMMITS.clear()
    monkeypatch.setattr(cp_app, "NilClient", _FakeCPClient)
    monkeypatch.setattr(
        cp_app, "NilTransport", lambda *a, **k: SimpleNamespace(aclose=_aclose)
    )
    store = _armed_store(tmp_path, plan)
    store.register_adapter("ws1", "shop", url="https://shop/nil", bearer="tok", system="shop")
    store.activate_adapter("ws1", "shop")

    async def provider(workspace: str):
        return {"reachable": True, "conformant": True, "verbs": [], "targets": {}}

    client = TestClient(
        create_app(store, secret="", skeleton_provider=provider, runner=_runner(_CommitClient()))
    )
    return store, client


async def test_rollback_preview_lists_the_reverse_chain(tmp_path, monkeypatch):
    store, client = _make(tmp_path, monkeypatch, _plan())
    run_id = await _fire(store, _CommitClient())
    r = client.post(
        f"/runs/{run_id}/rollback", json={"to_checkpoint": "order-placed", "workspace": "ws1"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["proposal_id"] == f"rb:{run_id}:order-placed"
    steps = body["rollback"]["steps"]
    # REVERSE commit order, post-checkpoint segment ONLY (step_1 stays committed).
    assert [s["node"] for s in steps] == ["step_4", "step_3"]
    assert [s["verb"] for s in steps] == ["commerce.release_stock", "commerce.process_refund"]
    assert [s["idempotency_key"] for s in steps] == [f"rb-{run_id}-0", f"rb-{run_id}-1"]
    # references resolved against the persisted trace — literal args on the card
    assert steps[1]["args"] == {"ref": "p-commerce-record_payment-0001"}
    assert _CP_COMMITS == []  # preview only: NOTHING committed yet
    # one governed proposal, visible on the normal pending feed
    pending = store.pending("ws1")
    assert [p["proposal_id"] for p in pending] == [f"rb:{run_id}:order-placed"]
    assert pending[0]["verb"] == "run.rollback" and pending[0]["tier"] == "HIGH"


async def test_re_requesting_the_preview_is_idempotent(tmp_path, monkeypatch):
    store, client = _make(tmp_path, monkeypatch, _plan())
    run_id = await _fire(store, _CommitClient())
    first = client.post(f"/runs/{run_id}/rollback", json={"to_checkpoint": "order-placed"})
    again = client.post(f"/runs/{run_id}/rollback", json={"to_checkpoint": "order-placed"})
    assert first.json()["proposal_id"] == again.json()["proposal_id"]
    assert len(store.pending("ws1")) == 1  # still ONE governed proposal


async def test_approval_commits_the_compensations_in_reverse_order(tmp_path, monkeypatch):
    store, client = _make(tmp_path, monkeypatch, _plan())
    run_id = await _fire(store, _CommitClient())
    proposal_id = client.post(
        f"/runs/{run_id}/rollback", json={"to_checkpoint": "order-placed"}
    ).json()["proposal_id"]
    decided = client.post(
        f"/proposals/{proposal_id}/decision", json={"status": "approved"}
    ).json()
    execution = decided["execution"]
    assert execution["executed"] is True
    assert execution["rolled_back_to"] == "order-placed"
    assert [c["node"] for c in execution["compensated"]] == ["step_4", "step_3"]
    assert [v for v, _ in _CP_PROPOSES] == [
        "commerce.release_stock", "commerce.process_refund"
    ]
    assert [key for _, key in _CP_COMMITS] == [f"rb-{run_id}-0", f"rb-{run_id}-1"]


async def test_re_approval_is_idempotent_never_double_compensates(tmp_path, monkeypatch):
    store, client = _make(tmp_path, monkeypatch, _plan())
    run_id = await _fire(store, _CommitClient())
    proposal_id = client.post(
        f"/runs/{run_id}/rollback", json={"to_checkpoint": "order-placed"}
    ).json()["proposal_id"]
    client.post(f"/proposals/{proposal_id}/decision", json={"status": "approved"})
    committed_once = list(_CP_COMMITS)
    again = client.post(f"/proposals/{proposal_id}/decision", json={"status": "approved"}).json()
    assert again["ok"] is False  # the decision is already made — nothing re-executes
    assert _CP_COMMITS == committed_once


# ── 4. honest refusals ─────────────────────────────────────────────────────────────────────────


async def test_irreversible_segment_refuses_listing_the_blocking_steps(tmp_path, monkeypatch):
    store, client = _make(tmp_path, monkeypatch, _plan(comp3=False))
    run_id = await _fire(store, _CommitClient())
    r = client.post(f"/runs/{run_id}/rollback", json={"to_checkpoint": "order-placed"})
    assert r.status_code == 409
    refusal = r.json()["refusal"]
    assert refusal["code"] == "IRREVERSIBLE_SEGMENT"
    assert refusal["blocking_steps"] == ["step_3"]
    assert store.pending("ws1") == []  # refused — no proposal held, nothing to approve
    assert _CP_COMMITS == []


async def test_unknown_checkpoint_refuses(tmp_path, monkeypatch):
    store, client = _make(tmp_path, monkeypatch, _plan())
    run_id = await _fire(store, _CommitClient())
    r = client.post(f"/runs/{run_id}/rollback", json={"to_checkpoint": "no-such-marker"})
    assert r.status_code == 404
    assert r.json()["refusal"]["code"] == "UNKNOWN_CHECKPOINT"


async def test_rollback_is_workspace_pinned(tmp_path, monkeypatch):
    store, client = _make(tmp_path, monkeypatch, _plan())
    run_id = await _fire(store, _CommitClient())
    r = client.post(
        f"/runs/{run_id}/rollback", json={"to_checkpoint": "order-placed", "workspace": "ws2"}
    )
    assert r.status_code == 404  # another tenant's run id is indistinguishable from a missing one


def test_unknown_run_refuses(tmp_path, monkeypatch):
    _store, client = _make(tmp_path, monkeypatch, _plan())
    r = client.post("/runs/no-such-run/rollback", json={"to_checkpoint": "order-placed"})
    assert r.status_code == 404


# ── 5. V7 (d) ties the two items together: a checkpoint IS compensation coverage ──────────────


def test_checkpoint_counts_as_v7_compensation_coverage():
    from nilscript.capability import Capability, validate_implements

    raw = _checkpoint_cycle()
    raw["implements"] = {"capability_id": "PlaceOrder", "version": "1.0"}
    capability = Capability.model_validate({
        "nil": "capability/0.1",
        "capability_id": "PlaceOrder",
        "workspace": "acme",
        "version": "1.0",
        "domain": "Ops",
        "owner_role": "Ops",
        "intent": {"ar": "طلب", "en": "Order"},
        "risk": "MEDIUM",
        "strategy": "OwnerApproval",
        "compensation": "CancelOrder",
        "implemented_by": {"default": "OrderFlow"},
    })
    # `Place` declares no compensate, but the checkpoint boundary provides the B5 coverage.
    assert validate_implements(Cycle.model_validate(raw), capability).ok
