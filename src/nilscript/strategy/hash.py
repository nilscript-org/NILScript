"""The version lock — `content_hash` over the **Strategy AST** (invariant I4).

Same canonicalisation as `capability.hash` / `cycle.hash`: SHA-256 over sorted-key canonical JSON
(`by_alias` so `Conditional.else_` serialises as `else`), so identical strategies hash identically
and the registry's idempotent-register / supersede disciplines apply unchanged.
"""

from __future__ import annotations

import hashlib
import json

from nilscript.strategy.models import Strategy


def strategy_content_hash(strategy: Strategy) -> str:
    canonical = json.dumps(
        strategy.model_dump(by_alias=True, mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
