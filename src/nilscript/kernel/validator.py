"""WosoolDSLValidator: the compiler frontend. A deterministic, side-effect-free static-analysis
pass that admits a safe program or rejects an unsafe one with structured diagnostics.

Pipeline (wosool-dsl/03-VALIDATION-AND-TYPES.md): V1 schema → V2 reference integrity →
V3 acyclicity (Kahn) → V4 whitelist → V5 argument typing → V6 reachability/terminality/forward-
refs. Each pass appends diagnostics; ERROR-severity blocks admission. V1 is fatal (no model to
analyse), so it returns early; the rest run independently so one program can surface every fault.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from nilscript.kernel.context import ValidationContext
from nilscript.kernel.diagnostics import DiagnosticCollector, ValidationResult
from nilscript.kernel.models import (
    ActionNode,
    AwaitApprovalNode,
    ConditionNode,
    ForeachNode,
    NotifyNode,
    ParallelNode,
    QueryNode,
    WosoolProgram,
)
from nilscript.kernel.references import (
    Reference,
    iter_full_references,
    iter_references,
    parse_reference,
    references_in_text,
)


def validate(raw: dict[str, Any], ctx: ValidationContext) -> ValidationResult:
    diags = DiagnosticCollector()

    # V1 — schema gate (Pydantic). Fatal: without a parsed model the later passes have nothing.
    try:
        program = WosoolProgram.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ()))
        diags.error(
            "V1_SCHEMA", f"{first.get('msg', 'invalid')} (at {loc or 'root'})", location=loc
        )
        return ValidationResult.of(diags.items)

    node_ids = set(program.nodes)
    _check_references(program, node_ids, diags)
    order, acyclic = _check_acyclicity(program, node_ids, diags)
    _check_whitelist(program, ctx, diags)
    _check_arguments(program, ctx, diags)
    _check_output_references(program, ctx, diags)
    _check_reachability(program, node_ids, order, acyclic, diags)
    return ValidationResult.of(diags.items)


# --- V2 reference integrity -----------------------------------------------------------------


def _successor_targets(node: Any) -> list[str]:
    """The control-flow successor node ids a node points at (terminals/None excluded)."""
    targets: list[str] = []
    for attr in ("next", "on_true", "on_false", "on_approved", "on_rejected", "on_timeout", "body"):
        value = getattr(node, attr, None)
        if isinstance(value, str):
            targets.append(value)
    if isinstance(node, ParallelNode):
        targets.extend(node.branches)
    error = getattr(node, "on_error", None)
    if error is not None and error.to is not None:
        targets.append(error.to)
    return targets


def _check_references(
    program: WosoolProgram, node_ids: set[str], diags: DiagnosticCollector
) -> None:
    if program.entry not in node_ids:
        diags.error("V2_DANGLING_REF", f"entry {program.entry!r} is not a defined node")
    for node in program.pipeline:
        for target in _successor_targets(node):
            if target not in node_ids:
                diags.error(
                    "V2_DANGLING_REF",
                    f"node {node.id!r} targets undefined node {target!r}",
                    node=node.id,
                )


# --- V3 acyclicity (Kahn's topological sort) ------------------------------------------------


def _check_acyclicity(
    program: WosoolProgram, node_ids: set[str], diags: DiagnosticCollector
) -> tuple[list[str], bool]:
    edges = {
        node.id: [t for t in _successor_targets(node) if t in node_ids] for node in program.pipeline
    }
    in_degree = {nid: 0 for nid in node_ids}
    for sources in edges.values():
        for target in sources:
            in_degree[target] += 1

    queue = [nid for nid in node_ids if in_degree[nid] == 0]
    order: list[str] = []
    while queue:
        nid = queue.pop()
        order.append(nid)
        for target in edges[nid]:
            in_degree[target] -= 1
            if in_degree[target] == 0:
                queue.append(target)

    if len(order) < len(node_ids):
        cyclic = sorted(node_ids - set(order))
        diags.error("V3_CYCLE", f"graph is not acyclic; nodes in a cycle: {cyclic}")
        return order, False
    return order, True


# --- V4 whitelist ---------------------------------------------------------------------------


def _check_whitelist(
    program: WosoolProgram, ctx: ValidationContext, diags: DiagnosticCollector
) -> None:
    ws = program.workspace
    for node in program.pipeline:
        if isinstance(node, ActionNode):
            spec = ctx.skill(node.skill)
            if spec is None or node.verb not in spec.required_verbs:
                diags.error(
                    "V4_UNKNOWN_SKILL",
                    f"skill/verb {node.skill!r}/{node.verb!r} is not in the registered catalog",
                    node=node.id,
                )
                continue
            if not ctx.verb_allowed(ws, node.verb):
                diags.error(
                    "V4_SCOPE_DENIED",
                    f"verb {node.verb!r} is not granted to workspace {ws!r}",
                    node=node.id,
                )
            if spec.deprecated:
                diags.warning(
                    "V4_DEPRECATED_VERB",
                    f"verb {node.verb!r} (skill {node.skill!r}) is deprecated; admits with a "
                    "one-MINOR overlap — migrate to its replacement",
                    node=node.id,
                )
        elif isinstance(node, QueryNode):
            if not ctx.is_read_verb(node.verb):
                diags.error(
                    "V4_UNKNOWN_VERB",
                    f"query verb {node.verb!r} is not a registered read verb",
                    node=node.id,
                )
            elif not ctx.verb_allowed(ws, node.verb):
                diags.error(
                    "V4_SCOPE_DENIED",
                    f"verb {node.verb!r} is not granted to workspace {ws!r}",
                    node=node.id,
                )


# --- V5 argument typing ---------------------------------------------------------------------


def _check_arguments(
    program: WosoolProgram, ctx: ValidationContext, diags: DiagnosticCollector
) -> None:
    for node in program.pipeline:
        if not isinstance(node, ActionNode):
            continue  # query args carry no hint_schema; reads are screened by the System
        spec = ctx.skill(node.skill)
        if spec is None:
            continue  # already a V4 error
        schema = spec.hint_schema
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        allow_extra = schema.get("additionalProperties", True) is not False

        for field in required:
            if field not in node.args:
                diags.error(
                    "V5_ARG_MISSING",
                    f"node {node.id!r} is missing required arg {field!r}",
                    node=node.id,
                )
        for key, value in node.args.items():
            if key not in properties:
                if not allow_extra:
                    diags.error(
                        "V5_ARG_TYPE",
                        f"node {node.id!r} has unknown arg {key!r}",
                        node=node.id,
                    )
                continue
            if parse_reference(value) is not None:
                continue  # a data reference — its value is unknown until run time
            expected = properties[key].get("type")
            if expected == "string" and not isinstance(value, str):
                got = type(value).__name__
                diags.error(
                    "V5_ARG_TYPE",
                    f"node {node.id!r} arg {key!r} must be a string hint, got {got}",
                    node=node.id,
                )


# --- V5 (0.2) typed QUERY-output references --------------------------------------------------


def _ref_str(ref: Reference) -> str:
    tail = "".join(f"[{s}]" if isinstance(s, int) else f".{s}" for s in ref.segments)
    return f"$.{ref.source}{tail}"


def _walk_output(
    schema: dict[str, Any],
    segments: tuple[Any, ...],
    node: Any,
    ref: Reference,
    diags: DiagnosticCollector,
) -> None:
    """Walk a reference path through a query verb's typed response schema (the shape of `output`).

    A field segment requires an object carrying that property (else V5_OUTPUT_FIELD_UNKNOWN); an
    index segment requires an array (else V5_PATH_SHAPE_MISMATCH); a field read from an array (or
    an index into an object) is the array/object confusion the typed contract exists to reject.
    """
    cursor: dict[str, Any] = schema
    for segment in segments:
        kind = cursor.get("type")
        if isinstance(segment, int):
            if kind != "array":
                diags.error(
                    "V5_PATH_SHAPE_MISMATCH",
                    f"node {node.id!r}: index [{segment}] into a non-array ({kind}) in {_ref_str(ref)}",
                    node=node.id,
                )
                return
            cursor = cursor.get("items", {})
        else:
            if kind != "object":
                diags.error(
                    "V5_PATH_SHAPE_MISMATCH",
                    f"node {node.id!r}: field {segment!r} read from a non-object ({kind}) in {_ref_str(ref)}",
                    node=node.id,
                )
                return
            properties = cursor.get("properties", {})
            if segment not in properties:
                diags.error(
                    "V5_OUTPUT_FIELD_UNKNOWN",
                    f"node {node.id!r}: field {segment!r} is not in the query response in {_ref_str(ref)}",
                    node=node.id,
                )
                return
            cursor = properties[segment]


def _check_output_references(
    program: WosoolProgram, ctx: ValidationContext, diags: DiagnosticCollector
) -> None:
    nodes = program.nodes
    for node in program.pipeline:
        if not isinstance(node, ActionNode | QueryNode):
            continue
        for ref in iter_full_references(node.args):
            source = nodes.get(ref.source)
            if not isinstance(source, QueryNode):
                continue  # only QUERY outputs are typed; action outputs stay opaque
            response = ctx.response_schema_for(source.verb)
            if response is None:
                continue  # untyped read — nothing to check against
            if not ref.segments or ref.segments[0] != "output":
                continue  # not an output reference
            _walk_output(response, ref.segments[1:], node, ref, diags)


# --- V6 reachability, terminality, forward references ---------------------------------------


def _node_reference_sources(node: Any) -> list[str]:
    """Data-reference source steps a node consumes (for forward-reference detection)."""
    if isinstance(node, ActionNode | QueryNode):
        return iter_references(node.args)
    if isinstance(node, ConditionNode):
        return references_in_text(node.expression)
    if isinstance(node, ForeachNode):
        ref = parse_reference(node.items)
        return [ref.source] if ref is not None else []
    if isinstance(node, AwaitApprovalNode):
        ref = parse_reference(node.proposal)
        return [ref.source] if ref is not None else []
    if isinstance(node, NotifyNode):
        return iter_references(node.message.model_dump())
    return []


def _check_reachability(
    program: WosoolProgram,
    node_ids: set[str],
    order: list[str],
    acyclic: bool,
    diags: DiagnosticCollector,
) -> None:
    nodes = program.nodes

    # Reachability: BFS from entry over successor edges.
    reachable: set[str] = set()
    if program.entry in node_ids:
        frontier = [program.entry]
        while frontier:
            nid = frontier.pop()
            if nid in reachable:
                continue
            reachable.add(nid)
            frontier.extend(t for t in _successor_targets(nodes[nid]) if t in node_ids)
    for nid in sorted(node_ids - reachable):
        diags.error("V6_UNREACHABLE", f"node {nid!r} is not reachable from entry", node=nid)

    # Terminality: at least one reachable node ends the walk.
    if reachable and not any(not _successor_targets(nodes[nid]) for nid in reachable):
        diags.error("V6_NO_TERMINAL", "program has no terminal node (every path continues)")

    # Forward references: a $.step_k must precede the consuming node in topological order.
    if not acyclic:
        return  # the cycle (V3) makes order meaningless; skip to avoid false positives
    index = {nid: i for i, nid in enumerate(order)}
    for node in program.pipeline:
        for source in _node_reference_sources(node):
            if source in ("item", "input") or source not in index:
                continue
            if index[source] >= index[node.id]:
                diags.error(
                    "V6_FORWARD_REF",
                    f"node {node.id!r} references {source!r} which does not precede it",
                    node=node.id,
                )
