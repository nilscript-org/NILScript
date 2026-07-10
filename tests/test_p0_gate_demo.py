"""THE P0 ACCEPTANCE GATE — one readable end-to-end demo, permanent in the suite.

Gate text (MVP-EXECUTION-PLAN.md, Gate P0 — quoted verbatim):

    "a 3-step cycle (query → HIGH write → notify) registered as a capability runs live
    end-to-end: card parks in Decisions with the exact payload preview, a two-key strategy
    demands two distinct approvers, approval commits and resumes the run, trigger replay
    does not double-write, a second workspace sees nothing, and `rollbackPhase()`
    compensates the write. All of it working **in mock mode with zero credentials**."

Every assertion below is tagged with the MVP/UBCA invariant it proves:

  I1 — Deterministic Permission Card: every human decision is a card assembled by code
       (exact payload preview, strategy state) parked in the Decisions feed — never prose.
  I2 — Approval algebra + SoD: a two-key `quorum(2, distinct)` demands two DISTINCT
       approvers, and the preparer is never an approver (SOD_VIOLATION).
  I3 — Approval drives execution: the strategy's satisfaction is the ONLY effect path;
       the commit fires exactly once and the owner's decision RESUMES the parked run.
  I4 — Idempotency: replaying the same trigger/idempotency key never double-writes.
  I5 — Tenancy fail-closed: a second workspace sees zero prepared/pending/run rows.
  I6 — Per-phase rollback: the reverse compensation chain after a checkpoint is held as
       ONE governed proposal; its approval compensates with `rb-{run}-{n}` keys.
  I7 — Mock-first: the whole walk runs against scripted in-process fakes — no network,
       no credentials (the registered adapter's bearer is never exercised).

Built from EXISTING infra only (the fixtures of test_gate_resume.py, test_prepared.py,
test_checkpoint_rollback.py): no new source code was needed — the prepare-plane commit
already fires the capability's default implementing cycle through the app runner
(`fire_manual`, idempotency key `prep:{prepared_id}`), and the run's HIGH write then parks
on the verb-tier gate whose decision resumes it. One honest sequencing note: today the
two-key card gates the FIRING of the run (its commit is the only effect path), and the
HIGH write inside the run parks on the SECOND, verb-tier gate — governance is layered, so
"parks on the HIGH write" happens after the two keys, not before.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi", reason="needs fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import nilscript.controlplane.app as cp_app  # noqa: E402
from nilscript.controlplane.app import create_app  # noqa: E402
from nilscript.controlplane.store import EventStore  # noqa: E402
from nilscript.kernel.executor import LocalExecutor  # noqa: E402
from nilscript.sdk.sentences import StatusBody  # noqa: E402

WS = "acme"
OTHER_WS = "rival"
SLUG = "issueinvoiceflow"  # cycle_slug("IssueInvoiceFlow")


# ── the 3-step cycle: query → checkpoint → HIGH write (with compensation) → notify ────────────
# The checkpoint marks the pre-write phase boundary — the rollback address for segment (9).


def _demo_cycle() -> dict:
    return {
        "nil": "cycle/0.3",  # the checkpoint step forces the v0.3 dialect
        "cycle_id": "IssueInvoiceFlow",
        "workspace": WS,
        "metadata": {"version": "1.0.0", "owner": "Finance"},
        "intent": {"ar": "إصدار فاتورة", "en": "Issue an invoice"},
        "trigger": {"type": "manual"},
        "context": [
            {"name": "customer", "entity_type": "Party"},
            {"name": "order", "entity_type": "Order"},
        ],
        "variables": [{"name": "order_no", "expression": "context.order"}],
        "flow": {
            "entry": "LookupCustomer",
            "steps": [
                {  # step_1 — the query (a read; commits nothing)
                    "id": "LookupCustomer", "type": "query",
                    "use": "crm.lookup_customer", "with": {"ref": "PO-7"},
                    "output": "party", "next": "PreWrite",
                },
                {  # step_2 — the compensation boundary (B5): the rollback address
                    "id": "PreWrite", "type": "checkpoint",
                    "name": "pre-write", "next": "WriteInvoice",
                },
                {  # step_3 — the HIGH write, with its declared inverse
                    "id": "WriteInvoice", "type": "action",
                    "use": "billing.create_invoice",
                    "with": {"customer_ref": "party.id", "order_ref": "order_no"},
                    "compensate": {"use": "billing.void_invoice",
                                   "with": {"order_ref": "PO-7"}},
                    "output": "invoice", "next": "Done",
                },
                {  # step_4 — the notify tail the resume must reach
                    "id": "Done", "type": "notify",
                    "message": {"ar": "صدرت الفاتورة", "en": "invoice issued"},
                },
            ],
        },
    }


def _two_key_strategy() -> dict:
    """The two-key upgrade of the wrapped strategy: quorum(2, distinct) over Finance+Admin."""
    return {
        "nil": "strategy/0.1",
        "strategy_id": "IssueInvoiceFlowApproval",  # wrap_cycle's derived id — a NEW version
        "workspace": WS,
        "version": 1,
        "root": {
            "form": "quorum", "k": 2, "distinct": True,
            "of": [
                {"form": "approve", "unit": {"by": "role", "name": "Finance"}},
                {"form": "approve", "unit": {"by": "role", "name": "Admin"}},
            ],
        },
    }


# ── mock mode, zero credentials (I7): every remote seam is a scripted in-process fake ─────────


class _MockAdapter:
    """The workspace's backend, scripted. Reads answer; the HIGH write's commit is HELD by the
    System (a proposal-shaped answer, not a status) — exactly the parked-commit wire behavior."""

    def __init__(self) -> None:
        self.queries: list[tuple[str, dict | None]] = []
        self.proposes: list[tuple[str, dict]] = []
        self.commits: list[tuple[str, str | None]] = []

    async def query(self, verb, args=None):
        self.queries.append((verb, args))
        return {"id": "C-77", "name": "ACME LLC"}

    async def propose(self, verb, args, *, session_id=None, request_timestamp=None):
        self.proposes.append((verb, args))
        return SimpleNamespace(is_refusal=False, id=f"wp-{len(self.proposes):08d}", code=None)

    async def commit(self, proposal_id, *, idempotency_key=None):
        self.commits.append((proposal_id, idempotency_key))
        return SimpleNamespace(tier=SimpleNamespace(value="HIGH"))  # HELD → the run parks


class _MockStatus(StatusBody):
    pass


class _MockGateClient:
    """Fakes the control plane's OWN commits — the approved-proposal commit
    (`_execute_approved`) and the rollback compensation chain (`_execute_rollback`)."""

    proposes: list[tuple[str, dict]] = []
    commits: list[tuple[str, str | None]] = []

    def __init__(self, *a, **k):
        pass

    async def propose(self, verb, args, *, session_id=None, request_timestamp=None):
        _MockGateClient.proposes.append((verb, args))
        return SimpleNamespace(
            is_refusal=False, id=f"gp-{len(_MockGateClient.proposes):08d}",
            code=None, message=None,
        )

    async def commit(self, proposal_id, *, idempotency_key=None):
        _MockGateClient.commits.append((proposal_id, idempotency_key))
        return _MockStatus(
            proposal=proposal_id, state="executed", result={"entity": {"id": "INV-901"}}
        )


async def _aclose():
    return None


@pytest.fixture()
def gate(tmp_path, monkeypatch):
    """The whole control plane over one SQLite file, every remote seam mocked."""
    _MockGateClient.proposes = []
    _MockGateClient.commits = []
    monkeypatch.setattr(cp_app, "NilClient", _MockGateClient)
    monkeypatch.setattr(cp_app, "NilTransport", lambda *a, **k: SimpleNamespace(aclose=_aclose))

    store = EventStore(path=str(tmp_path / "p0.db"))
    store.register_adapter(WS, "billing", label="Billing ERP", url="https://billing/nil",
                           bearer="tok", system="billing")
    store.activate_adapter(WS, "billing")

    async def provider(workspace: str):
        # The live skeleton: declared verbs + tier metadata (the wrap's risk floor source).
        return {
            "reachable": True, "conformant": True, "targets": {},
            "verbs": ["crm.lookup_customer", "billing.create_invoice", "billing.void_invoice"],
            "verb_details": [
                {"verb": "crm.lookup_customer", "tier": "LOW"},
                {"verb": "billing.create_invoice", "tier": "HIGH"},
                {"verb": "billing.void_invoice", "tier": "HIGH"},
            ],
        }

    adapter = _MockAdapter()

    async def runner(plan, *, run_id, resume=None, input=None):
        return await LocalExecutor(adapter, run_id=run_id, session_id=run_id).execute(
            plan, resume=resume, input=input
        )

    client = TestClient(create_app(store, secret="", skeleton_provider=provider, runner=runner))
    return store, client, adapter


def test_p0_gate_demo_end_to_end(gate):
    store, client, adapter = gate

    # ── (1) register the cycle, arm it, wrap it as a capability, upgrade to two-key ──────────
    r = client.post("/cycles/register", json={"cycle": _demo_cycle(), "authored_by": "owner"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["definition"]["state"] == "pending_approval"  # registering is governed
    r = client.post(f"/automations/{WS}/{SLUG}/1/state",
                    json={"state": "active", "approved_by": "owner"})
    assert r.status_code == 200

    r = client.post("/capabilities/wrap", json={"workspace": WS, "cycle_id": "IssueInvoiceFlow"})
    assert r.status_code == 200 and r.json()["ok"] is True
    # I1/I2: risk derives from DECLARED verb tiers only — the HIGH write floors the capability.
    cap = store.get_capability(WS, "IssueInvoiceFlow")
    assert cap["body"]["risk"] == "HIGH"
    assert cap["body"]["implemented_by"] == {"default": "IssueInvoiceFlow"}

    # The owner upgrades the wrapped strategy to the two-key form (a NEW registry version of
    # the same strategy id — strategies are data; prepare pins the latest version).
    r = client.post("/strategies", json={"strategy": _two_key_strategy()})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["definition"]["version"] == 2  # v1 = wrap's single-approver, v2 = two-key

    # ── (2) prepare → the deterministic Permission Card with the EXACT payload preview ───────
    inputs = {"customer": "ACME LLC", "order": "PO-7"}
    r = client.post("/prepared", json={
        "workspace": WS, "capability_id": "IssueInvoiceFlow",
        "inputs": inputs, "prepared_by": "agent-nadia",
    })
    assert r.status_code == 200
    prepared = r.json()["prepared"]
    pid = prepared["prepared_id"]
    card = prepared["card"]
    assert card["inputs"] == inputs                       # I1: the EXACT payload preview
    assert card["risk"] == "HIGH"                         # I1: declared risk on the card
    state = card["strategy"]["state"]
    assert state["status"] == "pending"                   # I2: the two-key state is visible…
    assert state["stages"][0]["k"] == 2 and state["stages"][0]["distinct"] is True
    assert {u["name"] for u in state["pending"]} == {"Finance", "Admin"}  # …and names both keys
    # I1: the card PARKS in the Decisions feed (workspace-pinned).
    feed = client.get("/prepared", params={"workspace": WS}).json()["prepared"]
    assert [p["prepared_id"] for p in feed] == [pid]
    # I3: preparing fired NOTHING — no run, no adapter call.
    assert store.list_runs(WS, SLUG) == [] and adapter.proposes == []

    # ── (4) the preparer's own signature refuses — separation of duties ──────────────────────
    r = client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "agent-nadia", "role": "Finance", "status": "approved"})
    assert r.status_code == 403
    assert r.json()["refusal"]["code"] == "SOD_VIOLATION"  # I2: preparer ∉ approvers

    # ── (5) first key signs — 1 of 2: still parked in Decisions, still NO effect ─────────────
    r = client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "fin-omar", "role": "Finance", "status": "approved"})
    assert r.json()["status"] == "pending"                # I2: one key is not two
    assert store.list_runs(WS, SLUG) == [] and adapter.proposes == []  # I3: no effect yet
    # Forcing execute before quorum refuses — the strategy is the only way forward.
    r = client.post(f"/prepared/{pid}/execute", json={"workspace": WS})
    assert r.status_code == 409 and r.json()["refusal"]["code"] == "NOT_APPROVED"  # I3

    # ── (6) second DISTINCT key → the commit fires the run EXACTLY once… ──────────────────────
    r = client.post(f"/prepared/{pid}/sign", json={
        "workspace": WS, "actor": "admin-sara", "role": "Admin", "status": "approved"})
    body = r.json()
    assert body["status"] == "approved"
    assert body["execution"]["committed"] is True         # I3: strategy satisfied → commit
    run_id = body["execution"]["run_id"]
    assert run_id == f"{SLUG}:v1:prep:{pid}"              # I4: the run key IS the prep key

    # ── (3) …and the run parks ON the HIGH write, visible on the pending surface ─────────────
    run = store.get_run(run_id)
    assert run["state"] == "waiting_approval"             # I3: parked at the action boundary
    waiting = run["trace"]["waiting"]
    assert waiting == {"kind": "approval", "node": "step_3",
                       "proposal": "wp-00000001", "tier": "HIGH"}
    # The query ran (with the card's inputs bound into the args), the write was PROPOSED once
    # and its commit HELD — the mock backend performed no effect.
    assert adapter.queries == [("crm.lookup_customer", {"ref": "PO-7"})]
    assert adapter.proposes == [
        ("billing.create_invoice", {"customer_ref": "C-77", "order_ref": "PO-7"})]  # I1→I3
    assert len(adapter.commits) == 1                      # attempted once, answered HELD
    # The pre-write checkpoint marker persisted as a ROW even though the run is parked.
    marks = store.list_checkpoints(run_id)
    assert [m["name"] for m in marks] == ["pre-write"]    # I6: the rollback address exists
    # The gate registers the hold (as os-server does) → the write is on the Decisions surface.
    client.post("/proposals/wp-00000001/await", json={
        "verb": "billing.create_invoice", "tier": "HIGH", "workspace": WS})
    assert [p["proposal_id"] for p in store.pending(WS)] == ["wp-00000001"]  # I1: visible, pending

    # ── (6 cont.) the owner's approval commits the write ONCE and RESUMES the run ────────────
    decided = client.post("/proposals/wp-00000001/decision", json={"status": "approved"}).json()
    assert decided["execution"]["executed"] is True
    assert decided["resumed"] == [
        {"run_id": run_id, "node_id": "step_3", "resumed": True, "state": "completed"}]  # I3
    assert [c[0] for c in _MockGateClient.commits] == ["wp-00000001"]  # I3: exactly ONE commit
    final = store.get_run(run_id)
    assert final["state"] == "completed"
    out = final["trace"]["context"]["step_3"]["output"]
    assert out["proposal"] == "wp-00000001" and out["state"] == "executed"
    assert out["committed_id"] == "INV-901"               # I3: committed result in the trace
    assert final["trace"]["notifications"] == [
        {"ar": "صدرت الفاتورة", "en": "invoice issued"}]   # I3: the run resumed TO the notify

    # ── (7) trigger replay does NOT double-write ─────────────────────────────────────────────
    r = client.post(f"/prepared/{pid}/execute", json={"workspace": WS})
    assert r.status_code == 409
    assert r.json()["refusal"]["code"] == "ALREADY_COMMITTED"      # I4: settled subjects refuse
    r = client.post(f"/automations/{WS}/{SLUG}/run",
                    json={"idempotency_key": f"prep:{pid}"})
    assert r.status_code == 200 and r.json().get("replayed") is True  # I4: replay, not re-run
    assert len(adapter.proposes) == 1                     # I4: the write was proposed once…
    assert [c[0] for c in _MockGateClient.commits] == ["wp-00000001"]  # …and committed once, ever
    assert len(store.list_runs(WS, SLUG)) == 1            # I4: one run row, not two

    # ── (8) a second workspace sees NOTHING ──────────────────────────────────────────────────
    assert client.get("/prepared", params={"workspace": OTHER_WS}).json() == {"prepared": []}
    assert client.get(f"/prepared/{pid}", params={"workspace": OTHER_WS}).status_code == 404
    assert store.pending(OTHER_WS) == []                  # I5: no pending decisions
    assert store.list_runs(OTHER_WS, SLUG) == []          # I5: no run rows
    r = client.post(f"/runs/{run_id}/rollback",
                    json={"to_checkpoint": "pre-write", "workspace": OTHER_WS})
    assert r.status_code == 404                           # I5: another tenant's run id = missing

    # ── (9) rollback to the checkpoint: ONE held proposal, then compensation with rb- keys ───
    r = client.post(f"/runs/{run_id}/rollback",
                    json={"to_checkpoint": "pre-write", "workspace": WS})
    assert r.status_code == 200 and r.json()["ok"] is True
    rb_pid = r.json()["proposal_id"]
    assert rb_pid == f"rb:{run_id}:pre-write"
    steps = r.json()["rollback"]["steps"]
    assert steps == [{                                     # I6: the write's OWN declared inverse
        "seq": 0, "node": "step_3", "verb": "billing.void_invoice",
        "args": {"order_ref": "PO-7"}, "idempotency_key": f"rb-{run_id}-0",
    }]
    # Preview only: NOTHING compensated yet; the plan is ONE governed proposal on the feed.
    assert [c[0] for c in _MockGateClient.commits] == ["wp-00000001"]     # I6: held, not fired
    assert [p["proposal_id"] for p in store.pending(WS)] == [rb_pid]

    decided = client.post(f"/proposals/{rb_pid}/decision", json={"status": "approved"}).json()
    execution = decided["execution"]
    assert execution["executed"] is True, decided
    assert execution["rolled_back_to"] == "pre-write"     # I6: approval compensates the write
    assert [c["node"] for c in execution["compensated"]] == ["step_3"]
    assert _MockGateClient.proposes[-1] == ("billing.void_invoice", {"order_ref": "PO-7"})
    assert _MockGateClient.commits[-1][1] == f"rb-{run_id}-0"      # I6: the rb- key
    # A re-delivered approval never double-compensates.
    again = client.post(f"/proposals/{rb_pid}/decision", json={"status": "approved"}).json()
    assert again["ok"] is False                           # I4/I6: the decision is settled
    assert _MockGateClient.commits[-1][1] == f"rb-{run_id}-0" and \
        len(_MockGateClient.commits) == 2                 # write + one compensation, no more
