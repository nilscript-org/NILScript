"""Read-only access to the bundled NIL standard (core schemas + verb profiles).

Every CLI tool reads the standard through here and ONLY here. Zero backend specifics live in
this package — the tools generate scaffolding and verify conformance against the standard; they
never know anything about any particular system of record.

Deprecation/parking is read from a SINGLE machine-readable source: the profile's own
`"deprecated": true` keyword (JSON Schema 2020-12). The tools never carry a hand-maintained list
of parked verbs, so a verb deprecated in a future spec is picked up automatically.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

# Wire/path version of the bundled schemas (the `/nil/v0.1` surface). This is the transport
# version, distinct from the package version — it does not bump when a profile's args evolve.
SPEC_VERSION = "0.1"

# core schema filename -> OpenAPI/component name. The order here is the order components are
# emitted, so the most fundamental shape (Envelope) comes first.
CORE_SCHEMAS: dict[str, str] = {
    "envelope.schema.json": "Envelope",
    "propose.schema.json": "ProposeBody",
    "proposal.schema.json": "ProposalBody",
    "commit.schema.json": "CommitBody",
    "status.schema.json": "StatusBody",
    "query.schema.json": "QueryBody",
    "query-answer.schema.json": "QueryAnswer",
    "event.schema.json": "EventBody",
    "rollback.schema.json": "RollbackBody",
    "grant.schema.json": "Grant",
}

_GAP_RE = re.compile(r"GAP-\d+")


def spec_root() -> Path:
    """Filesystem path to the bundled standard, e.g. `.../nilscript/sdk/spec/0.1`."""
    return Path(str(files("nilscript") / "sdk" / "spec" / SPEC_VERSION))


def load_core_schema(filename: str) -> dict[str, Any]:
    return json.loads((spec_root() / filename).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Verb:
    """One verb in the standard, derived from its arg-schema profile file."""

    name: str  # "commerce.create_product"
    namespace: str  # "commerce"
    action: str  # "create_product"
    profile_dir: str  # "commerce-v1"
    path: Path
    title: str
    required: tuple[str, ...]
    # Read straight from the profile's `"deprecated": true` keyword. A deprecated verb is parked:
    # `scaffold-shim` must NOT generate a fillable translation stub for it.
    deprecated: bool = False
    gap_ref: str | None = None  # e.g. "GAP-001", the gap that parked it (if cited in the profile)

    @property
    def tier_floor(self) -> str | None:
        """The fixed minimum tier, where the profile title pins one (`... floor HIGH ...`)."""
        for tier in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            if f"floor {tier}" in self.title:
                return tier
        return None


def _namespace(profile_dir: str) -> str:
    """`commerce-v1` -> `commerce` (drop the profile-set version suffix)."""
    return profile_dir.rsplit("-v", 1)[0]


def _gap_ref(doc: dict[str, Any]) -> str | None:
    """First `GAP-NNN` cited anywhere in the profile (title/$comment/field descriptions)."""
    match = _GAP_RE.search(json.dumps(doc, ensure_ascii=False))
    return match.group(0) if match else None


@lru_cache(maxsize=1)
def all_verbs() -> tuple[Verb, ...]:
    """Every verb in the standard, sorted, derived from the profile files on disk.

    `*.response.json` files describe a QUERY's answer shape, not a verb, and are skipped.
    """
    root = spec_root() / "profiles"
    verbs: list[Verb] = []
    for profile_dir in sorted(p.name for p in root.iterdir() if p.is_dir()):
        for profile in sorted((root / profile_dir).glob("*.json")):
            if profile.name.endswith(".response.json"):
                continue
            doc = json.loads(profile.read_text(encoding="utf-8"))
            action = profile.stem
            deprecated = bool(doc.get("deprecated", False))
            verbs.append(
                Verb(
                    name=f"{_namespace(profile_dir)}.{action}",
                    namespace=_namespace(profile_dir),
                    action=action,
                    profile_dir=profile_dir,
                    path=profile,
                    title=str(doc.get("title", "")),
                    required=tuple(doc.get("required", ())),
                    deprecated=deprecated,
                    gap_ref=_gap_ref(doc) if deprecated else None,
                )
            )
    return tuple(verbs)


def active_verbs() -> tuple[Verb, ...]:
    """Non-deprecated verbs — what `scaffold-shim` generates translation stubs for."""
    return tuple(v for v in all_verbs() if not v.deprecated)


def find_verb(name: str) -> Verb | None:
    return next((v for v in all_verbs() if v.name == name), None)


def load_profile(name: str) -> dict[str, Any] | None:
    verb = find_verb(name)
    if verb is None:
        return None
    return json.loads(verb.path.read_text(encoding="utf-8"))
