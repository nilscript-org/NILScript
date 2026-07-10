"""The version lock — `content_hash` over the **Capability AST** (invariant I4).

Same canonicalisation as `cycle.hash.cycle_content_hash` and `automation.models.content_hash`:
SHA-256 over sorted-key, tight-separator canonical JSON, so identical capabilities hash identically
regardless of authoring key order — the registry's idempotent-register / supersede-never-edit
disciplines hang off this one function.
"""

from __future__ import annotations

import hashlib
import json

from nilscript.capability.models import Capability


def capability_content_hash(capability: Capability) -> str:
    canonical = json.dumps(
        capability.model_dump(by_alias=True, mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
