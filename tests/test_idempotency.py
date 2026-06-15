"""The NIL idempotency protocol: deterministic, replay-safe tokens (02-NIL-CLIENT)."""

import string

from nilscript.sdk.idempotency import batch_tokens, nil_uuid

SESSION = "conv-7f3a"
TS = "2026-06-12T07:00:00Z"


def test_same_inputs_yield_same_token() -> None:
    assert nil_uuid(SESSION, TS, 0) == nil_uuid(SESSION, TS, 0)


def test_token_varies_by_each_component() -> None:
    base = nil_uuid(SESSION, TS, 0)
    assert nil_uuid("conv-other", TS, 0) != base
    assert nil_uuid(SESSION, "2026-06-12T07:00:01Z", 0) != base
    assert nil_uuid(SESSION, TS, 1) != base


def test_token_is_hex_and_long_enough_for_envelope_id() -> None:
    token = nil_uuid(SESSION, TS, 0)
    assert len(token) == 64  # sha256 hex; envelope id requires >= 8
    assert set(token) <= set(string.hexdigits.lower())


def test_batch_tokens_are_ordered_and_distinct() -> None:
    tokens = batch_tokens(SESSION, TS, 3)
    assert tokens == (nil_uuid(SESSION, TS, 0), nil_uuid(SESSION, TS, 1), nil_uuid(SESSION, TS, 2))
    assert len(set(tokens)) == 3
