"""Skeleton-driven dynamic tools: the MCP tool list is bounded to the backend's declared verbs."""

import pytest

pytest.importorskip("mcp", reason="needs the [mcp] extra")

from nilscript.mcp.dynamic import (  # noqa: E402
    describe_verb,
    load_profiles,
    register_dynamic_tools,
    tool_name_for,
)
from nilscript.mcp.tools import NilTools  # noqa: E402
from nilscript.sdk.client import NilClient  # noqa: E402
from nilscript.sdk.grants import GrantRef  # noqa: E402
from nilscript.sdk.transport import NilTransport  # noqa: E402

GRANT = GrantRef.from_secret(
    grant_id="g", workspace="w", secret="x", scopes=frozenset({"commerce.*"})
)


def _tools() -> NilTools:
    transport = NilTransport(base_url="https://x.example", bearer_secret="x")
    return NilTools(NilClient(transport=transport, grant=GRANT), transport)


def test_load_profiles_includes_known_verbs() -> None:
    profiles = load_profiles()
    assert "commerce.create_product" in profiles
    assert "resource.read" in profiles
    assert "properties" in profiles["commerce.create_product"]


def test_tool_name_is_mcp_safe() -> None:
    assert tool_name_for("commerce.create_product") == "propose_commerce_create_product"


def test_describe_verb_surfaces_required_args() -> None:
    profiles = load_profiles()
    desc = describe_verb("commerce.create_product", profiles["commerce.create_product"])
    assert "PROPOSE commerce.create_product" in desc
    assert "required:" in desc and "name" in desc


async def test_register_is_bounded_to_skeleton_verbs() -> None:
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("t")
    # Only these two verbs are "exposed" by the (mock) skeleton.
    registered = register_dynamic_tools(
        server, _tools(), ["commerce.create_product", "resource.read"]
    )
    assert registered == ["propose_commerce_create_product", "propose_resource_read"]

    listed = {t.name for t in await server.list_tools()}
    assert "propose_commerce_create_product" in listed
    assert "propose_resource_read" in listed
    # A real verb NOT in the skeleton is absent — hallucinated verbs aren't even on the menu.
    assert "propose_commerce_delete_product" not in listed
