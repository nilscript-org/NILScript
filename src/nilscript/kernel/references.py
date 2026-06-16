"""The $.step_k.output.field data-flow sub-language: parsing, resolution, and dependency scan.

A reference is a Reference Path (ASL sense): a single-node pointer — selection only, no filters,
wildcards, or functions. `resolve` turns references inside literals/args into real values read
from an append-only execution context; `iter_references` collects the source steps an args bag
depends on (used by the validator's V5/V6 dependency analysis and by the runtime interpreter).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# $.<source>(.<field> | [<index>])+  — source is a step id, `item`, or `input`. Segments are
# dotted identifiers or bracketed integer indices. No filters/wildcards/functions (least power).
_REFERENCE = re.compile(
    r"^\$\.(?P<source>step_[0-9]+|item|input)(?P<path>(?:\.[A-Za-z_]\w*|\[[0-9]+\])+)$"
)
_SEGMENT = re.compile(r"\.([A-Za-z_]\w*)|\[([0-9]+)\]")
# Reference tokens embedded in a larger string (e.g. a CEL guard expression or a message).
_REFERENCE_TOKEN = re.compile(r"\$\.(step_[0-9]+|item|input)(?:\.[A-Za-z_]\w*|\[[0-9]+\])*")


class ReferenceError(Exception):
    """A reference could not be resolved against the execution context."""


@dataclass(frozen=True)
class Reference:
    """A parsed reference: its source step (or `item`/`input`) and the path segments after it."""

    source: str
    segments: tuple[str | int, ...]


def parse_reference(value: object) -> Reference | None:
    """Parse a reference string, or None if `value` is not a (well-formed) reference."""
    if not isinstance(value, str):
        return None
    match = _REFERENCE.match(value)
    if match is None:
        return None
    # An unmatched alternation group is "" (not None); a non-empty name means a field segment,
    # otherwise the bracket index group holds an integer.
    segments: list[str | int] = [
        name if name else int(index) for name, index in _SEGMENT.findall(match.group("path"))
    ]
    return Reference(source=match.group("source"), segments=tuple(segments))


def _follow(root: Any, ref: Reference) -> Any:
    cursor = root
    for segment in ref.segments:
        try:
            cursor = cursor[segment]
        except (KeyError, IndexError, TypeError) as exc:
            raise ReferenceError(
                f"unresolved reference $.{ref.source}"
                + "".join(f"[{s}]" if isinstance(s, int) else f".{s}" for s in ref.segments)
            ) from exc
    return cursor


def resolve(value: Any, ctx: dict[str, Any], *, item: Any = None) -> Any:
    """Resolve every reference inside `value` against `ctx`, recursing into dicts and lists.

    A literal is returned as-is; a reference string is looked up. `$.item.*` resolves against the
    `item` binding (a foreach element). Raises ReferenceError if a source/field is absent — the
    validator guarantees this never happens for an admitted program, so a raise here is a bug.
    """
    if isinstance(value, dict):
        return {key: resolve(inner, ctx, item=item) for key, inner in value.items()}
    if isinstance(value, list):
        return [resolve(inner, ctx, item=item) for inner in value]
    ref = parse_reference(value)
    if ref is None:
        return value
    if ref.source == "item":
        # $.item.<field> indexes straight into the current foreach element.
        return _follow(item, ref)
    if ref.source not in ctx:
        raise ReferenceError(f"unresolved reference: source {ref.source!r} not in context")
    return _follow(ctx[ref.source], ref)


def iter_references(value: Any) -> list[str]:
    """All source steps referenced anywhere inside `value` (deduped, declaration order)."""
    found: list[str] = []
    _collect(value, found)
    seen: set[str] = set()
    ordered: list[str] = []
    for source in found:
        if source not in seen:
            seen.add(source)
            ordered.append(source)
    return ordered


def references_in_text(text: str) -> list[str]:
    """Source steps named by reference tokens embedded in a free string (a guard or message)."""
    return _REFERENCE_TOKEN.findall(text)


def iter_full_references(value: Any) -> list[Reference]:
    """Every parsed Reference anywhere inside `value` (for V5 output-path typing, NIL 0.2)."""
    out: list[Reference] = []
    _collect_full(value, out)
    return out


def _collect_full(value: Any, out: list[Reference]) -> None:
    if isinstance(value, dict):
        for inner in value.values():
            _collect_full(inner, out)
    elif isinstance(value, list):
        for inner in value:
            _collect_full(inner, out)
    else:
        ref = parse_reference(value)
        if ref is not None:
            out.append(ref)


def _collect(value: Any, out: list[str]) -> None:
    if isinstance(value, dict):
        for inner in value.values():
            _collect(inner, out)
    elif isinstance(value, list):
        for inner in value:
            _collect(inner, out)
    else:
        ref = parse_reference(value)
        if ref is not None:
            out.append(ref.source)
