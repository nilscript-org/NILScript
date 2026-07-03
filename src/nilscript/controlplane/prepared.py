"""B2 — PreparedExecution + the deterministic Permission Card builder.

`prepare(...)` turns (workspace, capability_id, inputs, prepared_by) into ONE persisted subject
whose approval the strategy interpreter (`strategy_exec`) drives. The card JSON is assembled BY
CODE ONLY (invariant I5 — an LLM may seed `inputs`, never assemble the card), field by field
from deterministic sources:

  capability / version / hash    the pinned registry record
  seeded inputs + `modifiable`   capability.inputs × provided values, validated against the
                                 typed contract (missing / typed-wrong → structured refusal
                                 listing fields); modifiable = the NOT-required inputs (required
                                 slots are locked, the resolved/modifiable convention)
  strategy state                 the interpreter (units, who signed, who's pending, two-key)
  affected systems               the default implementing cycle's step verbs × adapter registry
  risk / reversibility           the capability floor; reversibility from declared compensation
  prepared_by                    stamped for SoD (invariant I6)

BYTE-DETERMINISM: the card body carries NO timestamps, ids, or randomness — same registry state
+ same inputs ⇒ byte-identical `canonical_card` output. Envelope fields (prepared_id,
created_at, per-signature decided_at) are stamped OUTSIDE the hashed body.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from nilscript.controlplane import strategy_exec
from nilscript.cycle import cycle_slug

# The typed-contract checkers, by FieldType.kind. Least-surprise duck typing: an entity slot
# takes an id (str/int) or a record (dict); a scalar refuses containers; a list takes a list.
_KIND_OK = {
    "entity": lambda v: isinstance(v, (str, int, dict)) and not isinstance(v, bool),
    "list": lambda v: isinstance(v, list),
    "scalar": lambda v: isinstance(v, (str, int, float, bool)),
}


def _refusal(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"refusal": {"code": code, "message": message, **extra}}


def validate_inputs(
    capability_body: dict[str, Any], inputs: dict[str, Any]
) -> dict[str, Any] | None:
    """Validate seeded inputs against the capability's typed contract. Returns a structured
    refusal LISTING the offending fields (missing / wrong_type / unknown), or None when the
    contract is satisfied. Unknown fields refuse too — fail closed, never silently dropped."""
    fields = {f["name"]: f for f in capability_body.get("inputs", [])}
    missing = sorted(
        name for name, f in fields.items() if f.get("required") and name not in inputs
    )
    unknown = sorted(k for k in inputs if k not in fields)
    wrong = sorted(
        name
        for name, value in inputs.items()
        if name in fields
        and not _KIND_OK.get(fields[name].get("type", {}).get("kind", "scalar"), lambda _: False)(
            value
        )
    )
    if missing or unknown or wrong:
        return _refusal(
            "INPUT_CONTRACT",
            "inputs do not satisfy the capability's typed contract",
            missing=missing,
            wrong_type=wrong,
            unknown=unknown,
        )["refusal"]
    return None


def modifiable_of(capability_body: dict[str, Any]) -> list[str]:
    """The editable input paths: everything NOT marked required. A required slot is locked —
    editing it would change what was contractually demanded, not tune it."""
    return sorted(
        f["name"] for f in capability_body.get("inputs", []) if not f.get("required")
    )


def affected_systems(store: Any, workspace: str, capability_body: dict[str, Any]) -> list[str]:
    """The backends this capability touches: the DEFAULT implementing cycle's step verbs'
    namespaces (`odoo.crm_create_lead` → `odoo`), labelled through the adapter registry when a
    matching adapter is registered. Sorted for determinism; [] when the cycle is not registered
    (an honest empty, never a guess)."""
    cycle_id = (capability_body.get("implemented_by") or {}).get("default") or ""
    row = store.get_automation(workspace, cycle_slug(cycle_id)) if cycle_id else None
    source = (row or {}).get("source") or {}
    namespaces: set[str] = set()
    for step in ((source.get("flow") or {}).get("steps") or []):
        for verb in (step.get("use"), (step.get("compensate_with") or {}).get("use")):
            if isinstance(verb, str) and "." in verb:
                namespaces.add(verb.split(".", 1)[0])
    labels: dict[str, str] = {}
    for adapter in store.list_adapters(workspace):
        for key in (adapter.get("system"), adapter.get("adapter_id")):
            if key:
                labels.setdefault(key, adapter.get("label") or adapter.get("system") or key)
    return sorted(labels.get(ns, ns) for ns in namespaces)


def card_body(
    row: dict[str, Any],
    *,
    capability_row: dict[str, Any],
    strategy_row: dict[str, Any],
    strategy_state: dict[str, Any],
) -> dict[str, Any]:
    """The Permission Card body — every field from a deterministic source, no timestamps."""
    body = capability_row.get("body") or {}
    return {
        "nil": "prepared/0.1",
        "capability": {
            "id": row["capability_id"],
            "version": body.get("version"),
            "registry_version": capability_row.get("version"),
            "content_hash": capability_row.get("content_hash"),
        },
        "intent": body.get("intent") or {},
        "inputs": row["inputs"],
        "modifiable": row["modifiable"],
        "strategy": {
            "id": row["strategy_id"],
            "registry_version": strategy_row.get("version"),
            "content_hash": strategy_row.get("content_hash"),
            "state": strategy_state,
        },
        "affected_systems": row["affected_systems"],
        "risk": row["risk"],
        "reversibility": row["reversibility"],
        "compensation": {"via": row.get("compensation"), "covered": bool(row.get("compensation"))},
        "prepared_by": row["prepared_by"],
    }


def canonical_card(card: dict[str, Any]) -> str:
    """The one canonical serialization — sorted keys, tight separators — so byte-determinism is
    a property of the builder, not of dict ordering luck."""
    return json.dumps(card, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def card_hash(card: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_card(card).encode("utf-8")).hexdigest()


def card_view(store: Any, row: dict[str, Any]) -> dict[str, Any]:
    """The full card envelope for one prepared row: the deterministic body, its hash, and the
    NON-deterministic audit data (timestamps, deadlines, slot indices) OUTSIDE the body."""
    capability_row = (
        store.get_capability(row["workspace"], row["capability_id"], row["capability_version"])
        or {}
    )
    strategy_row = (
        store.get_strategy(row["workspace"], row["strategy_id"], row["strategy_version"]) or {}
    )
    state = strategy_exec.state(
        store, row["prepared_id"], strategy_row.get("body") or {}, inputs=row["inputs"]
    )
    card = card_body(
        row, capability_row=capability_row, strategy_row=strategy_row, strategy_state=state
    )
    return {
        "prepared_id": row["prepared_id"],
        "workspace": row["workspace"],
        "status": row["status"],
        "reason": row.get("reason") or "",
        "created_at": row["created_at"],
        "decided_at": row.get("decided_at"),
        "card": card,
        "card_hash": card_hash(card),
        "commit_result": row.get("commit_result"),
        "signatures": [
            {
                "unit_idx": s["unit_idx"],
                "unit_key": s["unit_key"],
                "stage": s["stage"],
                "by": s["by_kind"],
                "name": s["role"],
                "actor": s["actor"],
                "status": s["status"],
                "decided_at": s["decided_at"],
                "deadline": s["deadline"],
            }
            for s in store.signature_slots(row["prepared_id"])
        ],
    }


def prepare(
    store: Any,
    *,
    workspace: str,
    capability_id: str,
    inputs: dict[str, Any],
    prepared_by: str,
    version: int | None = None,
    now: Any = None,
) -> dict[str, Any]:
    """The prepare step: validate, pin, persist, and hold the strategy's first stage. Returns
    `{"ok": True, "prepared": <card envelope>}` or `{"refusal": {...}}` — refusals are answers.
    NO effect beyond rows: the commit (the ONLY effect path) fires only on full approval."""
    if not workspace:
        return _refusal("WORKSPACE_REQUIRED", "prepare is workspace-pinned — no tenant, no card")
    if not prepared_by:
        return _refusal(
            "PREPARER_REQUIRED", "SoD stamps the preparer at prepare time — no identity, no card"
        )
    capability_row = store.get_capability(workspace, capability_id, version)
    if capability_row is None:
        return _refusal(
            "UNKNOWN_CAPABILITY",
            f"no capability {capability_id!r} in workspace {workspace!r}",
            capability_id=capability_id,
        )
    body = capability_row.get("body") or {}
    contract_refusal = validate_inputs(body, inputs)
    if contract_refusal is not None:
        return {"refusal": contract_refusal}
    strategy_row = store.get_strategy(workspace, body.get("strategy") or "")
    if strategy_row is None:
        return _refusal(
            "UNKNOWN_STRATEGY",
            f"capability {capability_id!r} names strategy {body.get('strategy')!r} which is not "
            "registered — a dangling governance pointer cannot gate anything",
            strategy=body.get("strategy"),
        )
    risk = body.get("risk") or "HIGH"  # no declared floor reads as HIGH — fail closed
    prepared_id = f"prep-{uuid.uuid4().hex[:12]}"
    begun = strategy_exec.begin(
        store,
        prepared_id,
        strategy_row["body"],
        inputs=inputs,
        risk=risk,
        workspace=workspace,
        now=now,
    )
    if "refusal" in begun:
        return begun
    row = store.create_prepared(
        prepared_id,
        workspace=workspace,
        capability_id=capability_id,
        capability_version=capability_row["version"],
        content_hash=capability_row["content_hash"],
        strategy_id=strategy_row["strategy_id"],
        strategy_version=strategy_row["version"],
        strategy_hash=strategy_row["content_hash"],
        inputs=inputs,
        modifiable=modifiable_of(body),
        prepared_by=prepared_by,
        branch=begun.get("branch"),
        risk=risk,
        reversibility="REVERSIBLE" if body.get("compensation") else "IRREVERSIBLE",
        compensation=body.get("compensation"),
        affected_systems=affected_systems(store, workspace, body),
        status="approved" if begun["status"] == "approved" else "pending",
    )
    return {"ok": True, "prepared": card_view(store, row)}


__all__ = [
    "affected_systems",
    "canonical_card",
    "card_body",
    "card_hash",
    "card_view",
    "modifiable_of",
    "prepare",
    "validate_inputs",
]
