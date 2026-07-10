"""Registry-level invariants — the anti-explosion spine (Wave 4 §9/§14.2; Encaps D7 / Risks 3, 5, 8).

These are the gates that a single `Capability` cannot check about itself because they are properties of
the WHOLE set: one canonical concept (no forks), a consistent owner/domain per concept, valid pinned
SemVer (no `latest`), and an acyclic dependency DAG. They are PURE functions over capability bodies so
they double as executable invariants (Master Plan E1) — the registration endpoint calls
`validate_registry(existing + [candidate])` and rejects on any violation involving the candidate.

Capability bodies here are the same dicts the store persists (a serialized `capability/models.Capability`)
OR `Capability` instances — `_field` reads both, so the registry never depends on which it is handed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from nilscript.capability.models import SEMVER_PATTERN

_SEMVER_RE = re.compile(SEMVER_PATTERN)

# Violation codes — stable strings so callers (endpoint, tests, UI) can branch without prose matching.
DUPLICATE_CONCEPT = "duplicate_concept"  # same (id, version), different content — a real fork
INCONSISTENT_OWNER = "inconsistent_owner"  # one concept, conflicting owner/domain across versions
BAD_SEMVER = "bad_semver"  # version isn't MAJOR.MINOR[.PATCH] (this is how `latest` is rejected)
DEPENDENCY_CYCLE = "dependency_cycle"  # requires/enables form a cycle in the DAG


@dataclass(frozen=True)
class RegistryViolation:
    code: str
    capability_id: str
    detail: str


def _field(cap: "dict[str, Any] | Any", name: str, default: Any = None) -> Any:
    """Read a field off a capability whether it's a dict (persisted body) or a model instance."""
    if isinstance(cap, dict):
        return cap.get(name, default)
    return getattr(cap, name, default)


def _content_hash(cap: "dict[str, Any] | Any") -> str:
    """A stable content fingerprint. The store persists `content_hash`; models expose it if wrapped.
    Absent → "" (two versionless entries then only clash if truly identical, which is harmless)."""
    return str(_field(cap, "content_hash", "") or "")


def check_semver(caps: "list[Any]") -> list[RegistryViolation]:
    """Every capability pins a real MAJOR.MINOR[.PATCH]. A bare `latest`/empty/garbage version fails
    here — this IS the "no `latest`" gate at the registry layer (Risk 8)."""
    out: list[RegistryViolation] = []
    for cap in caps:
        cid = str(_field(cap, "capability_id", "?"))
        ver = str(_field(cap, "version", "") or "")
        if not _SEMVER_RE.match(ver):
            out.append(RegistryViolation(BAD_SEMVER, cid, f"version {ver!r} is not a pinned SemVer"))
    return out


def check_canonical(caps: "list[Any]") -> list[RegistryViolation]:
    """One canonical concept (Risk 3): a `capability_id` is a single concept with a single owner/domain
    across all its versions, and no two entries share an (id, version) with DIFFERENT content."""
    out: list[RegistryViolation] = []
    by_id: dict[str, list[Any]] = {}
    for cap in caps:
        by_id.setdefault(str(_field(cap, "capability_id", "?")), []).append(cap)

    for cid, group in by_id.items():
        # Owner/domain must be consistent — a concept cannot be silently re-owned or re-homed.
        owners = {str(_field(c, "owner_role", "")) for c in group}
        domains = {str(_field(c, "domain", "")) for c in group}
        if len(owners) > 1:
            out.append(RegistryViolation(INCONSISTENT_OWNER, cid, f"conflicting owner_role: {sorted(owners)}"))
        if len(domains) > 1:
            out.append(RegistryViolation(INCONSISTENT_OWNER, cid, f"conflicting domain: {sorted(domains)}"))
        # No two entries at the same version with different content — that's a fork masquerading as one.
        seen: dict[str, str] = {}
        for c in group:
            ver = str(_field(c, "version", ""))
            h = _content_hash(c)
            if ver in seen and seen[ver] and h and seen[ver] != h:
                out.append(RegistryViolation(
                    DUPLICATE_CONCEPT, cid, f"two different bodies registered at version {ver}"
                ))
            else:
                seen.setdefault(ver, h)
    return out


def build_dependency_edges(caps: "list[Any]") -> dict[str, set[str]]:
    """Directed edges cap → {caps it depends on}, drawn from `requires` and `enables` but ONLY where the
    referenced identifier is itself a known capability id (requires may also name state refs, which are
    not nodes in the capability DAG). Edges are deduped across versions of the same id."""
    known = {str(_field(c, "capability_id", "")) for c in caps}
    edges: dict[str, set[str]] = {cid: set() for cid in known if cid}
    for cap in caps:
        cid = str(_field(cap, "capability_id", ""))
        if not cid:
            continue
        for ref in (*(_field(cap, "requires", ()) or ()), *(_field(cap, "enables", ()) or ())):
            ref = str(ref)
            if ref in known and ref != cid:  # ignore state refs + self-loops-by-name
                edges[cid].add(ref)
    return edges


def find_dependency_cycle(edges: dict[str, set[str]]) -> list[str] | None:
    """The first dependency cycle as a node path (e.g. [A, B, A]), or None if the graph is acyclic.
    DFS with a colour map + a path stack — the standard cycle witness, no external deps."""
    color: dict[str, int] = {n: 0 for n in edges}  # 0 WHITE · 1 GREY · 2 BLACK
    for node in edges:
        if color[node] == 0:
            cycle = _dfs(node, edges, color, [], set())
            if cycle:
                return cycle
    return None


def _dfs(node: str, edges: dict[str, set[str]], color: dict[str, int],
         path: list[str], on_path: set[str]) -> list[str] | None:
    color[node] = 1  # GREY
    path.append(node)
    on_path.add(node)
    for nxt in sorted(edges.get(node, ())):
        if nxt in on_path:
            # Back-edge → cycle. Return the slice from the first occurrence + the closing node.
            i = path.index(nxt)
            return [*path[i:], nxt]
        if color.get(nxt, 0) == 0:  # WHITE
            found = _dfs(nxt, edges, color, path, on_path)
            if found:
                return found
    color[node] = 2  # BLACK
    path.pop()
    on_path.discard(node)
    return None


def check_dag(caps: "list[Any]") -> list[RegistryViolation]:
    """The dependency graph must be acyclic (Risk 5 — no capability depends on itself transitively)."""
    cycle = find_dependency_cycle(build_dependency_edges(caps))
    if cycle:
        return [RegistryViolation(DEPENDENCY_CYCLE, cycle[0], " → ".join(cycle))]
    return []


def validate_registry(caps: "list[Any]") -> list[RegistryViolation]:
    """All registry-level invariants, aggregated. Empty list ⇒ the set is a well-formed registry.
    The registration endpoint calls this with the existing set plus the candidate and rejects if any
    violation names the candidate (Encaps D7 hard gate)."""
    return [*check_semver(caps), *check_canonical(caps), *check_dag(caps)]
