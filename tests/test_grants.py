"""Grant refs: hashed-at-rest secrets, default-deny scope matching."""

import hashlib

from nilscript.sdk.grants import GrantRef, scope_allows


def test_secret_is_hashed_and_never_in_repr() -> None:
    grant = GrantRef.from_secret(
        grant_id="grant-001",
        workspace="ws-001",
        secret="raw-bearer-secret",
        scopes=frozenset({"services.create_invoice"}),
    )
    assert grant.token_digest == hashlib.sha256(b"raw-bearer-secret").hexdigest()
    assert "raw-bearer-secret" not in repr(grant)
    assert grant.bearer_secret() == "raw-bearer-secret"


def test_scope_allows_exact_match_only_by_default() -> None:
    scopes = frozenset({"services.create_invoice"})
    assert scope_allows(scopes, "services.create_invoice")
    assert not scope_allows(scopes, "services.send_followup")
    assert not scope_allows(frozenset(), "services.create_invoice")


def test_scope_allows_profile_wildcard() -> None:
    scopes = frozenset({"services.*"})
    assert scope_allows(scopes, "services.create_invoice")
    assert not scope_allows(scopes, "commerce.create_product")


def test_round_tripped_grant_fails_loudly_instead_of_silently() -> None:
    import pytest

    original = GrantRef.from_secret(
        grant_id="grant-001", workspace="ws-001", secret="s", scopes=frozenset()
    )
    rehydrated = GrantRef.model_validate(original.model_dump())
    with pytest.raises(RuntimeError, match="from_secret"):
        rehydrated.bearer_secret()
