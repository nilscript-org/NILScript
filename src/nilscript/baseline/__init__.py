"""nilscript.baseline — the versioned baseline bundle + its deterministic applier.

THE SaaS invariant this package owns: a single versioned bundle in git is the SSOT for what
every workspace *is*; one deterministic `apply_baseline` materializes it identically for
workspace #1 and #10,000; an upgrade is a BASELINE_VERSION bump + per-workspace reconcile.

The bundle: approval strategies + the governed capability catalog (published + fail-closed
drafts) + their implementing cycles (see catalog.py). The applier is IDEMPOTENT — registration
dedups by content hash (a re-apply of an unchanged bundle writes nothing) and every apply
stamps the workspace row with the installed baseline_version, which is what `reconcile`
compares against fleet-wide.
"""

from __future__ import annotations

from typing import Any

from nilscript.baseline import catalog

# Bump on ANY change to catalog.py (or future bundle parts). The applier stamps this onto
# workspaces.baseline_version — a fleet where every row equals BASELINE_VERSION is converged.
BASELINE_VERSION = "1.0.0"


def apply_baseline(store: Any, workspace: str) -> dict[str, Any]:
    """Materialize the current baseline bundle into `workspace` (idempotent reconcile).

    Order matters: strategies first (capabilities reference them by id), then implementing
    cycles (capabilities point at them), then the capabilities themselves. Registration is
    content-hash-deduped by the store, so re-applying an unchanged bundle is a no-op that
    still (re)pins the target state and stamps baseline_version.
    """
    if not workspace:
        raise ValueError("workspace is required")
    from nilscript.capability import Capability, capability_content_hash
    from nilscript.strategy import Strategy, strategy_content_hash

    result: dict[str, Any] = {
        "workspace": workspace,
        "baseline_version": BASELINE_VERSION,
        "strategies": [],
        "cycles": [],
        "published": [],
        "drafted": [],
    }

    # 1) strategies — register auto-increments an integer version; publish THAT version (never assume 1).
    for sid, root in catalog.STRATEGIES.items():
        strat = Strategy.model_validate(
            {"nil": "strategy/0.1", "strategy_id": sid, "workspace": workspace, "version": 1, "root": root})
        reg = store.register_strategy(workspace=workspace, strategy_id=sid,
                                      content_hash=strategy_content_hash(strat),
                                      body=strat.model_dump(by_alias=True, mode="json"),
                                      state="published")
        store.set_strategy_state(workspace, sid, reg["version"], "published")
        result["strategies"].append(sid)

    # 2) implementing cycles — REAL executable plan (the runner walks plan, NOT the .flow source;
    # an empty pipeline dispatched nothing, which is why approved sends never left the building).
    for cid, (name_en, plan, source) in catalog.cycles_for(workspace).items():
        store.register_automation(workspace=workspace, automation_id=cid, content_hash=f"cat-{cid}-plan",
                                  name={"en": name_en, "ar": name_en}, plan=plan,
                                  trigger={"type": "manual"}, state="active", kind="cycle", source=source)
        result["cycles"].append(cid)

    # 3) capabilities — register with the target state AND pin that state on the returned version
    # (register auto-versions; a stale pre-existing row must not shadow the new one).
    def _register(body: dict[str, Any], state: str) -> str:
        cp = Capability.model_validate(body)
        reg = store.register_capability(workspace=workspace, capability_id=cp.capability_id,
                                        content_hash=capability_content_hash(cp),
                                        body=cp.model_dump(by_alias=True, mode="json"),
                                        state=state)
        store.set_capability_state(workspace, cp.capability_id, reg["version"], state)
        return cp.capability_id

    result["published"] = [_register(c, "published") for c in catalog.published_for(workspace)]
    result["drafted"] = [_register(c, "draft") for c in catalog.drafts_for(workspace)]

    # 4) stamp — the reconcile signal. Done LAST so a half-applied bundle never claims the version.
    if hasattr(store, "set_workspace_baseline"):
        store.set_workspace_baseline(workspace, BASELINE_VERSION)
    return result


__all__ = ["BASELINE_VERSION", "apply_baseline", "catalog"]
