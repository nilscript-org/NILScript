"""The `.nil` printer — `print_nil(cycle) -> str`, the SECOND authoring view over the frozen
Cycle AST v0.2 (docs/PLAN-cycle-ast-ssot.md §Phase 4).

This module DEFINES the canonical textual form of a Cycle. Printing is deterministic: stable key
order, 2-space indent, one construct per AST node and one printed token per AST field. The parser
(`nil_parser`) is its exact inverse — `parse_nil(print_nil(c)) == c` is the trust contract, and
`print_nil(parse_nil(text)) == text` for canonical text is the stability contract.

The grammar is 1:1 with the model: there is no surface construct without an AST node, and no AST
field that cannot be printed. Bilingual values follow a bijection (see `_bilingual`):

    "x"               ⟺  BilingualText(ar="x", en="x")     # single quoted string: ar == en
    { ar: "x" }       ⟺  BilingualText(ar="x", en=None)    # ar-only
    { ar: "a"; en: "b" } ⟺ BilingualText(ar="a", en="b")  # both, distinct

so every BilingualText prints in exactly one way and parses back identically.
"""

from __future__ import annotations

import json
from typing import Any

from nilscript.cycle.models import (
    ActionStep,
    ApprovalStep,
    Cycle,
    CycleMetadata,
    DecisionStep,
    EntityRef,
    Flow,
    NotifyStep,
    Outcome,
    PolicyRef,
    QueryStep,
    RoleRef,
    VariableBinding,
)
from nilscript.kernel.models import BilingualText

INDENT = "  "


def print_nil(cycle: Cycle) -> str:
    """Render a Cycle to its canonical `.nil` text. Deterministic and round-trippable."""
    lines: list[str] = []
    lines.append(f"cycle {cycle.cycle_id} {_trigger_header(cycle.trigger)} {{")
    body = _Printer(level=1)
    body.cycle_body(cycle)
    lines.extend(body.lines)
    lines.append("}")
    return "\n".join(lines) + "\n"


class _Printer:
    """Accumulates indented body lines at a fixed nesting level."""

    def __init__(self, level: int) -> None:
        self.lines: list[str] = []
        self.level = level

    def _emit(self, text: str) -> None:
        self.lines.append(INDENT * self.level + text if text else "")

    def cycle_body(self, cycle: Cycle) -> None:
        self._emit(f"workspace {_string(cycle.workspace)}")
        self._emit(f"intent {_bilingual(cycle.intent)}")
        self.meta(cycle.metadata)
        if cycle.variables:
            for var in cycle.variables:
                self.variable(var)
        if cycle.context:
            self.context(cycle.context)
        if cycle.roles:
            self.roles(cycle.roles)
        if cycle.policies:
            self.policies(cycle.policies)
        if cycle.resources:
            self.resources(cycle.resources)
        self.flow(cycle.flow)
        if cycle.outcomes:
            self.outcomes(cycle.outcomes)
        if cycle.documentation is not None:
            self._emit(f"documentation {_bilingual(cycle.documentation)}")

    # ── meta -----------------------------------------------------------------------------------
    def meta(self, meta: CycleMetadata) -> None:
        parts = [f"version: {_string(meta.version)}", f"owner: {_string(meta.owner)}"]
        if meta.description is not None:
            parts.append(f"description: {_bilingual(meta.description)}")
        if meta.tags:
            parts.append(f"tags: {_string_list(meta.tags)}")
        self._emit("meta { " + "; ".join(parts) + " }")

    # ── let / context / roles / policies / resources -------------------------------------------
    def variable(self, var: VariableBinding) -> None:
        self._emit(f"let {var.name} = {var.expression};")

    def context(self, refs: tuple[EntityRef, ...]) -> None:
        self._emit("context {")
        inner = _Printer(self.level + 1)
        for ref in refs:
            role = f" (role: {ref.role})" if ref.role is not None else ""
            inner._emit(f"{ref.name}: {ref.entity_type}{role};")
        self.lines.extend(inner.lines)
        self._emit("}")

    def roles(self, roles: tuple[RoleRef, ...]) -> None:
        names = ", ".join(r.role for r in roles)
        self._emit(f"roles {{ {names} }}")

    def policies(self, policies: tuple[PolicyRef, ...]) -> None:
        self._emit("policies {")
        inner = _Printer(self.level + 1)
        for pol in policies:
            parts = [f"policy {pol.policy_id}"]
            if pol.applies_to:
                parts.append(f"applies_to {_id_list(pol.applies_to)}")
            if pol.condition is not None:
                parts.append(f"when {_string(pol.condition)}")
            if pol.raises_tier is not None:
                parts.append(f"raises_tier {pol.raises_tier}")
            inner._emit(" ".join(parts))
        self.lines.extend(inner.lines)
        self._emit("}")

    def resources(self, resources: tuple[str, ...]) -> None:
        self._emit(f"resources {_string_list(resources)}")

    # ── flow + steps ---------------------------------------------------------------------------
    def flow(self, flow: Flow) -> None:
        self._emit(f"flow entry {flow.entry} {{")
        inner = _Printer(self.level + 1)
        for step in flow.steps:
            inner.step(step)
        self.lines.extend(inner.lines)
        self._emit("}")

    def step(self, step: Any) -> None:
        self._emit(f"step {step.id} {{")
        body = _Printer(self.level + 1)
        if isinstance(step, ActionStep):
            body._action_like("use", step)
        elif isinstance(step, QueryStep):
            body._action_like("query", step)
        elif isinstance(step, DecisionStep):
            body._decision(step)
        elif isinstance(step, ApprovalStep):
            body._approval(step)
        elif isinstance(step, NotifyStep):
            body._notify(step)
        else:  # pragma: no cover - the union is closed
            raise TypeError(f"unprintable step {type(step).__name__}")
        self.lines.extend(body.lines)
        self._emit("}")

    def _action_like(self, keyword: str, step: ActionStep | QueryStep) -> None:
        self._emit(f"{keyword} {step.use} {_arg_map(step.with_)}")
        if step.output is not None:
            self._emit(f"output {step.output}")
        if step.next is not None:
            self._emit(f"next {step.next}")

    def _decision(self, step: DecisionStep) -> None:
        line = f"decision when {_string(step.when)} on_true {step.on_true}"
        if step.on_false is not None:
            line += f" on_false {step.on_false}"
        self._emit(line)
        if step.next is not None:
            self._emit(f"next {step.next}")

    def _approval(self, step: ApprovalStep) -> None:
        parts = [f"title: {_bilingual(step.title)}"]
        if step.description is not None:
            parts.append(f"description: {_bilingual(step.description)}")
        parts.append(f"approver: {step.approver}")
        parts.append(f"timeout_seconds: {step.timeout_seconds}")
        self._emit("await approval { " + "; ".join(parts) + " }")
        self._emit(f"on approve -> {step.on_approve}")
        if step.on_reject is not None:
            self._emit(f"on reject -> {step.on_reject}")
        if step.on_timeout is not None:
            self._emit(f"on timeout -> {step.on_timeout}")

    def _notify(self, step: NotifyStep) -> None:
        self._emit(f"notify {_bilingual(step.message)}")
        if step.next is not None:
            self._emit(f"next {step.next}")

    # ── outcomes -------------------------------------------------------------------------------
    def outcomes(self, outcomes: tuple[Outcome, ...]) -> None:
        self._emit("outcomes {")
        inner = _Printer(self.level + 1)
        for out in outcomes:
            line = out.name
            if out.when is not None:
                line += f" when {_string(out.when)}"
            inner._emit(line + ";")
        self.lines.extend(inner.lines)
        self._emit("}")


# ── trigger header -----------------------------------------------------------------------------


def _trigger_header(trigger: Any) -> str:
    if trigger.type == "event":
        # on_event/match/source_adapter are deferred surface sugar; the worked example uses the
        # default "executed" with no match. Print the richer form only when it diverges so the
        # canonical default stays terse and round-trips.
        head = f"triggers_on {trigger.on_verb}"
        extra = []
        if trigger.on_event != "executed":
            extra.append(f"on_event {trigger.on_event}")
        if trigger.source_adapter is not None:
            extra.append(f"source_adapter {_string(trigger.source_adapter)}")
        if trigger.match:
            extra.append(f"match {_arg_map(trigger.match)}")
        # `where (...)` introduces the optional event config — a delimiter the cycle body's own `{`
        # can never be confused with (the body brace immediately follows the header otherwise).
        return head + ("" if not extra else " where (" + "; ".join(extra) + ")")
    if trigger.type == "manual":
        return "triggers manual"
    if trigger.type == "schedule":
        parts = []
        if trigger.cron is not None:
            parts.append(f"cron: {_string(trigger.cron)}")
        if trigger.interval_seconds is not None:
            parts.append(f"interval_seconds: {trigger.interval_seconds}")
        if trigger.timezone != "Asia/Riyadh":
            parts.append(f"timezone: {_string(trigger.timezone)}")
        return "triggers schedule { " + "; ".join(parts) + " }"
    raise TypeError(f"unprintable trigger {trigger.type!r}")  # pragma: no cover


# ── value formatting -------------------------------------------------------------------------


def _string(value: str) -> str:
    """A JSON-escaped double-quoted string — the one canonical string token."""
    return json.dumps(value, ensure_ascii=False)


def _string_list(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_string(v) for v in values) + "]"


def _id_list(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(values) + "]"


def _bilingual(text: BilingualText) -> str:
    if text.en is not None and text.en == text.ar:
        return _string(text.ar)
    if text.en is None:
        return "{ ar: " + _string(text.ar) + " }"
    return "{ ar: " + _string(text.ar) + "; en: " + _string(text.en) + " }"


def _arg_map(args: dict[str, Any]) -> str:
    """`{ key: <value>, ... }` with insertion-order keys preserved. Values are JSON scalars or
    nested structures — printed as canonical JSON so any `with`/`match` payload round-trips."""
    if not args:
        return "{}"
    inner = ", ".join(f"{key}: {_arg_value(value)}" for key, value in args.items())
    return "{ " + inner + " }"


def _arg_value(value: Any) -> str:
    # Compact, deterministic JSON for every scalar/container; keeps unicode literal.
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "), sort_keys=False)
