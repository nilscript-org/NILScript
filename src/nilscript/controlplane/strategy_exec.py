"""B3 — the strategy interpreter: a pure state machine over signature-slot rows.

Drives the MVP-5 approval algebra (`Auto | Approve | Seq | Quorum | Conditional`) for ONE
prepared subject, entirely through `strategy_signatures` rows in the control-plane store:

- `Auto(policy)` auto-approves ONLY when the capability risk ≤ MEDIUM (fail closed at runtime,
  not just at V9 bind time) and records a decision row with actor ``policy:<id>``.
- `Approve(unit)` holds one slot addressed to the unit's role/person; its `timeout` becomes a
  row `deadline` the /automations/tick sweep enforces (the parked_runs deadline pattern):
  `escalate(to)` re-addresses a fresh slot, `reject` rejects the whole subject.
- `Seq(items)` materializes item N+1 only on item N's approval — the dependent-plan grammar
  (planned → pending stepwise, cancel-the-rest on any rejection) carried on the signatures
  table itself, because a strategy unit is an approval of the SAME subject, not a new adapter
  proposal (there is no verb/args to re-propose, so `planned_steps` rows would be dishonest).
- `Quorum(k, distinct, of)` is ONE subject with N slots; the stage completes only at k
  signatures from DISTINCT actors (and distinct roles when `distinct` is declared).
- `Conditional(when, then, else_)` routes by evaluating `when` against the prepared inputs with
  the kernel's OWN guard evaluator (`$.input.<field>` references) — never a second evaluator.
- SoD: the preparer (stamped at prepare time) can never sign their own subject, and a signer
  violating a unit's `distinct_from` refuses — both with code ``SOD_VIOLATION`` (a refusal
  payload, never an exception).
- A material edit VOIDS collected signatures (`superseded`, audit row kept) and re-holds fresh
  slots for the affected units (`rehold`).

Every public function returns data (state or a `{"refusal": {...}}` payload) — refusals are
answers, not exceptions. The strategy AST is re-flattened deterministically on every call from
the registry-pinned body, so the rows never encode control flow they could drift from.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from typing import Any

from nilscript.kernel.guards import GuardError, evaluate_guard
from nilscript.strategy.models import (
    PREPARER,
    Approve,
    Auto,
    Conditional,
    Quorum,
    Seq,
    Strategy,
    StrategyNodeType,
)

# Runtime mirror of V9's rule: automatic approval stops at MEDIUM (the floor only rises, I3).
_AUTO_ALLOWED_RISK = ("LOW", "MEDIUM")
# Slot statuses that still count as "live" (not yet settled for this generation of the card).
_LIVE = ("pending", "planned")

_DURATION_RE = re.compile(
    r"^P(?:(?P<years>\d+)Y)?(?:(?P<months>\d+)M)?(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)
_DURATION_SECONDS = {
    "years": 31536000,  # 365d — deadline arithmetic, not calendar arithmetic
    "months": 2592000,  # 30d
    "weeks": 604800,
    "days": 86400,
    "hours": 3600,
    "minutes": 60,
    "seconds": 1,
}


def duration_seconds(iso: str) -> int:
    """ISO-8601 duration → seconds (fixed 365d/30d for Y/M — deadlines, not calendars).
    Unparseable input maps to 0 (an immediate deadline — fail closed, never a silent no-timeout)."""
    match = _DURATION_RE.match(iso or "")
    if match is None:
        return 0
    return sum(
        int(value) * _DURATION_SECONDS[name]
        for name, value in match.groupdict().items()
        if value is not None
    )


def _refusal(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"refusal": {"code": code, "message": message, **extra}}


# ── flattening: strategy AST → ordered stages of signature units ─────────────────────────────


@dataclass(frozen=True)
class StageUnit:
    """One signature slot to hold: who may sign it and its timeout, position-stable by `key`."""

    key: str
    by: str  # role | person
    name: str
    distinct_from: tuple[str, ...] = ()
    timeout_after: str | None = None
    timeout_route: dict[str, Any] | None = None


@dataclass(frozen=True)
class Stage:
    """One Seq step: either an auto policy (no human gate) or a k-of-n unit group."""

    kind: str  # "auto" | "units"
    policy: str = ""
    k: int = 1
    distinct: bool = False
    units: tuple[StageUnit, ...] = ()


@dataclass(frozen=True)
class FlattenResult:
    stages: tuple[Stage, ...] = ()
    branch: str | None = None  # "then" | "else" for a Conditional root
    refusal: dict[str, Any] | None = None


def _unit(node: Approve, key: str) -> StageUnit:
    u = node.unit
    route = None
    after = None
    if u.timeout is not None:
        after = u.timeout.after
        if u.timeout.then is not None:
            route = u.timeout.then.model_dump(mode="json")
        else:
            # V9 refuses a route-less timeout at registration; if one slips through, the honest
            # fail-closed route is reject — a silent expiry hole is never an option.
            route = {"kind": "reject"}
    return StageUnit(
        key=key,
        by=u.by,
        name=u.name,
        distinct_from=tuple(u.distinct_from),
        timeout_after=after,
        timeout_route=route,
    )


def _stages_of(node: StrategyNodeType, prefix: str) -> list[Stage]:
    if isinstance(node, Auto):
        return [Stage(kind="auto", policy=node.policy)]
    if isinstance(node, Approve):
        return [Stage(kind="units", k=1, units=(_unit(node, f"{prefix}a"),))]
    if isinstance(node, Quorum):
        return [
            Stage(
                kind="units",
                k=node.k,
                distinct=node.distinct,
                units=tuple(
                    _unit(member, f"{prefix}q{i}") for i, member in enumerate(node.of)
                ),
            )
        ]
    if isinstance(node, Seq):
        out: list[Stage] = []
        for i, item in enumerate(node.items):
            out.extend(_stages_of(item, f"{prefix}s{i}."))
        return out
    raise TypeError(f"unsupported strategy node {type(node).__name__}")  # unreachable: closed union


def flatten(strategy: Strategy | dict[str, Any], inputs: dict[str, Any]) -> FlattenResult:
    """Deterministically flatten a strategy into ordered stages. A `Conditional` root is resolved
    HERE, against the prepared inputs, with the kernel's guard evaluator (`$.input.<field>`) —
    the same expression engine decision guards use. A guard that cannot evaluate is a refusal
    (fail closed), never a default branch."""
    if not isinstance(strategy, Strategy):
        strategy = Strategy.model_validate(strategy)
    root = strategy.root
    branch: str | None = None
    if isinstance(root, Conditional):
        try:
            branch = "then" if evaluate_guard(root.when, {"input": dict(inputs)}) else "else"
        except GuardError as exc:
            return FlattenResult(
                refusal=_refusal(
                    "CONDITION_UNRESOLVED",
                    f"strategy condition {root.when!r} did not evaluate against the prepared "
                    f"inputs: {exc}",
                    when=root.when,
                )["refusal"],
            )
        root = root.then if branch == "then" else root.else_
    return FlattenResult(stages=tuple(_stages_of(root, "")), branch=branch)


# ── materialization + state ──────────────────────────────────────────────────────────────────


def _deadline(unit: StageUnit, now: datetime.datetime) -> str | None:
    if unit.timeout_after is None:
        return None
    return (now + datetime.timedelta(seconds=duration_seconds(unit.timeout_after))).isoformat()


def _live_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The CURRENT generation of each unit: for every unit_key, only its newest row counts —
    older rows (superseded/escalated/cancelled) remain as the audit trail."""
    newest: dict[str, dict[str, Any]] = {}
    for slot in slots:  # unit_idx-ordered, so later rows overwrite earlier generations
        newest[slot["unit_key"]] = slot
    return sorted(newest.values(), key=lambda s: s["unit_idx"])


def _stage_satisfied(stage_no: int, stage: Stage, current: list[dict[str, Any]]) -> bool:
    slots = [s for s in current if s["stage"] == stage_no]
    signed = [s for s in slots if s["status"] == "signed"]
    if stage.kind == "auto":
        return any(s["by_kind"] == "policy" and s["status"] == "signed" for s in slots)
    actors = {s["actor"] for s in signed if s.get("actor")}
    if len(actors) < stage.k:  # k signatures from DISTINCT actors, always
        return False
    if stage.distinct:  # and from distinct declared identities when demanded
        identities = {(s["by_kind"], s["role"]) for s in signed}
        return len(identities) >= stage.k
    return True


def overall_status(stages: tuple[Stage, ...], slots: list[dict[str, Any]]) -> str:
    """'pending' | 'approved' | 'rejected' — derived purely from the slot rows."""
    if any(s["status"] in ("rejected", "timed_out") for s in slots):
        return "rejected"
    current = _live_slots(slots)
    for i, stage in enumerate(stages):
        if not _stage_satisfied(i, stage, current):
            return "pending"
    return "approved"


def _advance(
    store: Any,
    execution_id: str,
    stages: tuple[Stage, ...],
    *,
    now: datetime.datetime,
) -> None:
    """Materialize every stage up to (and including) the first unsatisfied one: its planned slots
    become pending (deadline clock starts NOW), and auto stages sign themselves as they are
    reached. Idempotent — already-pending/signed slots are untouched."""
    slots = store.signature_slots(execution_id)
    current = _live_slots(slots)
    for i, stage in enumerate(stages):
        if stage.kind == "auto":
            auto_slot = next(
                (s for s in current if s["stage"] == i and s["by_kind"] == "policy"), None
            )
            if auto_slot is not None and auto_slot["status"] == "planned":
                store.set_signature_status(
                    execution_id,
                    auto_slot["unit_idx"],
                    "signed",
                    actor=f"policy:{stage.policy}",
                    expect="planned",
                )
                current = _live_slots(store.signature_slots(execution_id))
            if _stage_satisfied(i, stage, current):
                continue
            return
        for slot in current:
            if slot["stage"] == i and slot["status"] == "planned":
                unit = next((u for u in stage.units if u.key == slot["unit_key"]), None)
                store.activate_signature_slot(
                    execution_id,
                    slot["unit_idx"],
                    deadline=_deadline(unit, now) if unit is not None else None,
                )
        current = _live_slots(store.signature_slots(execution_id))
        if not _stage_satisfied(i, stage, current):
            return


def begin(
    store: Any,
    execution_id: str,
    strategy: Strategy | dict[str, Any],
    *,
    inputs: dict[str, Any],
    risk: str,
    workspace: str = "",
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Materialize the signature slots for a prepared subject and activate stage 0. Returns
    `{"status": ..., "branch": ...}` or a refusal. NO effect beyond rows — approval-completeness
    is reported, never acted on here (the commit lives with the caller, the ONLY effect path)."""
    now = now or datetime.datetime.now(datetime.UTC)
    flat = flatten(strategy, inputs)
    if flat.refusal is not None:
        return {"refusal": flat.refusal}
    if any(stage.kind == "auto" for stage in flat.stages) and risk not in _AUTO_ALLOWED_RISK:
        return _refusal(
            "V9_AUTO_FORBIDDEN",
            f"auto() approval is not lawful at risk {risk} — automatic approval stops at "
            "MEDIUM (the floor only rises)",
            risk=risk,
        )
    idx = store.next_signature_unit_idx(execution_id)
    for stage_no, stage in enumerate(flat.stages):
        if stage.kind == "auto":
            store.add_signature_slot(
                execution_id,
                unit_idx=idx,
                unit_key=f"s{stage_no}.auto",
                stage=stage_no,
                by_kind="policy",
                role=stage.policy,
                workspace=workspace,
                status="planned",
            )
            idx += 1
            continue
        for unit in stage.units:
            store.add_signature_slot(
                execution_id,
                unit_idx=idx,
                unit_key=unit.key,
                stage=stage_no,
                by_kind=unit.by,
                role=unit.name,
                distinct_from=unit.distinct_from,
                quorum_k=stage.k,
                quorum_distinct=stage.distinct,
                workspace=workspace,
                status="planned",
                timeout_route=unit.timeout_route,
            )
            idx += 1
    _advance(store, execution_id, flat.stages, now=now)
    return {
        "status": overall_status(flat.stages, store.signature_slots(execution_id)),
        "branch": flat.branch,
    }


# ── the decision surface ─────────────────────────────────────────────────────────────────────


def _matches(slot: dict[str, Any], actor: str, role: str | None) -> bool:
    if slot["by_kind"] == "person":
        return slot["role"] == actor
    return role is not None and slot["role"] == role


def sign(
    store: Any,
    execution_id: str,
    strategy: Strategy | dict[str, Any],
    *,
    inputs: dict[str, Any],
    actor: str,
    role: str | None = None,
    decision: str = "approved",
    prepared_by: str = "",
    now: datetime.datetime | None = None,
    actor_roles: list[str] | None = None,
) -> dict[str, Any]:
    """One unit's decision on the subject. Enforces SoD structurally (the preparer can NEVER
    sign their own card; `distinct_from` and quorum-distinctness refuse duplicate identities),
    advances Seq stages on approval, and cancels everything live on a rejection. Returns the new
    overall status or a refusal payload — never an exception.

    `actor_roles` (when provided by the trusted BFF) is the VERIFIED set of roles the actor
    holds — the strategy-role → identity join. A `role` claim outside that set is refused:
    a CfoTwoKey slot can only be signed by an identity that actually holds Finance/CFO."""
    now = now or datetime.datetime.now(datetime.UTC)
    if not actor:
        return _refusal("ACTOR_REQUIRED", "a signature needs a named actor")
    if role and actor_roles is not None:
        held = {str(r).lower() for r in actor_roles}
        if role.lower() not in held:
            return _refusal(
                "ROLE_NOT_HELD",
                f"actor {actor!r} does not hold the role {role!r} — a signature role must be "
                "one of the identity's verified roles",
                actor=actor,
                role=role,
            )
    flat = flatten(strategy, inputs)
    if flat.refusal is not None:
        return {"refusal": flat.refusal}
    slots = store.signature_slots(execution_id)
    current = _live_slots(slots)
    status = overall_status(flat.stages, slots)
    if status != "pending":
        return _refusal(
            "ALREADY_DECIDED", f"this subject is already {status}", status=status
        )
    # SoD, invariant I6: the preparer of a card cannot sign it — structurally, whatever slot.
    if prepared_by and actor == prepared_by:
        return _refusal(
            "SOD_VIOLATION",
            f"{actor!r} prepared this subject and cannot sign it (preparer-not-approver)",
            actor=actor,
        )
    slot = next(
        (s for s in current if s["status"] == "pending" and _matches(s, actor, role)), None
    )
    if slot is None:
        return _refusal(
            "NO_PENDING_UNIT",
            f"no pending signature slot is addressed to actor {actor!r}"
            + (f" as role {role!r}" if role else ""),
            actor=actor,
            role=role,
        )
    signed = [s for s in current if s["status"] == "signed" and s.get("actor")]
    # distinct_from: the signer must differ from whoever signed as each named identity.
    for constraint in slot["distinct_from"]:
        if constraint == PREPARER:
            continue  # the preparer check above already covers it, unconditionally
        if any(s["role"] == constraint and s["actor"] == actor for s in signed):
            return _refusal(
                "SOD_VIOLATION",
                f"{actor!r} already signed as {constraint!r} and this unit demands a distinct "
                "identity (distinct_from)",
                actor=actor,
                distinct_from=constraint,
            )
    # Quorum distinctness: k signatures from DISTINCT actors — a second signature by the same
    # actor in the same STAGE can never advance its count, so it refuses honestly. (Across Seq
    # stages the same actor may lawfully sign twice unless a unit's distinct_from forbids it.)
    if any(s["actor"] == actor and s["stage"] == slot["stage"] for s in signed):
        return _refusal(
            "DUPLICATE_SIGNATURE",
            f"{actor!r} already signed this subject — quorum counts distinct actors only",
            actor=actor,
        )
    if decision == "rejected":
        store.set_signature_status(
            execution_id, slot["unit_idx"], "rejected", actor=actor, expect="pending"
        )
        _cancel_live(store, execution_id)
        return {"status": "rejected", "unit_idx": slot["unit_idx"]}
    if not store.set_signature_status(
        execution_id, slot["unit_idx"], "signed", actor=actor, expect="pending"
    ):
        return _refusal("ALREADY_DECIDED", "this slot was settled concurrently")
    _advance(store, execution_id, flat.stages, now=now)
    return {
        "status": overall_status(flat.stages, store.signature_slots(execution_id)),
        "unit_idx": slot["unit_idx"],
    }


def _cancel_live(store: Any, execution_id: str) -> int:
    n = 0
    for slot in store.signature_slots(execution_id):
        if slot["status"] in _LIVE and store.set_signature_status(
            execution_id, slot["unit_idx"], "cancelled", expect=_LIVE
        ):
            n += 1
    return n


# ── material edits: void collected signatures, re-hold ───────────────────────────────────────


def rehold(
    store: Any,
    execution_id: str,
    strategy: Strategy | dict[str, Any],
    *,
    inputs: dict[str, Any],
    risk: str,
    workspace: str = "",
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """A MATERIAL edit changed the subject: every collected signature is VOIDED (`superseded`,
    audit row kept — who signed what they no longer approved is the trail), live slots are
    retired, and a fresh generation of slots re-holds the strategy against the EDITED inputs
    (a Conditional may lawfully route differently now). Returns `begin`'s shape plus the count
    of voided signatures."""
    voided = 0
    for slot in store.signature_slots(execution_id):
        if slot["status"] == "signed":
            if store.set_signature_status(
                execution_id, slot["unit_idx"], "superseded", expect="signed"
            ):
                voided += 1
        elif slot["status"] in _LIVE:
            store.set_signature_status(execution_id, slot["unit_idx"], "cancelled", expect=_LIVE)
    out = begin(
        store,
        execution_id,
        strategy,
        inputs=inputs,
        risk=risk,
        workspace=workspace,
        now=now,
    )
    if "refusal" not in out:
        out["superseded"] = voided
    return out


# ── deadlines: the tick sweep (parked_runs pattern) ──────────────────────────────────────────


def sweep_due(
    store: Any, *, now: datetime.datetime | None = None
) -> list[dict[str, Any]]:
    """Enforce unit timeouts — called from the SAME external clock as /automations/tick.
    `escalate(to)` retires the due slot and re-holds a fresh one addressed to `to` (no deadline:
    the escalation target has no declared timeout of its own); `reject` (or a missing route —
    fail closed) times the slot out, which rejects the whole subject, cancelling its live
    siblings. Returns one action record per due slot."""
    now = now or datetime.datetime.now(datetime.UTC)
    actions: list[dict[str, Any]] = []
    for slot in store.due_signature_slots(now.isoformat()):
        execution_id = slot["execution_id"]
        route = slot.get("timeout_route") or {"kind": "reject"}
        if route.get("kind") == "escalate" and route.get("to"):
            if not store.set_signature_status(
                execution_id, slot["unit_idx"], "escalated", expect="pending"
            ):
                continue  # settled concurrently
            idx = store.next_signature_unit_idx(execution_id)
            store.add_signature_slot(
                execution_id,
                unit_idx=idx,
                unit_key=slot["unit_key"],
                stage=slot["stage"],
                by_kind="role",
                role=route["to"],
                distinct_from=slot["distinct_from"],
                quorum_k=slot["quorum_k"],
                quorum_distinct=slot["quorum_distinct"],
                workspace=slot["workspace"],
                status="pending",
            )
            actions.append(
                {
                    "execution_id": execution_id,
                    "unit_idx": slot["unit_idx"],
                    "action": "escalated",
                    "to": route["to"],
                }
            )
            continue
        if not store.set_signature_status(
            execution_id, slot["unit_idx"], "timed_out", expect="pending"
        ):
            continue
        _cancel_live(store, execution_id)
        actions.append(
            {"execution_id": execution_id, "unit_idx": slot["unit_idx"], "action": "rejected"}
        )
    return actions


# ── deterministic strategy state (for the card body — NO timestamps) ─────────────────────────


def state(
    store: Any,
    execution_id: str,
    strategy: Strategy | dict[str, Any],
    *,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """The strategy state a Permission Card renders: units, who signed, who is pending, and the
    distinct/two-key status. Deterministic — actor names and statuses only, timestamps live on
    the rows (envelope data), never in this body."""
    flat = flatten(strategy, inputs)
    if flat.refusal is not None:
        return {"refusal": flat.refusal}
    slots = store.signature_slots(execution_id)
    current = _live_slots(slots)
    units = [
        {
            "key": s["unit_key"],
            "stage": s["stage"],
            "by": s["by_kind"],
            "name": s["role"],
            "status": s["status"],
            "actor": s["actor"],
        }
        for s in current
    ]
    stage_state = []
    for i, stage in enumerate(flat.stages):
        stage_slots = [s for s in current if s["stage"] == i]
        stage_state.append(
            {
                "stage": i,
                "kind": stage.kind,
                "k": stage.k if stage.kind == "units" else 0,
                "distinct": stage.distinct,
                "signed": len([s for s in stage_slots if s["status"] == "signed"]),
                "satisfied": _stage_satisfied(i, stage, current),
            }
        )
    return {
        "branch": flat.branch,
        "units": units,
        "signed": [s["actor"] for s in current if s["status"] == "signed" and s["actor"]],
        "pending": [
            {"key": s["unit_key"], "by": s["by_kind"], "name": s["role"]}
            for s in current
            if s["status"] == "pending"
        ],
        "stages": stage_state,
        "status": overall_status(flat.stages, slots),
    }


__all__ = [
    "FlattenResult",
    "Stage",
    "StageUnit",
    "begin",
    "duration_seconds",
    "flatten",
    "overall_status",
    "rehold",
    "sign",
    "state",
    "sweep_due",
]
