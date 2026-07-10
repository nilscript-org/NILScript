"""The NIL Protocol Model — ApprovalStrategy AST v0.1 (CAPABILITY-SHIFT plan §A2).

The MVP-5 approval algebra: `Auto | Approve | Seq | Quorum | Conditional`. ONLY these five forms
are representable — `par/weighted/dynamic/delegate/override` are grammar-reserved keywords that
PARSE-REFUSE with `V9_UNSUPPORTED_FORM` (⛔ no-rewrite guarantee: a new form is a new model variant
plus a new interpreter case, never a rework). Same discipline as `cycle/models.py`: frozen pydantic
models, `extra="forbid"`, closed discriminated unions, pure literals.

A `Conditional` is a top-level router (`when "expr" -> then / else -> else`) — its branches are
non-conditional nodes, so nested conditionals are structurally unrepresentable in MVP. A timeout's
route (`then`) is OPTIONAL in the model so that "every timeout has a route" is a V9 governance
finding (`validate.py`) rendered as an answer, not a parse crash.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Union

from pydantic import Field, field_validator

from nilscript.kernel.models import DslModel

STRATEGY_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]*$"
IDENT_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]*$"
# ISO-8601 duration (P2D, PT4H, P1DT12H …) — at least one component. Checked by a field validator
# with Python's `re` (pydantic-core's regex engine does not support look-around).
_ISO8601_DURATION_RE = re.compile(
    r"^P(?=.)([0-9]+Y)?([0-9]+M)?([0-9]+W)?([0-9]+D)?(T(?=[0-9])([0-9]+H)?([0-9]+M)?([0-9]+S)?)?$"
)

# Reserved future forms: the grammar knows them ONLY to refuse them clearly (V9_UNSUPPORTED_FORM).
RESERVED_FORMS = ("par", "weighted", "dynamic", "delegate", "override")

# `distinct_from` names the identities this unit's signer must differ from: the literal "preparer"
# (SoD, invariant I6) or a role name.
PREPARER = "preparer"


class EscalateRoute(DslModel):
    """`escalate(role: Finance)` — on timeout, route the pending unit to another role."""

    kind: Literal["escalate"]
    to: str = Field(pattern=IDENT_PATTERN)


class RejectRoute(DslModel):
    """`reject` — on timeout, the whole strategy resolves rejected."""

    kind: Literal["reject"]


TimeoutRoute = Annotated[Union[EscalateRoute, RejectRoute], Field(discriminator="kind")]


class UnitTimeout(DslModel):
    """`timeout: P2D -> escalate(role: Finance)`. `then` is optional in the MODEL so a route-less
    deadline parses and V9 refuses it as a governance finding (V9_TIMEOUT_NO_ROUTE)."""

    after: str = Field(min_length=2)
    then: TimeoutRoute | None = None

    @field_validator("after")
    @classmethod
    def _after_is_iso8601_duration(cls, value: str) -> str:
        if not _ISO8601_DURATION_RE.match(value):
            raise ValueError(f"timeout.after {value!r} is not an ISO-8601 duration (e.g. P2D)")
        return value


class ApprovalUnit(DslModel):
    """One human signature slot: `approve(role: Manager, distinct_from: [preparer], timeout: …)`.
    `by` is the addressing mode (a role, or a named person); `distinct_from` is the SoD constraint
    the interpreter enforces structurally (preparer ∉ approvers)."""

    by: Literal["role", "person"]
    name: str = Field(pattern=IDENT_PATTERN)
    distinct_from: tuple[str, ...] = ()
    timeout: UnitTimeout | None = None


class Auto(DslModel):
    """`auto(policy: small_ops)` — no human gate; only lawful when the capability risk ≤ MEDIUM
    (V9_AUTO_FORBIDDEN otherwise — the floor only rises, I3)."""

    form: Literal["auto"]
    policy: str = Field(pattern=IDENT_PATTERN)


class Approve(DslModel):
    form: Literal["approve"]
    unit: ApprovalUnit


class Seq(DslModel):
    """`seq(a, b, …)` — units materialize in order; the next card appears on the prior approval
    (the dependent-plan machinery, reused)."""

    form: Literal["seq"]
    items: tuple[StrategyNode, ...] = Field(min_length=1, max_length=32)


class Quorum(DslModel):
    """`quorum(2, distinct, of: [approve(…), approve(…)])` — one card, N signature slots, commit
    at k signatures; `distinct` requires k signatures from distinct identities."""

    form: Literal["quorum"]
    k: int = Field(ge=1, le=32)
    distinct: bool = False
    of: tuple[Approve, ...] = Field(min_length=1, max_length=32)


StrategyNodeType = Union[Auto, Approve, Seq, Quorum]
StrategyNode = Annotated[StrategyNodeType, Field(discriminator="form")]


class Conditional(DslModel):
    """`when "amount < 5000" -> auto(…)  /  else -> seq(…)`. Both branches are REQUIRED — a
    condition with no else would be an ungoverned hole (fail closed)."""

    form: Literal["conditional"]
    when: str = Field(min_length=1)
    then: StrategyNode
    else_: StrategyNode = Field(alias="else")


StrategyRoot = Annotated[
    Union[Auto, Approve, Seq, Quorum, Conditional], Field(discriminator="form")
]


class Strategy(DslModel):
    nil: Literal["strategy/0.1"]
    strategy_id: str = Field(pattern=STRATEGY_ID_PATTERN)
    workspace: str = Field(min_length=1)
    version: int = Field(ge=1)  # prints as `v1`
    root: StrategyRoot


Seq.model_rebuild()
Conditional.model_rebuild()
Strategy.model_rebuild()
