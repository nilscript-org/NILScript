"""Phase 6 tests: registry currency (manifest merge/diff) + self-evolving memory guardrails (§5.4, §6)."""

from __future__ import annotations

from pathlib import Path

from nilscript.cli.manifest import diff, merge, shareable_violations
from nilscript.cli.memory import MemoryStore, propose_manifest_patch


def _structural() -> dict:
    return {
        "manifest_version": "0.1",
        "system": "erpnext",
        "nil_spec": "0.1",
        "verbs": {
            "services.create_invoice": {
                "hidden_requirements": [{"field": "company", "kind": "required_scalar"}]
            }
        },
    }


def _local_override() -> dict:
    return {
        "verbs": {
            "services.create_invoice": {
                "line_container": "items",
                "instance_values": {"company": "${ERPNEXT_COMPANY}"},
            }
        }
    }


def test_merge_layers_local_instances_onto_community_structure() -> None:
    merged = merge(_structural(), _local_override())
    verb = merged["verbs"]["services.create_invoice"]
    # structural requirement survives, local binding is layered on
    assert verb["hidden_requirements"] == [{"field": "company", "kind": "required_scalar"}]
    assert verb["instance_values"] == {"company": "${ERPNEXT_COMPANY}"}
    assert verb["line_container"] == "items"
    # the merged result still uses an ${ENV} placeholder, so it remains shareable-clean structurally
    assert shareable_violations(merged) == []


def test_merge_unions_requirements_without_duplicates() -> None:
    extra = {"verbs": {"services.create_invoice": {"hidden_requirements": [
        {"field": "company", "kind": "required_scalar"},  # dup — must not double
        {"field": "income_account", "kind": "required_on_line"},
    ]}}}
    merged = merge(_structural(), extra)
    reqs = merged["verbs"]["services.create_invoice"]["hidden_requirements"]
    assert sum(1 for r in reqs if r["field"] == "company") == 1
    assert any(r["field"] == "income_account" for r in reqs)


def test_diff_detects_drift_when_a_system_adds_a_requirement() -> None:
    old = _structural()
    new = merge(_structural(), {"verbs": {"services.create_invoice": {"hidden_requirements": [
        {"field": "cost_center", "kind": "required_on_line"}
    ]}}})
    report = diff(old, new)
    assert report["changed"] is True
    assert "cost_center:required_on_line" in report["verbs_changed"]["services.create_invoice"]["requirements_added"]


def test_diff_is_empty_for_identical_manifests() -> None:
    report = diff(_structural(), _structural())
    assert report["changed"] is False


def test_memory_is_append_only_and_auditable(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.jsonl")
    first = store.add_skill("invoice-with-autocreate", [{"verb": "services.create_client"}])
    # a revision SUPERSEDES the first — history is preserved, active view shows the latest only.
    second = store.add_skill(
        "invoice-with-autocreate",
        [{"verb": "services.create_client"}, {"verb": "services.create_invoice"}],
        supersedes=first["id"],
    )
    assert len(store.history("skill")) == 2  # nothing destroyed (no catastrophic forgetting)
    active = store.active("skill")
    assert len(active) == 1 and active[0]["id"] == second["id"]


def test_lesson_feeds_back_into_manifest_only_as_a_proposal() -> None:
    lesson = {"payload": {"verb": "services.create_invoice",
                          "learned_requirement": {"field": "cost_center", "kind": "required_on_line"}}}
    patch = propose_manifest_patch(lesson)
    assert patch is not None
    # it is a fragment to be REVIEWED + merged, not an applied manifest
    assert patch["verbs"]["services.create_invoice"]["hidden_requirements"][0]["field"] == "cost_center"
    # a non-structural lesson proposes nothing (no silent guesses)
    assert propose_manifest_patch({"payload": {"text": "just a note"}}) is None
