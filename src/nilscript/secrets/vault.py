"""Per-tenant encrypted secret vault — the place a company's adapter creds + LLM key are saved ONCE.

SaaS multi-tenancy needs each tenant's secrets (Odoo/Daftra creds, LLM API key) stored encrypted at
rest and readable only as that tenant. This module is the keystone:

  • Secrets are encrypted with a master key (Fernet / AES-128-CBC + HMAC) before they touch the store,
    so a leaked store row is ciphertext, not credentials.
  • Access is BY TENANT: `get(tenant)` only ever returns that tenant's blob — no cross-tenant read.
  • The backing `store` is an injectable MutableMapping (a dict in tests, a DB/Redis/file in prod), so
    the crypto + isolation logic is storage-agnostic and unit-testable with no infrastructure.

The vault never logs or returns secrets except to the caller that asked for its own tenant; the master
key comes from the environment / a KMS, never from code.
"""

from __future__ import annotations

import json
import os
from collections.abc import MutableMapping
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class VaultError(RuntimeError):
    """The vault could not store/read a secret (missing master key, corrupt/forged ciphertext)."""


class SecretVault:
    """Encrypt-at-rest per-tenant secrets. One process holds the master key; the store holds only
    ciphertext keyed by tenant."""

    def __init__(self, key: str | bytes, store: MutableMapping[str, bytes] | None = None) -> None:
        try:
            self._fernet = Fernet(key if isinstance(key, bytes) else key.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise VaultError(f"invalid vault master key (expect a Fernet key): {exc}") from exc
        self._store: MutableMapping[str, bytes] = store if store is not None else {}

    @classmethod
    def from_env(cls, var: str = "NIL_VAULT_KEY",
                 store: MutableMapping[str, bytes] | None = None) -> SecretVault:
        key = os.environ.get(var)
        if not key:
            raise VaultError(f"{var} is not set — refusing to run the secret vault without a master key")
        return cls(key, store)

    @staticmethod
    def generate_key() -> str:
        """A fresh master key the operator stores in their secret manager (never committed)."""
        return Fernet.generate_key().decode("utf-8")

    def put(self, tenant: str, secrets: dict[str, Any]) -> None:
        """Save (replace) a tenant's secret bundle, encrypted. Called once at onboarding / when rotated."""
        if not tenant:
            raise VaultError("a tenant is required to store secrets")
        blob = self._fernet.encrypt(json.dumps(secrets, separators=(",", ":")).encode("utf-8"))
        self._store[tenant] = blob

    def get(self, tenant: str) -> dict[str, Any] | None:
        """Decrypt and return a tenant's secret bundle, or None if the tenant has none. Only ever the
        caller-named tenant's blob — isolation is enforced by the key, not by hoping the caller is honest."""
        blob = self._store.get(tenant)
        if blob is None:
            return None
        try:
            return json.loads(self._fernet.decrypt(blob).decode("utf-8"))
        except (InvalidToken, ValueError) as exc:  # forged / wrong-key / corrupt ciphertext
            raise VaultError(f"could not decrypt secrets for tenant '{tenant}' (wrong key or tampered)") from exc

    def get_secret(self, tenant: str, name: str) -> Any | None:
        """One named secret for a tenant (e.g. 'llm_api_key', 'adapter_bearer'), or None."""
        bundle = self.get(tenant)
        return bundle.get(name) if bundle else None

    def has(self, tenant: str) -> bool:
        return tenant in self._store

    def delete(self, tenant: str) -> None:
        """Off-board: drop a tenant's secrets entirely."""
        self._store.pop(tenant, None)
