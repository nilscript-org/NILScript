"""Prescriptive refusals + the bounded, grounded repair loop (plan §5.1–5.2).

A NIL refusal can carry a **`repair`** block that prescribes its own fix: "the missing entity is a
customer; create it with `services.create_client`; carry the new id into `party_id`". On such a
refusal the agent runs a *bounded, grounded* loop — resolve the value from conversation context,
emit the prerequisite verb **as a proposal** (NIL's no-commit-without-confirmation invariant holds),
then retry the original. It is grounded (driven by a real refusal, never a guess) and bounded (a hard
attempt cap). Ambiguity surfaces candidates instead of inventing an entity ("عبدالرحيم vs عبدالرحمن").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

DEFAULT_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class RepairBlock:
    """A refusal's self-prescribed fix."""

    missing_entity: str  # "customer"
    resolve_with: str  # the NIL verb that creates it, e.g. "services.create_client"
    carry: str  # "<original_arg>-><created_field>", e.g. "party_id->name"

    def as_dict(self) -> dict[str, str]:
        return {"missing_entity": self.missing_entity, "resolve_with": self.resolve_with, "carry": self.carry}

    @property
    def target_arg(self) -> str:
        return self.carry.replace("→", "->").split("->", 1)[0].strip()

    @property
    def source_field(self) -> str:
        parts = self.carry.replace("→", "->").split("->", 1)
        return (parts[1] if len(parts) > 1 else "name").strip()


def make_refusal(code: str, field_name: str | None = None, *, message: str = "", repair: RepairBlock | None = None) -> dict[str, Any]:
    """Build a NIL refusal body, optionally carrying a prescriptive `repair` block (plan §5.1)."""
    body: dict[str, Any] = {"outcome": "refusal", "code": code}
    if field_name is not None:
        body["field"] = field_name
    if message:
        body["message"] = message
    if repair is not None:
        body["repair"] = repair.as_dict()
    return body


def repair_of(refusal: dict[str, Any]) -> RepairBlock | None:
    """Extract a RepairBlock from a refusal body, or None if it carries none."""
    block = refusal.get("repair") if isinstance(refusal, dict) else None
    if not isinstance(block, dict) or "missing_entity" not in block:
        return None
    return RepairBlock(
        missing_entity=block["missing_entity"],
        resolve_with=block.get("resolve_with", ""),
        carry=block.get("carry", "->name"),
    )


@dataclass(frozen=True)
class Resolution:
    """The result of resolving a missing entity from conversation context."""

    value: Any | None = None  # a single resolved value -> proceed
    candidates: list[str] = field(default_factory=list)  # >1 plausible -> AMBIGUOUS, never guess


@dataclass
class RepairOutcome:
    status: str  # "repaired" | "ambiguous" | "unresolved" | "exhausted" | "not_repairable"
    attempts: int = 0
    created: list[dict[str, Any]] = field(default_factory=list)  # prerequisite entities (as proposals)
    candidates: list[str] = field(default_factory=list)
    final: Any | None = None  # the retried original's result, on success


# Callable contracts injected by the host (conv-layer / SDK):
Resolver = Callable[[str], Resolution]  # missing_entity -> Resolution (from the recent-entities pool)
Proposer = Callable[[str, Any], dict[str, Any]]  # (verb, value) -> created entity (a confirmed proposal)
Retrier = Callable[[dict[str, Any]], dict[str, Any]]  # carried args -> the original verb's outcome body


def run_repair_loop(
    refusal: dict[str, Any],
    original_args: dict[str, Any],
    *,
    resolve: Resolver,
    propose_prerequisite: Proposer,
    retry_original: Retrier,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> RepairOutcome:
    """Run the bounded grounded loop (plan §5.2). See module docstring for the contract.

    Returns a RepairOutcome; `repaired` carries the retried original's `final` body. Never invents an
    entity: ambiguity -> `ambiguous` (+candidates); no resolution -> `unresolved` (ask the human).
    """
    args = dict(original_args)
    outcome = RepairOutcome(status="not_repairable")

    for attempt in range(1, max_attempts + 1):
        outcome.attempts = attempt
        block = repair_of(refusal)
        if block is None:
            outcome.status = "not_repairable" if attempt == 1 else "repaired"
            return outcome

        resolution = resolve(block.missing_entity)
        if len(resolution.candidates) > 1:
            return RepairOutcome(status="ambiguous", attempts=attempt, created=outcome.created, candidates=resolution.candidates)
        if resolution.value in (None, ""):
            return RepairOutcome(status="unresolved", attempts=attempt, created=outcome.created)

        # Emit the prerequisite as a proposal (human-confirmation preserved upstream of `propose`).
        created = propose_prerequisite(block.resolve_with, resolution.value)
        outcome.created.append(created)
        args[block.target_arg] = created.get(block.source_field, created.get("name"))

        result = retry_original(args)
        if result.get("outcome") == "refusal" and repair_of(result) is not None:
            refusal = result  # another unmet prerequisite — loop (bounded)
            continue
        return RepairOutcome(status="repaired", attempts=attempt, created=outcome.created, final=result)

    return RepairOutcome(status="exhausted", attempts=max_attempts, created=outcome.created)


# --- backward recovery: the Saga unwind (ROLLBACK) --------------------------------------------
#
# Forward repair (above) heals by *completing*. When that is impossible — a prerequisite can't be
# made, the owner cancels, a downstream step is terminally failed — the program is unwound by
# *compensation*, in reverse commit order. This is the other arm of the same self-healing axiom.


@dataclass(frozen=True)
class CommittedStep:
    """A step the runtime already committed, carrying how it may be reversed."""

    verb: str
    reversibility: str  # REVERSIBLE | COMPENSABLE | IRREVERSIBLE
    compensation_token: str | None = None
    result: dict[str, Any] = field(default_factory=dict)


@dataclass
class UnwindOutcome:
    """The result of unwinding a partially-completed saga.

    `status`:
      - "compensated" — every completed step was reversed (auto for blessed REVERSIBLE steps).
      - "parked"      — some steps need a human DECIDE (COMPENSABLE / non-allowlisted) — never auto-acted.
      - "blocked"     — an IRREVERSIBLE step means the program cannot be fully rolled back (honest partial).
    """

    status: str
    compensated: list[str] = field(default_factory=list)
    parked: list[str] = field(default_factory=list)
    irreversible: list[str] = field(default_factory=list)


# step -> the governed compensation outcome (a real PROPOSE->COMMIT upstream).
Compensator = Callable[["CommittedStep"], dict[str, Any]]


def run_saga_unwind(
    steps: list[CommittedStep],
    *,
    compensate: Compensator,
    auto_compensate: frozenset[str] | set[str] = frozenset(),
) -> UnwindOutcome:
    """Unwind committed `steps` in reverse order via governed compensation (plan §3, ROLLBACK).

    Only REVERSIBLE steps whose verb is on the `auto_compensate` allowlist are reversed automatically;
    COMPENSABLE (or non-allowlisted) steps are PARKED for a human DECIDE — never auto-acted. An
    IRREVERSIBLE step blocks a full rollback and is reported honestly, never silently skipped.
    """
    outcome = UnwindOutcome(status="compensated")
    for step in reversed(steps):
        if step.reversibility == "IRREVERSIBLE":
            outcome.irreversible.append(step.verb)
        elif step.reversibility == "REVERSIBLE" and step.verb in auto_compensate:
            compensate(step)  # governed compensation (previewed + committed upstream)
            outcome.compensated.append(step.verb)
        else:  # COMPENSABLE, or a REVERSIBLE step not pre-blessed for auto-unwind
            outcome.parked.append(step.verb)

    if outcome.irreversible:
        outcome.status = "blocked"
    elif outcome.parked:
        outcome.status = "parked"
    return outcome
