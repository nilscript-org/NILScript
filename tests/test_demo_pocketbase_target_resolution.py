"""Focused proof for the universal entity-noun read resolution in the vendored demo PocketBase
adapter: a generic noun (client/customer) resolves to the declared collection, and a `name` search
matches the display-name field. Kept byte-identical (in the resolver logic) with the standalone
pocketbase-nil-adapter."""

from __future__ import annotations

from fastapi.testclient import TestClient

from nilscript.demo.pocketbase_nil_adapter.edge import (
    CapturingEmitter,
    _apply_match,
    _resolve_target,
    create_app,
)
from nilscript.demo.pocketbase_nil_adapter.system import FakeSystem
from nilscript.demo.pocketbase_nil_adapter.translate import WRITE_VERBS

_DECLARED = sorted({v.doctype for v in WRITE_VERBS.values()})


def _env(verb: str, args: dict) -> dict:
    return {"nil": "0.1", "grant": "g", "workspace": "w", "body": {"verb": verb, "args": args}}


def test_generic_noun_resolves_to_declared_target() -> None:
    resolved = _resolve_target("client")
    assert resolved in _DECLARED
    assert resolved == _resolve_target("customer"), "synonyms resolve to the same declared target"


def test_exact_declared_target_passes_through() -> None:
    for d in _DECLARED:
        assert _resolve_target(d) == d


def test_name_search_matches_display_name_field() -> None:
    rows = [{"first_name": "Acme"}, {"first_name": "Beta"}]
    hits = _apply_match(rows, {"name": "acme"})
    assert hits == [{"first_name": "Acme"}], "a `name` filter also matches first_name"


def test_aliased_noun_create_commits_into_real_collection_not_raw_noun() -> None:
    """The bug this guards: resolution happened at PROPOSE but the COMMIT path reads the STORED
    target. If the stored target were the raw noun ('client'), the commit would write to a phantom
    collection 'client' and the real declared collection ('clients') would stay empty. Assert the
    record lands in the resolved declared collection and NOT under the raw noun."""
    real = _resolve_target("client")
    assert real != "client" and real in _DECLARED, "precondition: 'client' resolves to a declared collection"

    system = FakeSystem()
    client = TestClient(create_app(system, CapturingEmitter(), bearer=None), raise_server_exceptions=False)

    proposed = client.post("/nil/v0.1/propose", json=_env(
        "resource.create", {"target": "client", "name": "Acme", "phone": "0500000000"})).json()["body"]
    assert proposed["outcome"] == "proposal", f"aliased-noun create must propose: {proposed}"
    assert proposed["resolved"]["target"] == real, "PROPOSE preview already shows the resolved collection"

    pid = proposed["id"]
    committed = client.post("/nil/v0.1/commit", json={"nil": "0.1", "grant": "g", "workspace": "w",
        "body": {"proposal": pid, "idempotency_key": pid}}).json()["body"]
    assert committed["state"] == "executed", f"aliased-noun create must commit: {committed}"

    assert system.docs.get(real), f"the record must land in the real collection '{real}'"
    assert "client" not in system.docs, "commit must NEVER write to the raw noun 'client' (phantom collection)"
