"""Env-based wiring shared by every deployable (worker, gateway).

Per-workspace credentials come from the secret store via env — never from code.
"""

import os
from collections.abc import Mapping

from nilscript.sdk.breaker import CircuitBreaker
from nilscript.sdk.client import NilClient
from nilscript.sdk.grants import GrantRef
from nilscript.sdk.transport import NilTransport


def grant_from_env(source: Mapping[str, str]) -> GrantRef:
    try:
        scopes_raw = source.get("NIL_GRANT_SCOPES", "")
        return GrantRef.from_secret(
            grant_id=source["NIL_GRANT_ID"],
            workspace=source["NIL_WORKSPACE"],
            secret=source["NIL_GRANT_SECRET"],
            scopes=frozenset(scopes_raw.split(",")) if scopes_raw else frozenset(),
        )
    except KeyError as exc:
        raise RuntimeError(f"missing required environment variable: {exc}") from exc


def require_https(base_url: str, source: Mapping[str, str]) -> str:
    """Reject a cleartext NIL base URL: the bearer token rides every request, so http://
    would leak the credential. Applies to env-sourced AND directory/DB-sourced base URLs.
    The NIL_ALLOW_INSECURE=1 escape hatch is for local development only."""
    if not base_url.startswith("https://") and source.get("NIL_ALLOW_INSECURE") != "1":
        raise RuntimeError(
            "NIL base URL must be https:// (bearer token would travel cleartext); "
            "set NIL_ALLOW_INSECURE=1 only for local development"
        )
    return base_url


def base_url_from_env(source: Mapping[str, str]) -> str:
    try:
        base_url = source["NIL_BASE_URL"]
    except KeyError as exc:
        raise RuntimeError(f"missing required environment variable: {exc}") from exc
    return require_https(base_url, source)


def client_for_grant(grant: GrantRef, source: Mapping[str, str]) -> NilClient:
    transport = NilTransport(
        base_url=base_url_from_env(source),
        bearer_secret=grant.bearer_secret(),
        breaker=CircuitBreaker(),
    )
    return NilClient(transport=transport, grant=grant)


def client_from_env(env: Mapping[str, str] | None = None) -> NilClient:
    source = env if env is not None else dict(os.environ)
    return client_for_grant(grant_from_env(source), source)
