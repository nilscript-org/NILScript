"""Registry-level invariants (Wave 4 §14.2) as executable gates (Master Plan E1). Capabilities are
given as plain bodies — the shape the store persists — so these tests double as the contract the
registration endpoint enforces: one canonical concept, pinned SemVer, an acyclic dependency DAG.
"""

from __future__ import annotations

from nilscript.capability.registry import (
    BAD_SEMVER,
    DEPENDENCY_CYCLE,
    DUPLICATE_CONCEPT,
    INCONSISTENT_OWNER,
    build_dependency_edges,
    check_canonical,
    check_dag,
    check_semver,
    find_dependency_cycle,
    validate_registry,
)


def cap(cid, *, version="1.0", domain="Procurement", owner="Ops", requires=(), enables=(), content_hash="h"):
    return {
        "capability_id": cid,
        "version": version,
        "domain": domain,
        "owner_role": owner,
        "requires": tuple(requires),
        "enables": tuple(enables),
        "content_hash": content_hash,
    }


# ── SemVer / no `latest` ────────────────────────────────────────────────────────────────────────────
def test_pinned_semver_passes() -> None:
    assert check_semver([cap("Communication", version="2.3"), cap("Inventory", version="1.0.1")]) == []


def test_latest_is_rejected_as_bad_semver() -> None:
    v = check_semver([cap("Communication", version="latest")])
    assert [x.code for x in v] == [BAD_SEMVER]
    assert v[0].capability_id == "Communication"


def test_empty_or_garbage_version_rejected() -> None:
    assert {x.code for x in check_semver([cap("A", version=""), cap("B", version="v2")])} == {BAD_SEMVER}


# ── One canonical concept ───────────────────────────────────────────────────────────────────────────
def test_multiple_versions_of_one_concept_are_fine() -> None:
    caps = [cap("Communication", version="1.0"), cap("Communication", version="2.0")]
    assert check_canonical(caps) == []


def test_concept_cannot_be_re_owned_across_versions() -> None:
    caps = [cap("Communication", version="1.0", owner="Ops"), cap("Communication", version="2.0", owner="Finance")]
    codes = [x.code for x in check_canonical(caps)]
    assert INCONSISTENT_OWNER in codes


def test_same_version_different_content_is_a_fork() -> None:
    caps = [cap("Communication", version="2.0", content_hash="aaa"),
            cap("Communication", version="2.0", content_hash="bbb")]
    assert [x.code for x in check_canonical(caps)] == [DUPLICATE_CONCEPT]


def test_same_version_same_content_is_idempotent_not_a_fork() -> None:
    caps = [cap("Communication", version="2.0", content_hash="aaa"),
            cap("Communication", version="2.0", content_hash="aaa")]
    assert check_canonical(caps) == []


# ── Dependency DAG ──────────────────────────────────────────────────────────────────────────────────
def test_edges_only_link_known_capabilities_not_state_refs() -> None:
    caps = [cap("PurchaseOrder", requires=("Inventory", "budget_state")), cap("Inventory")]
    edges = build_dependency_edges(caps)
    assert edges["PurchaseOrder"] == {"Inventory"}  # budget_state is not a capability node
    assert edges["Inventory"] == set()


def test_acyclic_registry_passes() -> None:
    caps = [cap("PurchaseOrder", requires=("Inventory",)), cap("Inventory", enables=("Reporting",)), cap("Reporting")]
    assert check_dag(caps) == []
    assert find_dependency_cycle(build_dependency_edges(caps)) is None


def test_dependency_cycle_is_caught_with_a_witness_path() -> None:
    caps = [cap("A", requires=("B",)), cap("B", requires=("C",)), cap("C", requires=("A",))]
    v = check_dag(caps)
    assert [x.code for x in v] == [DEPENDENCY_CYCLE]
    # The witness is a closed loop (first node repeats at the end) naming every node in the cycle.
    nodes = [n.strip() for n in v[0].detail.split("→")]
    assert nodes[0] == nodes[-1]  # closes on itself
    assert set(nodes) == {"A", "B", "C"}


def test_self_dependency_by_enables_does_not_crash_and_is_clean() -> None:
    # Self-name edges are dropped, so a bare self-enable is not a cycle and must not crash.
    assert check_dag([cap("A", enables=("A",))]) == []


# ── Aggregate gate ──────────────────────────────────────────────────────────────────────────────────
def test_validate_registry_aggregates_all_violations() -> None:
    caps = [
        cap("A", version="latest", requires=("B",)),  # bad semver + part of a cycle
        cap("B", requires=("A",)),
    ]
    codes = {x.code for x in validate_registry(caps)}
    assert BAD_SEMVER in codes and DEPENDENCY_CYCLE in codes


def test_clean_registry_has_no_violations() -> None:
    caps = [cap("PurchaseOrder", requires=("Inventory",)), cap("Inventory"), cap("Communication", version="2.1")]
    assert validate_registry(caps) == []
