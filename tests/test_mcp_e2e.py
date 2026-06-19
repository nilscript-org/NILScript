"""End-to-end: a real MCP client drives a live NIL shim through `nilscript mcp` over stdio.

The full plug-and-play path the server exists for, with NO mocks:

    MCP client  ──stdio──▶  nilscript mcp (subprocess)  ──HTTP/NIL──▶  FakeSystem shim (subprocess)

Boots the vendored PocketBase adapter against its in-memory FakeSystem (no live backend), launches
the MCP server as the stdio child of a real `mcp` ClientSession, and exercises
describe → propose → commit → rollback. Skips cleanly if the `[mcp]` extra or the demo adapter is
absent.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="needs the [mcp] extra")

import nilscript  # noqa: E402  (locate the vendored adapter under the package)

DEMO_DIR = Path(nilscript.__file__).parent / "demo"
BEARER = "secret123"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_up(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as s:
            s.settimeout(0.25)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError(f"shim did not come up on :{port} within {timeout}s")


_SHIM_BOOT = (
    "import sys, uvicorn;"
    "sys.path.insert(0, {demo!r});"
    "from pocketbase_nil_adapter.edge import create_app, CapturingEmitter;"
    "from pocketbase_nil_adapter.system import FakeSystem;"
    "uvicorn.run(create_app(FakeSystem(), CapturingEmitter(), bearer={bearer!r}),"
    " host='127.0.0.1', port={port}, log_level='warning')"
)


def _payload(call_result) -> dict:
    """Tool return as a dict. We parse the canonical JSON text content rather than
    `structuredContent` — our payloads legitimately contain a `result` key (the SSOT envelope), so
    any unwrap heuristic on the structured shape would be ambiguous; the text is the full dict."""
    return json.loads(call_result.content[0].text)


async def test_mcp_stdio_drives_live_shim_propose_commit_rollback() -> None:
    if not (DEMO_DIR / "pocketbase_nil_adapter").is_dir():
        pytest.skip("vendored demo adapter not present")
    try:
        import uvicorn  # noqa: F401
    except ModuleNotFoundError:
        pytest.skip("needs uvicorn (the [demo] extra) to boot a real shim")

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    port = _free_port()
    shim = subprocess.Popen(
        [sys.executable, "-c", _SHIM_BOOT.format(demo=str(DEMO_DIR), bearer=BEARER, port=port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_until_up(port)
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m", "nilscript.cli", "mcp",
                "--adapter-url", f"http://127.0.0.1:{port}",
                "--bearer", BEARER,
                "--scope", "commerce.*",
                "--scope", "resource.*",
            ],
            env={**os.environ},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # 1) the tool list IS the gate surface — generics + skeleton-bound per-verb tools
                listed = await session.list_tools()
                names = {t.name for t in listed.tools}
                assert {"nil_describe", "nil_propose", "nil_commit", "nil_rollback"} <= names
                # dynamic tools mirror the live skeleton (commerce.create_product is exposed)
                assert "propose_commerce_create_product" in names

                # 2) discovery — the shim reports its own skeleton
                skeleton = _payload(await session.call_tool("nil_describe", {}))
                assert skeleton["reachable"] is True and skeleton["conformant"] is True
                assert "commerce.create_product" in skeleton["verbs"]

                # 3) PROPOSE — preview only, no write
                preview = _payload(
                    await session.call_tool(
                        "nil_propose",
                        {"verb": "commerce.create_product", "args": {"name": "Aurora", "price": 49.9}},
                    )
                )
                assert preview["outcome"] == "proposal"
                proposal_id = preview["id"]

                # 4) COMMIT — the one write; returns a compensation handle
                committed = _payload(await session.call_tool("nil_commit", {"proposal_id": proposal_id}))
                assert committed["committed"] is True
                assert committed["state"] == "executed"
                token = committed["compensation"]["token"]
                assert token

                # 5) ROLLBACK — previews a compensation (never a silent write)
                reversal = _payload(
                    await session.call_tool(
                        "nil_rollback", {"compensation_token": token, "reason": "owner_cancel"}
                    )
                )
                assert reversal["outcome"] == "proposal"
                assert reversal["verb"] == "commerce.delete_product"
    finally:
        shim.terminate()
        try:
            shim.wait(timeout=5)
        except subprocess.TimeoutExpired:
            shim.kill()
