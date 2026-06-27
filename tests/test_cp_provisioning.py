"""Control-plane tenant onboarding: one-call provision (encrypted secrets + adapter) + secret read."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from nilscript.secrets import SecretVault

TOKEN = "reg-tok"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NIL_VAULT_KEY", SecretVault.generate_key())
    from nilscript.controlplane.app import create_app
    from nilscript.controlplane.store import EventStore

    store = EventStore(str(tmp_path / "cp.db"))
    app = create_app(store, registry_token=TOKEN)
    return TestClient(app, raise_server_exceptions=False), store


_AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _provision(c, ws, **body):
    return c.post("/tenants/provision", json={"workspace": ws, **body}, headers=_AUTH)


def test_one_call_provision_stores_secrets_and_activates_adapter(client) -> None:
    c, store = client
    r = _provision(
        c, "ws_acme",
        secrets={"adapter_bearer": "sek", "llm_api_key": "sk-acme"},
        adapter={"adapter_id": "odoo", "url": "https://acme.odoo", "system": "odoo_crm"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and "llm_api_key" in body["provisioned"]["secrets"]
    assert "odoo" in body["provisioned"]["adapter"]
    active = store.active_adapter("ws_acme")
    assert active and active["adapter_id"] == "odoo"


def test_secret_read_is_token_gated_and_returns_value(client) -> None:
    c, _ = client
    _provision(c, "ws_acme", secrets={"llm_api_key": "sk-acme"})
    assert c.get("/tenants/ws_acme/secret/llm_api_key").status_code == 401  # no token
    r = c.get("/tenants/ws_acme/secret/llm_api_key", headers=_AUTH)
    assert r.status_code == 200 and r.json()["value"] == "sk-acme"


def test_secrets_are_encrypted_at_rest(client) -> None:
    c, store = client
    _provision(c, "ws_acme", secrets={"llm_api_key": "sk-PLAINTEXT-LEAK"})
    row = store._conn.execute(
        "SELECT ciphertext FROM tenant_secrets WHERE workspace='ws_acme'"
    ).fetchone()
    assert b"sk-PLAINTEXT-LEAK" not in row["ciphertext"]  # ciphertext on disk, not the key


def test_tenants_are_isolated(client) -> None:
    c, store = client
    _provision(c, "ws_a", secrets={"llm_api_key": "key-A"})
    _provision(c, "ws_b", secrets={"llm_api_key": "key-B"})
    assert store.get_secret("ws_a", "llm_api_key") == "key-A"
    assert store.get_secret("ws_b", "llm_api_key") == "key-B"
    assert store.get_secrets("ws_ghost") is None


def test_provision_requires_auth_and_workspace(client) -> None:
    c, _ = client
    assert c.post("/tenants/provision", json={"workspace": "x"}).status_code == 401
    assert c.post("/tenants/provision", json={}, headers=_AUTH).status_code == 400
