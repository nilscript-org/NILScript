"""The discovery handshake carries DECLARED per-verb governance metadata.

`/nil/v0.1/describe` → `verb_details[]` is the adapter's own authority statement
(type / tier / reversibility / required_args / references). Consumers must use it
instead of guessing tier or type from verb names; an adapter that declares nothing
yields [] and its verbs are metadata-unknown (fail closed downstream).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from nilscript.demo.pocketbase_nil_adapter.compensation import COMPENSATIONS
from nilscript.demo.pocketbase_nil_adapter.edge import CapturingEmitter, create_app
from nilscript.demo.pocketbase_nil_adapter.system import FakeSystem
from nilscript.demo.pocketbase_nil_adapter.translate import QUERY_VERBS, WRITE_VERBS


def _describe() -> dict:
    app = create_app(FakeSystem(), CapturingEmitter(), bearer="test-token")
    client = TestClient(app)
    r = client.get("/nil/v0.1/describe")
    assert r.status_code == 200
    return r.json()


def test_every_advertised_verb_has_declared_details() -> None:
    d = _describe()
    details = {v["verb"]: v for v in d["verb_details"]}
    assert set(d["verbs"]) == set(details), "verbs and verb_details must cover the same set"


def test_write_verbs_declare_authority_fields_from_their_tables() -> None:
    d = _describe()
    details = {v["verb"]: v for v in d["verb_details"]}
    for name, verb in WRITE_VERBS.items():
        got = details[name]
        assert got["type"] == "write"
        assert got["tier"] == verb.tier
        assert got["required_args"] == list(verb.required)
        expected_rev = (COMPENSATIONS.get(name) or {}).get("reversibility", "IRREVERSIBLE")
        assert got["reversibility"] == expected_rev, (
            f"{name}: reversibility must come from COMPENSATIONS (omission = IRREVERSIBLE)"
        )


def test_query_verbs_declare_low_read() -> None:
    d = _describe()
    details = {v["verb"]: v for v in d["verb_details"]}
    for name in QUERY_VERBS:
        assert details[name]["type"] == "query"
        assert details[name]["tier"] == "LOW"


def test_handshake_passes_verb_details_through() -> None:
    import asyncio

    from nilscript.sdk.connect import handshake

    described = _describe()

    class _Transport:
        async def get(self, path: str) -> dict:
            assert "describe" in path
            return described

    report = asyncio.run(handshake(_Transport()))
    assert report["conformant"] is True
    assert report["verb_details"], "handshake must pass declared metadata through"
    assert {v["verb"] for v in report["verb_details"]} == set(report["verbs"])
