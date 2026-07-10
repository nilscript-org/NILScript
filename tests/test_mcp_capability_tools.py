"""Gate M6 — the five-tool capability plane, end to end (plan B7, UBCA Part X).

The CapabilityTools HTTP client is backed by the REAL control-plane ASGI app (no network), so
this proves: MCP tool → CP endpoint → registry/contract/strategy → SSOT. The gate's acceptance:
an agent holding ONLY nil_discover/nil_inspect/nil_prepare/nil_execute/nil_schedule answers an
intent with catalog capabilities — zero raw verbs reach the model. Discovery is pure code and
FAIL CLOSED on exposure (published + exposure.ai only; draft/hidden never surface); an empty
shortlist is an honest answer, never a fallback to verbs; contract refusals and NOT_APPROVED
pass through as answers, never retried.
"""

from __future__ import annotations

import datetime as _dt

import httpx
import pytest

pytest.importorskip("fastapi", reason="needs fastapi")

from nilscript.controlplane.app import create_app  # noqa: E402
from nilscript.controlplane.store import EventStore  # noqa: E402
from nilscript.kernel.executor import RunResult  # noqa: E402
from nilscript.mcp.capability_tools import (  # noqa: E402
    EMPTY_DISCOVERY_MESSAGE,
    CapabilityTools,
    rank_capabilities,
)

WS = "acme"


def _capability(
    capability_id: str,
    *,
    domain: str = "Finance",
    intent_en: str = "Issue a customer invoice",
    intent_ar: str = "إصدار فاتورة عميل",
    aliases: tuple[str, ...] = (),
    examples: tuple[str, ...] = (),
    ai: bool = True,
    risk: str = "HIGH",
    strategy: str = "CustomsTwoKey",
) -> dict:
    return {
        "nil": "capability/0.1",
        "capability_id": capability_id,
        "workspace": WS,
        "version": "2.3",
        "domain": domain,
        "owner_role": "Finance",
        "intent": {"en": intent_en, "ar": intent_ar},
        "aliases": list(aliases),
        "examples": list(examples),
        "inputs": [
            {"name": "customer", "type": {"kind": "entity", "of": "Party"}, "required": True},
            {"name": "amount", "type": {"kind": "scalar", "of": "Money"}},
        ],
        "outputs": [{"name": "invoice", "type": {"kind": "entity", "of": "Invoice"}}],
        "risk": risk,
        "strategy": strategy,
        "compensation": "CancelInvoice",
        "requires": ["CustomerAccount"],
        "creates": ["Invoice"],
        "enables": ["CollectPayment"],
        "exposure": {"ai": ai, "roles": ["Finance"]},
        "implemented_by": {"default": "IssueInvoiceCycle"},
    }


def _store_capability(store: EventStore, cap_dict: dict, *, publish: bool = True) -> None:
    from nilscript.capability import Capability, capability_content_hash

    cap = Capability.model_validate(cap_dict)
    row = store.register_capability(
        workspace=WS,
        capability_id=cap.capability_id,
        content_hash=capability_content_hash(cap),
        body=cap.model_dump(by_alias=True, mode="json"),
    )
    if publish:
        store.set_capability_state(WS, cap.capability_id, row["version"], "published")


def _seed(store: EventStore) -> None:
    from nilscript.strategy import Strategy, strategy_content_hash

    _store_capability(
        store,
        _capability(
            "IssueInvoice",
            aliases=("bill the customer", "فوترة العميل"),
            examples=("invoice ACME for last month",),
        ),
    )
    _store_capability(
        store,
        _capability(
            "CustomerRefund",
            domain="Support",
            intent_en="Refund a customer payment",
            intent_ar="استرداد دفعة عميل",
        ),
    )
    # exposure fail-closed fixtures: a published-but-hidden and a draft capability, both with
    # the EXACT winning alias — neither may ever surface.
    _store_capability(
        store, _capability("HiddenBilling", ai=False, aliases=("bill the customer",))
    )
    _store_capability(
        store,
        _capability("DraftBilling", aliases=("bill the customer",)),
        publish=False,
    )
    _store_capability(
        store,
        _capability(
            "SmallRefund",
            intent_en="Refund a small amount",
            intent_ar="استرداد مبلغ صغير",
            risk="MEDIUM",
            strategy="AutoSmall",
        ),
    )
    for strat_dict in (
        {
            "nil": "strategy/0.1",
            "strategy_id": "CustomsTwoKey",
            "workspace": WS,
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
        },
        {
            "nil": "strategy/0.1",
            "strategy_id": "AutoSmall",
            "workspace": WS,
            "version": 1,
            "root": {"form": "auto", "policy": "small_ops"},
        },
    ):
        strat = Strategy.model_validate(strat_dict)
        store.register_strategy(
            workspace=WS,
            strategy_id=strat.strategy_id,
            content_hash=strategy_content_hash(strat),
            body=strat.model_dump(by_alias=True, mode="json"),
        )
    store.register_automation(
        workspace=WS,
        automation_id="issueinvoicecycle",
        content_hash="h1",
        name={"en": "Issue invoice"},
        plan={"workspace": WS, "pipeline": []},
        trigger={"type": "manual"},
        state="active",
        kind="cycle",
        source={"flow": {"steps": [{"id": "Create", "type": "action", "use": "odoo.invoice_create"}]}},
    )


class _Runs:
    def __init__(self) -> None:
        self.fired: list[dict] = []

    async def __call__(self, plan, *, run_id, resume=None, input=None):
        self.fired.append({"run_id": run_id, "input": input})
        return RunResult(completed=True, context={})


@pytest.fixture()
def plane(tmp_path):
    store = EventStore(str(tmp_path / "cp.db"))
    _seed(store)
    runs = _Runs()
    app = create_app(store, secret="", runner=runs)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cp")
    tools = CapabilityTools("http://cp", "", workspace=WS, client=client)
    return store, tools, client, runs


# ── nil_discover: ranking, exposure fail-closed, honest empty ─────────────────────────────────


async def test_discover_ranks_exact_alias_above_word_overlap(plane):
    _, tools, _, _ = plane
    out = await tools.discover("bill the customer")
    assert out["outcome"] == "matches"
    ids = [m["capability_id"] for m in out["matches"]]
    assert ids[0] == "IssueInvoice"  # exact alias beats mere word overlap
    assert out["matches"][0]["aliases_hit"] == ["bill the customer"]
    assert "CustomerRefund" in ids  # shares 'customer' with its intent — a lower match
    assert out["matches"][0]["risk"] == "HIGH"
    assert out["matches"][0]["strategy"] == "CustomsTwoKey"


async def test_discover_matches_arabic_aliases_and_intent(plane):
    _, tools, _, _ = plane
    out = await tools.discover("فوترة العميل")
    assert out["matches"][0]["capability_id"] == "IssueInvoice"
    assert out["matches"][0]["aliases_hit"] == ["فوترة العميل"]

    overlap = await tools.discover("إصدار فاتورة")
    assert overlap["matches"][0]["capability_id"] == "IssueInvoice"


async def test_discover_never_surfaces_draft_or_unexposed(plane):
    """Fail closed: HiddenBilling (ai:false) and DraftBilling (state=draft) carry the EXACT
    winning alias and STILL never appear."""
    _, tools, _, _ = plane
    out = await tools.discover("bill the customer")
    ids = {m["capability_id"] for m in out["matches"]}
    assert "HiddenBilling" not in ids and "DraftBilling" not in ids


async def test_discover_domain_filter(plane):
    _, tools, _, _ = plane
    out = await tools.discover("refund the customer", domain="Support")
    assert [m["capability_id"] for m in out["matches"]] == ["CustomerRefund"]


async def test_discover_empty_is_honest_never_falls_back_to_verbs(plane):
    _, tools, _, _ = plane
    out = await tools.discover("teleport the warehouse to mars")
    assert out == {"outcome": "empty", "matches": [], "message": EMPTY_DISCOVERY_MESSAGE}
    assert "do NOT fall back to raw verbs" in out["message"]


def test_rank_capabilities_is_deterministic_and_capped_at_eight():
    records = [
        {
            "capability_id": f"Cap{i:02d}",
            "version": 1,
            "state": "published",
            "body": {
                "version": "1.0",
                "domain": "Finance",
                "risk": "LOW",
                "strategy": "S",
                "intent": {"en": "ship the parcel", "ar": ""},
                "aliases": [],
                "examples": [],
                "exposure": {"ai": True, "roles": []},
            },
        }
        for i in range(12)
    ]
    ranked = rank_capabilities(records, "ship the parcel")
    assert len(ranked) == 8  # the shortlist is bounded whatever the catalog size
    # identical scores tie-break on capability_id — byte-deterministic order
    assert [r["capability_id"] for r in ranked] == [f"Cap{i:02d}" for i in range(8)]
    assert rank_capabilities(records, "ship the parcel") == ranked


# ── nil_inspect ───────────────────────────────────────────────────────────────────────────────


async def test_inspect_returns_the_full_contract(plane):
    _, tools, _, _ = plane
    out = await tools.inspect("IssueInvoice")
    assert out["capability_id"] == "IssueInvoice" and out["state"] == "published"
    assert len(out["content_hash"]) == 64
    d = out["definition"]
    assert [f["name"] for f in d["inputs"]] == ["customer", "amount"]
    assert d["inputs"][0]["required"] is True
    assert [f["name"] for f in d["outputs"]] == ["invoice"]
    assert d["requires"] == ["CustomerAccount"]
    assert d["creates"] == ["Invoice"] and d["enables"] == ["CollectPayment"]
    assert d["implemented_by"] == {"default": "IssueInvoiceCycle"}
    assert out["strategy"]["id"] == "CustomsTwoKey"
    assert out["strategy"]["root"]["form"] == "quorum" and out["strategy"]["root"]["k"] == 2


async def test_inspect_unknown_capability_passes_the_refusal_through(plane):
    _, tools, _, _ = plane
    out = await tools.inspect("Nope")
    assert out == {"error": "unknown capability"}


# ── nil_prepare ───────────────────────────────────────────────────────────────────────────────


async def test_prepare_returns_the_card_envelope(plane):
    _, tools, _, _ = plane
    out = await tools.prepare("IssueInvoice", {"customer": "ACME", "amount": 18400})
    prepared = out["prepared"]
    assert prepared["status"] == "pending" and len(prepared["card_hash"]) == 64
    assert prepared["card"]["inputs"] == {"customer": "ACME", "amount": 18400}
    assert prepared["card"]["prepared_by"] == "ai-agent"  # SoD: the agent can never sign this
    assert len(prepared["card"]["strategy"]["state"]["pending"]) == 2


async def test_prepare_contract_refusal_passes_through_with_field_lists(plane):
    _, tools, _, _ = plane
    out = await tools.prepare("IssueInvoice", {"amount": ["not", "scalar"], "ghost": 1})
    refusal = out["refusal"]
    assert out["ok"] is False and refusal["code"] == "INPUT_CONTRACT"
    assert refusal["missing"] == ["customer"]
    assert refusal["wrong_type"] == ["amount"]
    assert refusal["unknown"] == ["ghost"]


# ── nil_execute ───────────────────────────────────────────────────────────────────────────────


async def test_execute_not_approved_is_the_answer_never_retried(plane):
    _, tools, _, runs = plane
    pid = (await tools.prepare("IssueInvoice", {"customer": "ACME"}))["prepared"]["prepared_id"]
    out = await tools.execute(pid)
    assert out["ok"] is False and out["refusal"]["code"] == "NOT_APPROVED"
    assert out["answer"].startswith("awaiting signatures — a human must sign in Decisions")
    assert runs.fired == []  # zero effect without the humans


async def test_execute_commits_a_fully_approved_card(plane):
    _, tools, _, runs = plane
    pid = (await tools.prepare("SmallRefund", {"customer": "ACME"}))["prepared"]["prepared_id"]
    out = await tools.execute(pid)  # auto strategy at MEDIUM: approved, commit is lawful
    assert out["ok"] is True and out["execution"]["committed"] is True
    assert len(runs.fired) == 1


# ── nil_schedule ──────────────────────────────────────────────────────────────────────────────


async def test_schedule_happy_path_registers_a_pending_row(plane):
    store, tools, _, _ = plane
    pid = (await tools.prepare("IssueInvoice", {"customer": "ACME"}))["prepared"]["prepared_id"]
    when = (_dt.datetime.now(_dt.UTC) + _dt.timedelta(hours=2)).isoformat()
    out = await tools.schedule(pid, when)
    assert out["ok"] is True
    sched = out["scheduled"]
    assert sched["status"] == "pending" and sched["fire_at"] == when
    assert store.get_scheduled_execution(sched["schedule_id"])["prepared_id"] == pid


async def test_schedule_past_timestamp_refuses(plane):
    _, tools, _, _ = plane
    pid = (await tools.prepare("IssueInvoice", {"customer": "ACME"}))["prepared"]["prepared_id"]
    out = await tools.schedule(pid, "2020-01-01T00:00:00Z")
    assert out["ok"] is False and out["refusal"]["code"] == "PAST_SCHEDULE"


async def test_tick_fires_a_due_schedule_through_the_same_execute_path(plane):
    store, tools, client, runs = plane
    pid = (await tools.prepare("SmallRefund", {"customer": "ACME"}))["prepared"]["prepared_id"]
    store.create_scheduled_execution(
        "sched-m6", prepared_id=pid, workspace=WS, fire_at="2020-01-01T00:00:00+00:00"
    )
    tick = (await client.post("/automations/tick")).json()
    assert tick["scheduled"][0]["status"] == "fired"
    assert tick["scheduled"][0]["execution"]["committed"] is True
    assert len(runs.fired) == 1
    assert store.get_prepared(pid, WS)["status"] == "committed"


# ── the server surface: five tools, in BOTH modes ─────────────────────────────────────────────


async def test_five_tools_register_alongside_the_existing_surface(monkeypatch):
    pytest.importorskip("mcp", reason="needs the [mcp] extra")
    from nilscript.mcp.server import build_server, build_tools

    five = {"nil_discover", "nil_inspect", "nil_prepare", "nil_execute", "nil_schedule"}
    cap = CapabilityTools("http://cp", "", workspace=WS)

    monkeypatch.delenv("NIL_MCP_SINGLE_SURFACE", raising=False)
    tools = build_tools(adapter_url="http://127.0.0.1:9", bearer="")
    full = {t.name for t in await build_server(tools, capability_tools=cap).list_tools()}
    assert five <= full

    monkeypatch.setenv("NIL_MCP_SINGLE_SURFACE", "1")
    single = {t.name for t in await build_server(tools, capability_tools=cap).list_tools()}
    assert five <= single  # the capability plane IS the model-facing plane — never hidden
    assert "nil_propose" not in single  # verb-level tools stay behind the builder flag

    # without a configured control plane the five tools simply don't exist — never half-work
    none_cfg = {t.name for t in await build_server(tools).list_tools()}
    assert five.isdisjoint(none_cfg)
