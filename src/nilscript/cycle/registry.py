"""The Protocol Registry — the symbol layer over a Cycle AST (the spine of the LSP).

Where `compile_cycle` LOWERS a Cycle to the governed IR, this module INDEXES it: it resolves every
IDENTIFIER in the cycle (a step name, a variable, a context entity, a role, a named output, a
policy id, an outcome) to a `Symbol`, and — given the verb catalog (`ValidationContext`) — the known
verbs and which are granted. From that index it answers the editor questions:

  - go-to-definition  → `resolve(name)`
  - find-references    → `references(name)`   (every step that USES the name)
  - completion         → `completions(kind)` / `verbs_for(prefix)`
  - dead-reference     → `dead_references()`  (used-but-undefined + defined-but-unused)

Kernel-pure. Governance metadata (tier / reversibility / IO) lives in os-server, NOT the kernel, so
this registry covers AST symbols + the verb CATALOG (name + skill + granted?) — never tier. Reference
scanning reuses compile.py's identifier-path discipline (`_PATH`): a value `lead.id` references the
head `lead`; a value with spaces/quotes/operators is a literal and references nothing. Step-target
fields (`next`, `on_*`) and `approver` are direct name references, not paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from nilscript.cycle.models import (
    ActionStep,
    ApprovalStep,
    Cycle,
    CycleStepType,
    DecisionStep,
    NotifyStep,
    QueryStep,
)
from nilscript.kernel.context import ValidationContext

# Same identifier-path shape compile.py uses to tell a reference from a literal: a value that is a
# bare dotted identifier (`lead`, `lead.id`, `payload.name`) is a candidate reference; anything with
# spaces, quotes, or operators is a literal.
_PATH = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")

SymbolKind = Literal[
    "step",
    "variable",
    "context_entity",
    "role",
    "output",
    "policy",
    "outcome",
    "verb",
]


@dataclass(frozen=True)
class Symbol:
    """One named thing in (or available to) a cycle. `defined_at` is the step name / section the
    symbol is declared in, or None for catalog verbs (declared by the backend, not the cycle).
    `detail` is a short human string for editor hover."""

    name: str
    kind: SymbolKind
    defined_at: str | None
    detail: str


@dataclass(frozen=True)
class DeadReference:
    """A structured dead-reference finding. `problem` is one of:
    - "undefined_step"   — a step-target field points at a step name that does not exist
    - "undefined_ref"    — a `with`/`when` value references a name that is no value source
    - "unused_output"    — a step declares an `output` no later step ever reads
    - "unused_variable"  — a variable binding no step ever reads
    """

    name: str
    kind: SymbolKind
    problem: str


def _head(value: str) -> str:
    """The head identifier of a dotted path (`lead.id` → `lead`)."""
    return value.partition(".")[0]


def _path_refs(value: object) -> list[str]:
    """Head identifiers referenced by a `with`/`when` value, recursing into dicts/lists. A literal
    (non-identifier string, number, bool) references nothing — mirrors compile.py's `_resolve`."""
    return [h for h, _dotted in _path_refs_dotted(value)]


def _path_refs_dotted(value: object) -> list[tuple[str, bool]]:
    """Like `_path_refs` but each head carries whether the path was DOTTED (`lead.id` → dotted).
    A bare single token (`default`, `quotation_sent`) is, like in compile.py, indistinguishable from
    a literal — only dotted paths are treated as definite references for dead-ref purposes."""
    if isinstance(value, dict):
        return [r for v in value.values() for r in _path_refs_dotted(v)]
    if isinstance(value, (list, tuple)):
        return [r for v in value for r in _path_refs_dotted(v)]
    if isinstance(value, str) and _PATH.match(value):
        return [(_head(value), "." in value)]
    return []


def _expr_refs(expression: str | None) -> list[str]:
    """Head identifiers referenced inside a decision/outcome guard expression. Best-effort: pull
    every bare dotted identifier token out of the expression and keep its head."""
    if not expression:
        return []
    return [_head(tok) for tok in re.findall(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", expression)]


def _step_target_fields(step: CycleStepType) -> list[tuple[str, str]]:
    """(field, target-step-name) pairs where the step references ANOTHER step by name."""
    out: list[tuple[str, str]] = []
    if isinstance(step, (ActionStep, QueryStep, DecisionStep, NotifyStep)) and step.next:
        out.append(("next", step.next))
    if isinstance(step, DecisionStep):
        out.append(("on_true", step.on_true))
        if step.on_false:
            out.append(("on_false", step.on_false))
    if isinstance(step, ApprovalStep):
        out.append(("on_approve", step.on_approve))
        if step.on_reject:
            out.append(("on_reject", step.on_reject))
        if step.on_timeout:
            out.append(("on_timeout", step.on_timeout))
    return out


def _value_refs(step: CycleStepType) -> list[str]:
    """Head identifiers a step references through its DATA (not step-targets): `with` args for
    action/query, the `when` guard for a decision, the `approver` for an approval."""
    return [h for h, _definite in _value_refs_dotted(step)]


def _value_refs_dotted(step: CycleStepType) -> list[tuple[str, bool]]:
    """Like `_value_refs` but each head carries whether it is a DEFINITE reference (a dotted path,
    or an `approver` which is always a direct context-entity name) vs an ambiguous bare token that
    could be a literal. Used by dead-ref so a literal like `"default"` is never flagged."""
    if isinstance(step, (ActionStep, QueryStep)):
        return _path_refs_dotted(step.with_)
    if isinstance(step, DecisionStep):
        return [(h, True) for h in _expr_refs(step.when)]  # an expr operand is a real reference
    if isinstance(step, ApprovalStep):
        return [(step.approver, True)]  # a direct context-entity reference
    return []


class ProtocolRegistry:
    """The symbol index for one cycle. Build with `from_cycle`; query with `resolve` / `references`
    / `completions` / `dead_references` / `verbs_for`."""

    def __init__(
        self,
        symbols: dict[str, Symbol],
        steps: tuple[CycleStepType, ...],
        granted_verbs: frozenset[str],
        known_verbs: frozenset[str],
    ) -> None:
        self._symbols = symbols
        self._steps = steps
        self._granted_verbs = granted_verbs
        self._known_verbs = known_verbs

    # ── build ────────────────────────────────────────────────────────────────────────────────

    @classmethod
    def from_cycle(
        cls, cycle: Cycle, ctx: ValidationContext | None = None
    ) -> ProtocolRegistry:
        """Index every AST symbol, and — if a verb catalog is given — every catalog verb. Later
        definitions of the same name win (e.g. an output re-declared by a later step), matching the
        lowering's most-recent-producer semantics; verbs never shadow an AST name."""
        symbols: dict[str, Symbol] = {}

        # context entities (with role) ────────────────────────────────────────────────────────
        for ent in cycle.context:
            role = f" (role: {ent.role})" if ent.role else ""
            symbols[ent.name] = Symbol(
                name=ent.name,
                kind="context_entity",
                defined_at="context",
                detail=f"{ent.entity_type}{role}",
            )

        # variables ──────────────────────────────────────────────────────────────────────────
        for vb in cycle.variables:
            symbols[vb.name] = Symbol(
                name=vb.name,
                kind="variable",
                defined_at="variables",
                detail=f"variable = {vb.expression}",
            )

        # roles ────────────────────────────────────────────────────────────────────────────────
        for rr in cycle.roles:
            symbols[rr.role] = Symbol(
                name=rr.role,
                kind="role",
                defined_at="roles",
                detail=f"role: {rr.role}",
            )

        # policies ──────────────────────────────────────────────────────────────────────────────
        for pol in cycle.policies:
            scope = ", ".join(pol.applies_to) if pol.applies_to else "all effecting steps"
            tier = f" raises {pol.raises_tier}" if pol.raises_tier else ""
            symbols[pol.policy_id] = Symbol(
                name=pol.policy_id,
                kind="policy",
                defined_at="policies",
                detail=f"policy over [{scope}]{tier}",
            )

        # outcomes ──────────────────────────────────────────────────────────────────────────────
        for oc in cycle.outcomes:
            when = f" when {oc.when}" if oc.when else ""
            symbols[oc.name] = Symbol(
                name=oc.name,
                kind="outcome",
                defined_at="outcomes",
                detail=f"outcome{when}",
            )

        # steps + their declared outputs ────────────────────────────────────────────────────────
        # Outputs after steps so that a step name and an output name can co-exist; an output keeps
        # the LAST producing step (most-recent-producer, as in compile._lower).
        for step in cycle.flow.steps:
            symbols[step.id] = Symbol(
                name=step.id,
                kind="step",
                defined_at=step.id,
                detail=_step_detail(step),
            )
        for step in cycle.flow.steps:
            output = getattr(step, "output", None)
            if output:
                symbols[output] = Symbol(
                    name=output,
                    kind="output",
                    defined_at=step.id,
                    detail=f"output of {step.id}",
                )

        # catalog verbs ────────────────────────────────────────────────────────────────────────
        granted: frozenset[str] = frozenset()
        known: frozenset[str] = frozenset()
        if ctx is not None:
            known, granted = _catalog_verbs(cycle.workspace, ctx)
            for verb in sorted(known):
                if verb in symbols:
                    continue  # never shadow an AST symbol
                skill = verb.split(".", 1)[0]
                state = "granted" if verb in granted else "known (not granted)"
                symbols[verb] = Symbol(
                    name=verb,
                    kind="verb",
                    defined_at=None,
                    detail=f"verb in skill {skill} ({state})",
                )

        return cls(symbols=symbols, steps=cycle.flow.steps, granted_verbs=granted, known_verbs=known)

    # ── go-to-definition ────────────────────────────────────────────────────────────────────

    def resolve(self, name: str) -> Symbol | None:
        """The definition for `name`, or None if it resolves to nothing the cycle declares."""
        return self._symbols.get(name)

    # ── find-references ──────────────────────────────────────────────────────────────────────

    def references(self, name: str) -> list[str]:
        """Names of the steps that USE `name`: a step-target field (`next`/`on_*`) pointing at a step
        name, an `approver` pointing at a context entity, or a `with`/`when` value whose head is
        `name`. Order follows declaration order; each step listed at most once."""
        out: list[str] = []
        for step in self._steps:
            uses = {t for _, t in _step_target_fields(step)} | set(_value_refs(step))
            if name in uses:
                out.append(step.id)
        return out

    # ── completion ───────────────────────────────────────────────────────────────────────────

    def completions(self, kind: str | None = None) -> list[Symbol]:
        """All indexed symbols, optionally filtered to one `kind` (e.g. "step" for a `next` target,
        "verb" for a `use`). Sorted by name for stable editor ordering."""
        syms = [s for s in self._symbols.values() if kind is None or s.kind == kind]
        return sorted(syms, key=lambda s: s.name)

    def verbs_for(self, prefix: str = "") -> list[str]:
        """Catalog verb names matching `prefix` — autocomplete after `use `. Sorted."""
        return sorted(v for v in self._known_verbs if v.startswith(prefix))

    # ── dead-reference detection ─────────────────────────────────────────────────────────────

    def dead_references(self) -> list[DeadReference]:
        """Two classes of finding, in declaration order:

        USED-BUT-UNDEFINED (an error):
          - a step-target field (`next`/`on_*`) → a step name that does not exist
          - a `with`/`when`/`approver` value whose head names no value source (output / variable /
            context entity / role). Literals are never flagged — they are filtered by `_PATH`, the
            same way compile.py distinguishes a reference from a literal.

        DEFINED-BUT-UNUSED (a warning):
          - a declared `output` no later step reads
          - a `variable` binding no step reads
        """
        findings: list[DeadReference] = []
        step_names = {s.id for s in self._steps}
        # a name is a usable VALUE source if it is an output, variable, context entity, or role
        value_sources = {
            n
            for n, s in self._symbols.items()
            if s.kind in ("output", "variable", "context_entity", "role")
        }

        seen: set[tuple[str, str]] = set()
        used_values: set[str] = set()
        for step in self._steps:
            # step-target references → must be a real step
            for _field, target in _step_target_fields(step):
                if target not in step_names and (target, "undefined_step") not in seen:
                    seen.add((target, "undefined_step"))
                    findings.append(DeadReference(target, "step", "undefined_step"))
            # value references → must be a value source (output/variable/context/role). Only a
            # DEFINITE reference (dotted path / approver / expr operand) is flagged when undefined;
            # a bare token (`default`) is, like in compile.py, treated as a literal.
            for ref, definite in _value_refs_dotted(step):
                used_values.add(ref)
                if (
                    definite
                    and ref not in value_sources
                    and (ref, "undefined_ref") not in seen
                ):
                    seen.add((ref, "undefined_ref"))
                    findings.append(DeadReference(ref, "variable", "undefined_ref"))

        # defined-but-unused: outputs and variables nothing reads
        for name, sym in self._symbols.items():
            if sym.kind == "output" and name not in used_values:
                findings.append(DeadReference(name, "output", "unused_output"))
            elif sym.kind == "variable" and name not in used_values:
                findings.append(DeadReference(name, "variable", "unused_variable"))

        return findings


def _step_detail(step: CycleStepType) -> str:
    """A short human description of a step for hover."""
    if isinstance(step, ActionStep):
        return f"action step using {step.use}"
    if isinstance(step, QueryStep):
        return f"query step using {step.use}"
    if isinstance(step, DecisionStep):
        return f"decision step when {step.when}"
    if isinstance(step, ApprovalStep):
        return f"approval step (approver: {step.approver})"
    if isinstance(step, NotifyStep):
        return "notify step"
    return "step"


def _catalog_verbs(
    workspace: str, ctx: ValidationContext
) -> tuple[frozenset[str], frozenset[str]]:
    """(known, granted) verb sets for `workspace`. KNOWN = every verb the skill catalog declares
    plus every read verb; GRANTED = the subset the workspace's scopes admit (default-deny via
    `ctx.verb_allowed`). os-server owns tier/reversibility — the kernel knows only name + grant."""
    known: set[str] = set(ctx.read_verbs)
    for spec in ctx.skills.values():
        known |= set(spec.required_verbs)
    granted = frozenset(v for v in known if ctx.verb_allowed(workspace, v))
    return frozenset(known), granted
