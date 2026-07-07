"""The NIL Protocol Model — Capability AST v0.1 (CAPABILITY-SHIFT plan §A1).

The `capability` is the business contract layer ABOVE a cycle: what the organisation can do,
who owns it, what it needs and produces, how risky it is, and which approval strategy governs it.
It is DATA, never code (invariant I1) — the kernel prepares/approves/executes; the capability only
describes. Same discipline as `cycle/models.py`: frozen pydantic models, `extra="forbid"`, pure
literals, every authoring surface (`.nil` text, the hub editor) a projection of this one object.

The `strategy` field references an ApprovalStrategy (`strategy/models.py`) BY ID — never inline —
and `implemented_by` maps implementation names to cycle ids ("default" required). `archetype` is an
OPTIONAL tag validated against the fixed enum (🏷 tag-only in MVP): auto-wrapped v0 capabilities
omit it rather than guess semantics (fail closed — never guess, invariant I2).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, model_validator

from nilscript.cycle.models import CYCLE_ID_PATTERN, VERB_PATTERN, PolicyTier
from nilscript.kernel.models import BilingualText, DslModel

# A capability id shares the cycle id shape (stable PascalCase/slug identity); referenced names
# (roles, strategies, entities, other capabilities) are bare identifiers on the `.nil` surface.
CAPABILITY_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]*$"
IDENT_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]*$"
FIELD_NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*$"
# `v2.3` or `v2.3.1` on the surface — MAJOR.MINOR with an optional PATCH.
SEMVER_PATTERN = r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?$"

_IDENT_RE = re.compile(IDENT_PATTERN)

# The fixed archetype vocabulary (🏷 tag-only in MVP: enum membership is the whole check — V8).
# Structurally closed via Literal so an unknown tag is unrepresentable, like every other enum here.
ArchetypeTag = Literal[
    "Approval",
    "Request",
    "Review",
    "Fulfillment",
    "Provisioning",
    "Deprovisioning",
    "Collection",
    "Registration",
    "Renewal",
    "Incident",
    "Investigation",
    "Compliance",
    "Monitoring",
    "Reconciliation",
    "Negotiation",
    "Planning",
    "Publishing",
    "Synchronization",
    "Escalation",
    "Recovery",
]


class FieldType(DslModel):
    """A typed contract slot: `Entity(Party)` (kind=entity), `List(OrderLine)` (kind=list), or a
    bare scalar name like `Money` (kind=scalar). `of` names the entity / item / scalar type."""

    kind: Literal["entity", "list", "scalar"]
    of: str = Field(pattern=FIELD_NAME_PATTERN)


class CapabilityField(DslModel):
    """One typed input/output of the capability contract (`customer: Entity(Party) required`)."""

    name: str = Field(pattern=FIELD_NAME_PATTERN)
    type: FieldType
    required: bool = False


class Exposure(DslModel):
    """Who may invoke the capability. `ai: false` is the fail-closed default — flipping it is a
    deliberate governance act (the act that replaces "registering a tool")."""

    ai: bool = False
    roles: tuple[str, ...] = ()


class Sod(DslModel):
    """Separation-of-duties class (invariant I6). `preparer_not_approver` requires every approve
    unit of the bound strategy to carry `distinct_from: [preparer]` (checked by V9)."""

    preparer_not_approver: bool = False


class Metrics(DslModel):
    sla: str = Field(min_length=1)  # e.g. "P2D" — informational in MVP


# The governance tier lattice — a skill may only sit AT or ABOVE its capability's risk floor (I3).
TIER_ORDER: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


class GovernanceEnvelope(DslModel):
    """D5 — the per-Skill governance surface: the tier, reversibility, and the FULL effect set the skill
    can produce, so the Permission Card shows the complete blast radius before approval (compile-checked
    against what the resolved cycle actually does). `effects` is the union of verbs the skill may fire —
    a skill cannot smuggle an effect not declared here."""

    tier: PolicyTier
    reversibility: Literal["REVERSIBLE", "COMPENSABLE", "IRREVERSIBLE"] = "IRREVERSIBLE"
    effects: tuple[str, ...] = ()  # verb ids this skill may produce (the declared blast radius)
    sod: Sod = Field(default_factory=Sod)

    @model_validator(mode="after")
    def _effects_are_verb_ids(self) -> GovernanceEnvelope:
        verb_re = re.compile(VERB_PATTERN)
        bad = [e for e in self.effects if not verb_re.match(e)]
        if bad:
            raise ValueError(f"envelope effects must be verb ids (domain.action), got {bad}")
        return self


class Skill(DslModel):
    """One named operation ON a capability (send · receive · notify) — the call site a cycle uses.
    Semantic-first (D3): a cycle calls `comms.send(...)` by MEANING; `resolves_to` lists the candidate
    verb(s) and an explicit `via:` at the call site disambiguates. Carries its own governance envelope
    (D5). A Skill is not a Verb — after migration the Verb is private to the capability."""

    name: str = Field(pattern=IDENT_PATTERN)  # "send"
    intent: BilingualText
    inputs: tuple[CapabilityField, ...] = ()
    outputs: tuple[CapabilityField, ...] = ()
    resolves_to: tuple[str, ...] = ()  # candidate verb ids; one when unambiguous, many when `via`-picked
    envelope: GovernanceEnvelope

    @model_validator(mode="after")
    def _resolves_to_are_verb_ids(self) -> Skill:
        verb_re = re.compile(VERB_PATTERN)
        bad = [v for v in self.resolves_to if not verb_re.match(v)]
        if bad:
            raise ValueError(f"skill {self.name!r} resolves_to must be verb ids, got {bad}")
        return self


class Capability(DslModel):
    nil: Literal["capability/0.1"]
    capability_id: str = Field(pattern=CAPABILITY_ID_PATTERN)
    workspace: str = Field(min_length=1)
    version: str = Field(pattern=SEMVER_PATTERN)  # "2.3" — prints as `v2.3`
    domain: str = Field(pattern=IDENT_PATTERN)  # "Finance"
    owner_role: str = Field(pattern=IDENT_PATTERN)
    intent: BilingualText
    aliases: tuple[str, ...] = ()  # discovery phrases, EN/AR mixed freely
    examples: tuple[str, ...] = ()
    inputs: tuple[CapabilityField, ...] = ()
    outputs: tuple[CapabilityField, ...] = ()
    risk: PolicyTier  # the FLOOR — implementations may only raise it (I3)
    strategy: str = Field(pattern=IDENT_PATTERN)  # ApprovalStrategy ref, by id
    compensation: str | None = Field(default=None, pattern=CAPABILITY_ID_PATTERN)
    requires: tuple[str, ...] = ()  # capability/state refs (idents)
    creates: tuple[str, ...] = ()  # entity refs
    enables: tuple[str, ...] = ()  # capability refs
    exposure: Exposure = Field(default_factory=Exposure)
    sod: Sod = Field(default_factory=Sod)
    archetype: ArchetypeTag | None = None  # OPTIONAL: wrapped v0 capabilities omit it
    metrics: Metrics | None = None
    skills: tuple[Skill, ...] = ()  # public operations (Wave 4 §14.3b) — OPTIONAL so wrapped v0 caps omit
    implemented_by: dict[str, str] = Field(min_length=1)  # name → cycle id

    @model_validator(mode="after")
    def _implemented_by_is_well_formed(self) -> Capability:
        """`implemented_by` must carry a "default" implementation, and every entry must be an
        identifier → cycle-id pair — an unnameable implementation is unrepresentable."""
        if "default" not in self.implemented_by:
            raise ValueError('implemented_by requires a "default" implementation')
        cycle_re = re.compile(CYCLE_ID_PATTERN)
        for key, value in self.implemented_by.items():
            if not _IDENT_RE.match(key):
                raise ValueError(f"implemented_by name {key!r} is not an identifier")
            if not cycle_re.match(value):
                raise ValueError(f"implemented_by[{key!r}] = {value!r} is not a cycle id")
        return self

    @model_validator(mode="after")
    def _skills_are_well_formed(self) -> Capability:
        """Skill names are unique on a capability, and each skill sits AT or ABOVE the capability's risk
        floor (I3 — an implementation may only RAISE the tier, never lower the governance)."""
        names = [s.name for s in self.skills]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate skill names: {dupes}")
        floor = TIER_ORDER[self.risk]
        below = [
            f"{s.name}({s.envelope.tier})"
            for s in self.skills
            if TIER_ORDER[s.envelope.tier] < floor
        ]
        if below:
            raise ValueError(f"skills below the capability risk floor {self.risk}: {below}")
        return self

    @model_validator(mode="after")
    def _ref_lists_are_identifiers(self) -> Capability:
        for label, refs in (
            ("requires", self.requires),
            ("creates", self.creates),
            ("enables", self.enables),
            ("exposure.roles", self.exposure.roles),
        ):
            bad = [r for r in refs if not _IDENT_RE.match(r)]
            if bad:
                raise ValueError(f"{label} entries must be identifiers, got {bad}")
        return self
