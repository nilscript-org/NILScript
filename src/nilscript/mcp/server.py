"""The generic NIL-MCP server — one front door for any MCP-compatible agent.

This is the ONLY module that imports the `mcp` SDK (pulled by the `[mcp]` extra). It builds the
exact southbound wiring `nilscript run` already uses (`GrantRef` → `NilTransport` → `NilClient`),
wraps it in `NilTools`, and exposes six generic NIL primitives as MCP tools over stdio. Behind the
one front door, any mounted NIL adapter is driven through governed propose→approve→commit→rollback.

Dynamic per-verb tools (generated from the live skeleton) are a Phase-2 refinement; the generic
primitives below already make every adapter operable and keep the surface small.
"""

from __future__ import annotations

from nilscript.mcp.tools import NilTools
from nilscript.sdk.client import NilClient
from nilscript.sdk.grants import GrantRef
from nilscript.sdk.transport import NilTransport

_INSTRUCTIONS = (
    "This server is the NIL gate to a backend. Every write is two-step: call nil_propose to get a "
    "preview (no side effect), then nil_commit to execute. Reads use nil_query. nil_describe lists "
    "the verbs the backend actually exposes — do not invent others. To reverse a committed effect, "
    "call nil_rollback (it previews a compensation; commit it like any proposal). Refusals "
    "(UNKNOWN_VERB, UPSTREAM_UNAVAILABLE, IRREVERSIBLE, COMPENSATION_EXPIRED) are answers — read "
    "them, do not retry blindly."
)


def build_tools(
    *,
    adapter_url: str,
    grant_id: str = "local",
    workspace: str = "",
    bearer: str = "",
    scopes: frozenset[str] | None = None,
    session_id: str = "mcp-session",
    gate: str = "two-step",
) -> NilTools:
    """Wire the SDK client to the adapter and wrap it in the MCP tool surface.

    Mirrors `cli._cmd_run` so local-run and MCP behave identically against the same shim.
    """
    grant = GrantRef.from_secret(
        grant_id=grant_id,
        workspace=workspace,
        secret=bearer,
        scopes=scopes if scopes is not None else frozenset({"*"}),
    )
    transport = NilTransport(base_url=adapter_url, bearer_secret=bearer)
    client = NilClient(transport=transport, grant=grant)
    return NilTools(client, transport, session_id=session_id, gate=gate)


def build_server(
    tools: NilTools,
    *,
    name: str = "nilscript",
    dynamic_verbs: list[str] | None = None,
):  # type: ignore[no-untyped-def]
    """Bind the NilTools methods onto a FastMCP server. Imports `mcp` lazily.

    `dynamic_verbs` (the live skeleton from `handshake().verbs`) adds one `propose_<verb>` tool per
    verb the backend exposes — the tool list becomes the skeleton.
    """
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(name, instructions=_INSTRUCTIONS)

    server.add_tool(
        tools.describe,
        name="nil_describe",
        description="Discover the backend skeleton: the verbs and targets it actually exposes. "
        "No side effect.",
    )
    server.add_tool(
        tools.propose,
        name="nil_propose",
        description="Preview an intent (verb + args). NO side effect: returns a human-readable "
        "preview with a reversibility tier, or a structured refusal. Always call this before "
        "nil_commit.",
    )
    server.add_tool(
        tools.commit,
        name="nil_commit",
        description="Execute a previously previewed proposal by its id. This is the ONLY tool that "
        "writes. Idempotent: re-committing the same proposal replays, it never double-writes.",
    )
    server.add_tool(
        tools.query,
        name="nil_query",
        description="Read live business truth (verb + args). No side effect.",
    )
    server.add_tool(
        tools.status,
        name="nil_status",
        description="Get the status/result of a proposal by id, including its compensation handle.",
    )
    server.add_tool(
        tools.rollback,
        name="nil_rollback",
        description="Request a governed reversal of a committed effect (compensation_token + "
        "reason: saga_unwind|owner_cancel|downstream_failed|agent_repair). Previews a compensation "
        "to commit, or refuses honestly (IRREVERSIBLE / COMPENSATION_EXPIRED). No silent write.",
    )

    if dynamic_verbs:
        from nilscript.mcp.dynamic import register_dynamic_tools

        register_dynamic_tools(server, tools, dynamic_verbs)
    return server


async def _discover_verbs(adapter_url: str, bearer: str) -> list[str]:
    """Fetch the adapter skeleton with a throwaway transport (its own event loop), so the server's
    long-lived transport is only ever used inside the serving loop. Unreachable ⇒ no dynamic tools."""
    from nilscript.sdk.connect import handshake

    transport = NilTransport(base_url=adapter_url, bearer_secret=bearer)
    try:
        skeleton = await handshake(transport)
        return list(skeleton.get("verbs", []))
    finally:
        await transport.aclose()


def serve(
    *,
    adapter_url: str,
    grant_id: str = "local",
    workspace: str = "",
    bearer: str = "",
    scopes: frozenset[str] | None = None,
    gate: str = "two-step",
    transport: str = "stdio",
    dynamic_tools: bool = True,
) -> None:
    """Build and run the server (blocking). Called by `nilscript mcp`.

    When `dynamic_tools` is set (default), the live skeleton is fetched once at startup and one
    `propose_<verb>` tool is registered per exposed verb (the tool list becomes the skeleton).
    """
    import asyncio

    verbs: list[str] = []
    if dynamic_tools:
        verbs = asyncio.run(_discover_verbs(adapter_url, bearer))

    tools = build_tools(
        adapter_url=adapter_url,
        grant_id=grant_id,
        workspace=workspace,
        bearer=bearer,
        scopes=scopes,
        gate=gate,
    )
    server = build_server(tools, dynamic_verbs=verbs)
    server.run(transport=transport)  # type: ignore[arg-type]
