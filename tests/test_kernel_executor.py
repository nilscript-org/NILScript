"""End-to-end LocalExecutor proof against the in-memory PocketBase FakeSystem — no live backend.

Drives the real NIL edge in-process via httpx ASGITransport, exercising the headless kernel:
a single action reaching `executed`, condition+dataflow routing, and a compensate (saga) unwind.
"""

from __future__ import annotations

import httpx
import pytest

from nilscript.kernel import LocalExecutor
from nilscript.sdk.client import NilClient
from nilscript.sdk.grants import GrantRef
from nilscript.sdk.transport import NilTransport

pocketbase_edge = pytest.importorskip("pocketbase_nil_adapter.edge")
pocketbase_system = pytest.importorskip("pocketbase_nil_adapter.system")


def _executor() -> LocalExecutor:
    app = pocketbase_edge.create_app(
        pocketbase_system.FakeSystem(), pocketbase_edge.CapturingEmitter(), bearer=None
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://shim")
    transport = NilTransport(base_url="http://shim", bearer_secret="x", client=client)
    grant = GrantRef.from_secret(
        grant_id="g", workspace="ws_demo", secret="s", scopes=frozenset({"commerce.*"})
    )
    nil = NilClient(transport=transport, grant=grant)
    return LocalExecutor(nil, run_id="test-run", session_id="test-session")


def _action(node_id: str, verb: str, args: dict, **extra) -> dict:
    return {"id": node_id, "type": "action", "skill": "product", "verb": verb, "args": args, **extra}


async def test_single_action_reaches_executed() -> None:
    program = {
        "wosool": "0.1",
        "workspace": "ws_demo",
        "entry": "step_1",
        "pipeline": [_action("step_1", "commerce.create_product", {"name": "قميص"}, next=None)],
    }
    result = await _executor().execute(program)
    assert result.completed
    assert result.context["step_1"]["output"]["state"] == "executed"


async def test_condition_routes_on_dataflow() -> None:
    program = {
        "wosool": "0.1",
        "workspace": "ws_demo",
        "entry": "step_1",
        "pipeline": [
            _action("step_1", "commerce.create_product", {"name": "قميص"}, next="step_2"),
            {
                "id": "step_2",
                "type": "condition",
                "expression": '$.step_1.output.state == "executed"',
                "on_true": "step_3",
            },
            _action("step_3", "commerce.create_product", {"name": "حذاء"}, next=None),
        ],
    }
    result = await _executor().execute(program)
    assert result.completed
    assert result.context["step_2"]["output"] is True
    assert "step_3" in result.context  # the on_true branch ran


async def test_compensate_unwinds_committed_step() -> None:
    # step_1 commits (REVERSIBLE, compensate_with delete_product); step_2 refuses (missing required
    # `name`); on_error=compensate ⇒ the executor unwinds step_1 and reports an honest partial.
    program = {
        "wosool": "0.1",
        "workspace": "ws_demo",
        "entry": "step_1",
        "on_error": "compensate",
        "pipeline": [
            _action(
                "step_1",
                "commerce.create_product",
                {"name": "قميص"},
                next="step_2",
                compensate_with={"verb": "commerce.delete_product", "args": {"product_id": "x"}},
            ),
            _action("step_2", "commerce.create_product", {}, next=None),  # missing name → refusal
        ],
    }
    result = await _executor().execute(program)
    assert result.completed is False
    assert result.partial is True
    assert result.blocked_at == "step_2"
    assert result.compensated == ["step_1"]
