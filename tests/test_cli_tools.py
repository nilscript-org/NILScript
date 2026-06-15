"""Gate-A tests for the nilscript adapter-tooling CLI: verbs / profile / export-openapi.

These exercise the tools, not any adapter — they assert the tools read the standard correctly,
flag deprecated verbs from the single machine-readable source, and emit a structurally valid
API surface.
"""

from __future__ import annotations

from nilscript.cli import main
from nilscript.cli._openapi import build_openapi
from nilscript.cli._spec import active_verbs, all_verbs, find_verb, load_profile


def test_verbs_catalog_includes_known_verbs() -> None:
    names = {v.name for v in all_verbs()}
    assert "commerce.create_product" in names
    assert "services.create_invoice" in names
    # 0.2 verbs are present in the bundled spec
    assert "commerce.record_payment" in names


def test_profile_returns_arg_schema_for_known_verb() -> None:
    profile = load_profile("commerce.create_product")
    assert profile is not None
    assert profile["type"] == "object"
    assert "name" in profile["required"]


def test_profile_unknown_verb_returns_none() -> None:
    assert load_profile("commerce.does_not_exist") is None


def test_tier_floor_parsed_from_profile_title() -> None:
    refund = find_verb("commerce.process_refund")
    assert refund is not None
    assert refund.tier_floor == "HIGH"


def test_deprecated_verb_flagged_from_single_source() -> None:
    # update_order_status carries `"deprecated": true` in its profile (GAP-001) — the tool reads
    # that flag directly, no hand-maintained list.
    parked = find_verb("commerce.update_order_status")
    assert parked is not None
    assert parked.deprecated is True
    assert parked.gap_ref == "GAP-001"


def test_active_verb_not_deprecated() -> None:
    active = find_verb("commerce.create_product")
    assert active is not None
    assert active.deprecated is False
    assert active.gap_ref is None


def test_active_verbs_exclude_deprecated() -> None:
    active = {v.name for v in active_verbs()}
    assert "commerce.update_order_status" not in active
    assert "commerce.record_payment" in active
    assert active_verbs()  # non-empty


def test_export_openapi_covers_the_five_endpoints() -> None:
    doc = build_openapi()
    assert doc["openapi"].startswith("3.1")
    paths = doc["paths"]
    assert "post" in paths["/nil/v0.1/propose"]
    assert "post" in paths["/nil/v0.1/commit"]
    assert "post" in paths["/nil/v0.1/query"]
    assert "get" in paths["/nil/v0.1/status/{proposal_id}"]
    assert "post" in paths["/webhooks/nil-events"]
    schemas = doc["components"]["schemas"]
    assert "ProposeBody" in schemas
    assert "Envelope" in schemas
    assert "$schema" not in schemas["Envelope"]


def test_verbs_output_marks_deprecated(capsys) -> None:
    rc = main(["verbs"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "DEPRECATED" in out
    assert "GAP-001" in out


def test_main_export_openapi_smoke(capsys) -> None:
    rc = main(["export-openapi"])
    assert rc == 0
    assert '"openapi"' in capsys.readouterr().out
