"""Per-tenant encrypted secret storage for SaaS multi-tenancy."""

from nilscript.secrets.vault import SecretVault, VaultError

__all__ = ["SecretVault", "VaultError"]
