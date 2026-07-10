"""The `.strategy.nil` printer — `print_strategy_nil(strategy) -> str`, DEFINING canonical form.

Node expressions print inline (`seq(approve(role: Manager), …)`); a Conditional root prints as the
two-clause `when "expr" -> <then>` / `else -> <else>` form — the ONE way a conditional appears on
the surface, keeping `parse(print(ast)) == ast` an exact bijection. Argument order inside
`approve(…)` is fixed (role/person, distinct_from, timeout) so printing is deterministic.
"""

from __future__ import annotations

from nilscript.cycle.nil_printer import INDENT, _id_list, _string
from nilscript.strategy.models import (
    Approve,
    Auto,
    Conditional,
    Quorum,
    Seq,
    Strategy,
    StrategyNodeType,
    UnitTimeout,
)


def print_strategy_nil(strategy: Strategy) -> str:
    """Render a Strategy to its canonical `.nil` text. Deterministic and round-trippable."""
    lines: list[str] = [f"strategy {strategy.strategy_id} v{strategy.version} {{"]
    lines.append(f"{INDENT}workspace {_string(strategy.workspace)}")
    root = strategy.root
    if isinstance(root, Conditional):
        lines.append(f"{INDENT}when {_string(root.when)} -> {_node(root.then)}")
        lines.append(f"{INDENT}else -> {_node(root.else_)}")
    else:
        lines.append(f"{INDENT}{_node(root)}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _node(node: StrategyNodeType) -> str:
    if isinstance(node, Auto):
        return f"auto(policy: {node.policy})"
    if isinstance(node, Approve):
        return _approve(node)
    if isinstance(node, Seq):
        return "seq(" + ", ".join(_node(item) for item in node.items) + ")"
    if isinstance(node, Quorum):
        distinct = ", distinct" if node.distinct else ""
        of = ", ".join(_approve(a) for a in node.of)
        return f"quorum({node.k}{distinct}, of: [{of}])"
    raise TypeError(f"unprintable strategy node {type(node).__name__}")  # pragma: no cover


def _approve(node: Approve) -> str:
    unit = node.unit
    parts = [f"{unit.by}: {unit.name}"]
    if unit.distinct_from:
        parts.append(f"distinct_from: {_id_list(unit.distinct_from)}")
    if unit.timeout is not None:
        parts.append(f"timeout: {_timeout(unit.timeout)}")
    return "approve(" + ", ".join(parts) + ")"


def _timeout(timeout: UnitTimeout) -> str:
    if timeout.then is None:
        return timeout.after  # route-less — parses, then V9 refuses it (a governance answer)
    if timeout.then.kind == "escalate":
        return f"{timeout.after} -> escalate(role: {timeout.then.to})"
    return f"{timeout.after} -> reject"


__all__ = ["print_strategy_nil"]
