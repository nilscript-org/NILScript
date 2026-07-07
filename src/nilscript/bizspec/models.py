"""The BizSpec AST v0.1 (Wave 4 §11). Frozen pydantic, `extra="forbid"` — the L2 contract.

Two kinds of step, kept deliberately distinct so the language never blurs effects and control flow
(Constitution D4 / Law 5):

  · UseStep     an EFFECT — call a capability Skill BY MEANING (`comms.send`). Resolved through the
                Domain's imports (alias → capability@major) + the Skill's semantic-first verb candidates.
                Names a Skill, NEVER a verb — verbs are private to their capability.
  · ControlStep a control-flow PRIMITIVE — approval / wait / decision / checkpoint / notify. Not a
                capability; the compiler lowers it to the corresponding NIL step type directly.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, model_validator

from nilscript.capability.models import IDENT_PATTERN
from nilscript.cycle.models import VAR_PATTERN, PolicyTier
from nilscript.kernel.models import BilingualText, DslModel

# A skill call site: `alias.skill` (two identifiers). The alias resolves through the Domain's imports;
# the skill is the capability's public operation. This is a SHAPE check only — that the reference names
# a real Skill (and not, say, a private verb) is enforced at COMPILE time, where `resolve_skill` returns
# None for anything the capability doesn't expose and the compiler refuses.
_USE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*\.[A-Za-z][A-Za-z0-9_]*$")

# The control-flow primitives (D4). Effects never appear here; capabilities never appear as control.
ControlKind = Literal["approval", "wait", "decision", "checkpoint", "notify"]


class UseStep(DslModel):
    """An effect step: `use: comms.send` with args, an optional `via` (D3 explicit verb pick), and an
    optional `bind` to name the step output for later reference (`$<bind>`)."""

    use: str  # "alias.skill" — resolved through the Domain
    args: dict[str, Any] = Field(default_factory=dict)
    via: str | None = None  # explicit verb disambiguation, checked against the Skill's candidates
    bind: str | None = Field(default=None, pattern=VAR_PATTERN)  # output var, e.g. `bind: po` → `$po`

    @model_validator(mode="after")
    def _use_has_skill_call_shape(self) -> UseStep:
        if not _USE_RE.match(self.use):
            raise ValueError(f"use must be 'Alias.skill' (a dotted identifier), got {self.use!r}")
        return self


class ControlStep(DslModel):
    """A control-flow primitive — explicit, never a capability (D4). Carries only BUSINESS-level fields;
    the runtime scaffolding a runnable cycle needs (step ids, `next`-chaining, on_approve/on_timeout
    targets, the Flow entry) is SYNTHESIZED by the compiler, never authored here (§11 — L2 has no runtime
    detail). Per kind: `approval` → strategy (+ optional approver/timeout); `wait` → event (+ optional
    match/timeout); `notify` → message; `checkpoint` → `to` label."""

    control: ControlKind
    strategy: str | None = Field(default=None, pattern=IDENT_PATTERN)  # approval strategy ref
    approver: str | None = Field(default=None, min_length=1)  # approval: the business actor/role
    event: str | None = None  # wait: the event name to park on
    match: dict[str, Any] = Field(default_factory=dict)  # wait: correlation keys ($var refs allowed)
    timeout_seconds: int | None = Field(default=None, ge=1, le=2_592_000)  # approval/wait SLA
    message: BilingualText | None = None  # notify: the bilingual message
    to: str | None = None  # checkpoint: the label

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> ControlStep:
        if self.control == "approval" and self.strategy is None:
            raise ValueError("an approval control step needs a strategy")
        if self.control == "wait" and not self.event:
            raise ValueError("a wait control step needs an event")
        if self.control == "notify" and self.message is None:
            raise ValueError("a notify control step needs a message")
        if self.control == "checkpoint" and not self.to:
            raise ValueError("a checkpoint control step needs a `to` label")
        return self


class BizSpecPolicies(DslModel):
    """Cross-cutting policy the compiler folds into the emitted cycle: a floor tier and an SoD flag."""

    tier_floor: PolicyTier | None = None
    sod_preparer_not_approver: bool = False


class BizSpec(DslModel):
    nil: Literal["bizspec/0.1"]
    domain: str = Field(pattern=IDENT_PATTERN)  # the Domain the steps resolve through
    intent: str = Field(min_length=1)  # provenance from L1 (what the human/Hermes meant)
    steps: tuple["UseStep | ControlStep", ...] = ()
    policies: BizSpecPolicies = Field(default_factory=BizSpecPolicies)

    @model_validator(mode="after")
    def _has_at_least_one_step(self) -> BizSpec:
        if not self.steps:
            raise ValueError("a BizSpec must declare at least one step")
        return self
