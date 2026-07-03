"""The SSOT version lock — `content_hash` over the **Cycle AST**, not the derived IR.

The lowered `WosoolProgram` is deterministic from the Cycle, so its hash is derivable and cannot
tell apart two cycles that lower identically but differ in authoring-time metadata (intent, owner,
policies). Hashing the AST is therefore the true lock: a registered cycle re-runs the exact bytes a
human approved. Same canonicalisation as `automation.models.content_hash` (`by_alias` so
`ForeachNode.as_` serialises as `as`; sorted keys + tight separators ⇒ identical cycles hash
identically).
"""

from __future__ import annotations

import hashlib
import json

from nilscript.cycle.models import Cycle


def cycle_content_hash(cycle: Cycle) -> str:
    dumped = cycle.model_dump(by_alias=True, mode="json")
    if dumped.get("implements") is None:
        # v0.3 seam, hash-stable: an absent `implements` and a None one are the SAME statement,
        # so dropping the null keeps every pre-implements cycle's hash (its version lock) intact.
        dumped.pop("implements", None)
    canonical = json.dumps(
        dumped,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
