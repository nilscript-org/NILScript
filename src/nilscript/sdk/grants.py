"""Agent-plane grant references. Secrets are hashed at rest; raw value lives only in memory."""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, PrivateAttr


class GrantRef(BaseModel):
    """One agent-plane grant per workspace (02-NIL-CLIENT). Never an owner-plane credential."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    grant_id: str
    workspace: str
    token_digest: str
    scopes: frozenset[str]

    _secret: str = PrivateAttr(default="")

    @classmethod
    def from_secret(
        cls, *, grant_id: str, workspace: str, secret: str, scopes: frozenset[str]
    ) -> GrantRef:
        grant = cls(
            grant_id=grant_id,
            workspace=workspace,
            token_digest=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            scopes=scopes,
        )
        grant._secret = secret
        return grant

    def bearer_secret(self) -> str:
        """The raw secret for transport auth — intentionally a method, never a dumped field."""
        if not self._secret:
            raise RuntimeError(
                "GrantRef carries no secret — construct via GrantRef.from_secret(); "
                "round-tripping through model_dump/model_validate drops the secret by design"
            )
        return self._secret


def scope_allows(scopes: frozenset[str], verb: str) -> bool:
    """Default-deny scope check: exact verb or a `profile.*` wildcard."""
    if verb in scopes:
        return True
    profile, _, _ = verb.partition(".")
    return f"{profile}.*" in scopes
