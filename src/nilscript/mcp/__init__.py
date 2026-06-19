"""nilscript.mcp — the generic NIL-MCP server.

One front door so any MCP-compatible agent connects once and drives any mounted NIL adapter through
governed propose→approve→commit→rollback. Launched via ``nilscript mcp`` (needs the ``[mcp]`` extra).

``nilscript.mcp.tools`` is pure and MCP-SDK-free (testable on its own); ``nilscript.mcp.server`` is
the only module that imports the ``mcp`` package.
"""

from nilscript.mcp.tools import NilTools

__all__ = ["NilTools"]
