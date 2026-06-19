"""The human-approval gate: HIGH/CRITICAL commits consult the control plane and fail safe."""

import pytest

pytest.importorskip("mcp", reason="needs the [mcp] extra")
respx = pytest.importorskip("respx")

import httpx  # noqa: E402

from nilscript.mcp.server import build_tools  # noqa: E402

CP = "http://cp.test"


def _human_tools(monkeypatch, *, with_cp=True):
    if with_cp:
        monkeypatch.setenv("NIL_APPROVAL_URL", CP)
    else:
        monkeypatch.delenv("NIL_APPROVAL_URL", raising=False)
    tools = build_tools(adapter_url="https://adapter.test", gate="human")
    tools._proposals["default"] = {"p1": {"tier": "HIGH", "verb": "services.create_invoice"}}
    return tools


async def test_low_tier_is_not_gated(monkeypatch) -> None:
    tools = _human_tools(monkeypatch)
    tools._proposals["default"]["p2"] = {"tier": "MEDIUM", "verb": "commerce.create_product"}
    assert await tools._gate_decision("default", "p2") is None  # commits directly


@respx.mock
async def test_pending_holds_and_registers(monkeypatch) -> None:
    respx.get(f"{CP}/proposals/p1/decision").mock(return_value=httpx.Response(200, json={"status": "pending"}))
    awaited = respx.post(f"{CP}/proposals/p1/await").mock(return_value=httpx.Response(200, json={"status": "pending"}))
    tools = _human_tools(monkeypatch)
    block = await tools._gate_decision("default", "p1")
    assert block is not None and block["outcome"] == "approval_required" and block["tier"] == "HIGH"
    assert awaited.called  # the proposal was registered for owner approval


@respx.mock
async def test_approved_allows_commit(monkeypatch) -> None:
    respx.get(f"{CP}/proposals/p1/decision").mock(return_value=httpx.Response(200, json={"status": "approved"}))
    tools = _human_tools(monkeypatch)
    assert await tools._gate_decision("default", "p1") is None  # owner approved → write proceeds


@respx.mock
async def test_rejected_blocks_commit(monkeypatch) -> None:
    respx.get(f"{CP}/proposals/p1/decision").mock(return_value=httpx.Response(200, json={"status": "rejected"}))
    tools = _human_tools(monkeypatch)
    block = await tools._gate_decision("default", "p1")
    assert block is not None and block["outcome"] == "rejected"


@respx.mock
async def test_unreachable_control_plane_fails_safe(monkeypatch) -> None:
    respx.get(f"{CP}/proposals/p1/decision").mock(side_effect=httpx.ConnectError("down"))
    tools = _human_tools(monkeypatch)
    block = await tools._gate_decision("default", "p1")
    assert block is not None and block["outcome"] == "approval_required"  # held, never auto-committed


async def test_no_control_plane_holds(monkeypatch) -> None:
    tools = _human_tools(monkeypatch, with_cp=False)
    block = await tools._gate_decision("default", "p1")
    assert block is not None and block["outcome"] == "approval_required"
