"""State-witness (TOCTOU precondition) — the canonical, adapter-agnostic helper.

NIL's propose→approve→commit lifecycle opens a window: a human (or policy) approves a proposal, and
the world can change before COMMIT lands. The witness closes it. At PROPOSE the adapter snapshots the
SSOT values of the fields the write will touch and binds their canonical hash to the proposal; at
COMMIT it re-snapshots and compares. A drift fails closed with `PRECONDITION_FAILED` (Annex A) — the
kernel re-previews rather than writing against stale reality. This is reference-legibility's sibling:
both make the kernel refuse to act on something it can no longer stand behind.

Pure given the snapshot, so it is unit-tested without a backend. A create (no prior record) yields an
empty witness and never blocks. See docs/reference-legibility.md and the conformance matrix.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def compute_witness(state: dict[str, Any]) -> str:
    """Canonical sha256 over an SSOT state snapshot (the fields a write will touch). Order-independent;
    `default=str` tolerates dates/ids. Empty snapshot → "" (no precondition, e.g. a create)."""
    if not state:
        return ""
    canonical = json.dumps(state, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def witness_changed(bound: str, current: str) -> bool:
    """True iff a non-empty bound witness no longer matches the current state — the world drifted
    between propose/approve and commit. An empty bound (create / no prior state) never blocks."""
    return bool(bound) and bound != current
