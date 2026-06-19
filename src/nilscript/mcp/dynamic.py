"""Skeleton-driven dynamic tools: one `propose_<verb>` per verb the backend actually exposes.

The differentiator made literal — the MCP tool list IS the adapter's skeleton. An agent is never
presented a verb the backend doesn't declare, so a hallucinated verb isn't even on the menu (and is
refused at PROPOSE if forced through the generic `nil_propose`). Each dynamic tool is a typed
shortcut to `NilTools.propose`: still a preview, still requires `nil_commit` to write.

This module is MCP-SDK-free except for the `register_dynamic_tools` binding step, which takes the
server object passed in by `server.py`.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from nilscript.mcp.tools import NilTools


def load_profiles() -> dict[str, dict[str, Any]]:
    """Map every verb in the bundled profiles to its JSON-Schema profile.

    Same source the SDK ships as the agent's tool catalog: `nilscript.sdk/spec/0.1/profiles/
    <family>-v1/*.json` (response schemas skipped). Verb name = `<family>.<file-stem>`.
    """
    out: dict[str, dict[str, Any]] = {}
    spec = resources.files("nilscript.sdk").joinpath("spec/0.1/profiles")
    for profile_dir in spec.iterdir():
        if not profile_dir.is_dir():
            continue
        family = profile_dir.name.replace("-v1", "")
        for f in profile_dir.iterdir():
            if f.name.endswith(".json") and ".response" not in f.name:
                out[f"{family}.{f.name[:-5]}"] = json.loads(f.read_text())
    return out


def tool_name_for(verb: str) -> str:
    """`commerce.create_product` -> `propose_commerce_create_product` (MCP-tool-name-safe)."""
    return "propose_" + verb.replace(".", "_")


def describe_verb(verb: str, schema: dict[str, Any] | None) -> str:
    """A one-line tool description carrying the verb's required/optional args from its profile."""
    head = f"PROPOSE {verb} — preview only, no write (commit the returned proposal with nil_commit)."
    if not schema:
        return head + " Args: see nil_describe."
    props = schema.get("properties", {})
    required = list(schema.get("required", []))
    optional = [k for k in props if k not in required]
    req = ", ".join(required) if required else "—"
    opt = ", ".join(optional) if optional else "—"
    return f"{head} required: {req}; optional: {opt}."


def _make_propose_fn(tools: NilTools, verb: str):  # type: ignore[no-untyped-def]
    async def _propose(args: dict[str, Any] | None = None) -> dict[str, Any]:
        return await tools.propose(verb, args or {})

    _propose.__name__ = tool_name_for(verb)
    return _propose


def register_dynamic_tools(
    server: Any,
    tools: NilTools,
    verbs: list[str],
    *,
    profiles: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Bind one `propose_<verb>` tool per skeleton verb onto `server`. Returns the tool names.

    `verbs` is the live skeleton (`handshake().verbs`) — the filter that keeps the surface bounded
    to what the backend really exposes. A verb with no bundled profile still gets a tool (it is a
    real adapter verb); it simply carries a generic description.
    """
    catalog = profiles if profiles is not None else load_profiles()
    registered: list[str] = []
    for verb in verbs:
        name = tool_name_for(verb)
        server.add_tool(
            _make_propose_fn(tools, verb),
            name=name,
            description=describe_verb(verb, catalog.get(verb)),
        )
        registered.append(name)
    return registered
