"""The compiler's output — the structured L3 plan (Wave 4 §10). Frozen dataclasses (not authored AST;
these are compiler results), the thing the `.nil` printer (§14.4c) serializes. An effect step carries
everything the runtime + Permission Card need — the pinned capability, the resolved verb, the governed
backend (D8), and the tier — so nothing is decided later at runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CompiledStep:
    """One lowered step. `kind="effect"` → a resolved capability skill call; `kind="control"` → a
    control-flow primitive lowered verbatim (approval/wait/decision/checkpoint/notify)."""

    kind: str  # "effect" | "control"
    # effect fields (None on control steps):
    capability: str | None = None
    version: str | None = None  # the pinned SemVer the import resolved to
    skill: str | None = None
    verb: str | None = None  # the resolved concrete verb (D3)
    backend: str | None = None  # the governed target system (D8)
    tier: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    bind: str | None = None
    # control fields (None on effect steps):
    control: str | None = None
    strategy: str | None = None
    approver: str | None = None
    event: str | None = None
    match: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int | None = None
    message: Any | None = None  # BilingualText for a notify step
    to: str | None = None


@dataclass(frozen=True)
class CompiledEnvelope:
    """The aggregate governance surface of the whole plan (D5): the strongest tier, the union of every
    effect the plan can fire, and the strongest reversibility — the full blast radius on the Card."""

    tier: str
    reversibility: str
    effects: tuple[str, ...]


@dataclass(frozen=True)
class CompiledPlan:
    """A compiled cycle: the domain it ran in, its lowered steps, and the aggregate envelope."""

    domain: str
    intent: str
    steps: tuple[CompiledStep, ...]
    envelope: CompiledEnvelope
