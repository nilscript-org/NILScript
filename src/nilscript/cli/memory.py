"""Self-evolving memory & skills with safety guardrails (plan §5.4, §8).

When a repair succeeds, the lesson is worth keeping two ways: a **Reflexion lesson** (verbal — "an
invoice needs an existing customer; auto-create from party_id") and a **Voyager-style skill** (a
reusable macro). The known foot-gun (plan §8) is self-editing memory without versioning/audit —
catastrophic forgetting and poisoning. So this store is **append-only and content-addressed**: a
revision SUPERSEDES a prior entry by id (history is never destroyed, every state is reconstructable),
and feeding a lesson back into the manifest is a **proposal** the caller confirms — never a silent
write.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class MemoryStore:
    """An append-only JSONL ledger of lessons and skills. Nothing is ever edited in place."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _append(self, kind: str, payload: dict[str, Any], supersedes: str | None) -> dict[str, Any]:
        entries = self._entries()
        canonical = json.dumps({"kind": kind, "payload": payload}, sort_keys=True, ensure_ascii=False)
        # content-addressed id; seq disambiguates identical payloads recorded twice.
        digest = hashlib.sha256(f"{len(entries)}:{canonical}".encode("utf-8")).hexdigest()[:16]
        entry = {"seq": len(entries), "id": digest, "kind": kind, "payload": payload, "supersedes": supersedes}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def add_lesson(self, text: str, *, verb: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Record a Reflexion lesson. Returns the stored entry (with its version id)."""
        return self._append("lesson", {"text": text, "verb": verb, "tags": tags or []}, supersedes=None)

    def add_skill(self, name: str, steps: list[dict[str, Any]], *, supersedes: str | None = None) -> dict[str, Any]:
        """Add (or, via `supersedes`, revise) a Voyager-style reusable skill macro."""
        return self._append("skill", {"name": name, "steps": steps}, supersedes=supersedes)

    def history(self, kind: str | None = None) -> list[dict[str, Any]]:
        """Every entry ever written (audit trail), optionally filtered by kind."""
        return [e for e in self._entries() if kind is None or e["kind"] == kind]

    def active(self, kind: str | None = None) -> list[dict[str, Any]]:
        """Current view: entries not superseded by a later revision. History is preserved on disk."""
        entries = self._entries()
        superseded = {e["supersedes"] for e in entries if e.get("supersedes")}
        return [e for e in entries if e["id"] not in superseded and (kind is None or e["kind"] == kind)]


def propose_manifest_patch(lesson: dict[str, Any]) -> dict[str, Any] | None:
    """Turn a confirmed lesson into a manifest PATCH proposal (plan §5.4 — close the loop).

    Returns a manifest fragment to be reviewed/merged, or None if the lesson has no structural
    content. GUARDRAIL: this only *proposes* — it never writes a manifest. The caller (a human or a
    tier-scoped policy) confirms before `manifest merge` applies it.
    """
    payload = lesson.get("payload", lesson)
    verb = payload.get("verb")
    learned = payload.get("learned_requirement")  # {"field":..., "kind":...}
    if not verb or not isinstance(learned, dict) or not learned.get("field"):
        return None
    return {
        "verbs": {
            verb: {
                "hidden_requirements": [
                    {"field": learned["field"], "kind": learned.get("kind", "required_scalar")}
                ]
            }
        }
    }
