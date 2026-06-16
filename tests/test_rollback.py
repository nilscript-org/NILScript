"""ROLLBACK / Saga-compensation upgrade: wire conformance + model invariants + profile tiers.

The seventh performative is the lifecycle-closing primitive. These tests prove it lands
additively on the 0.1 wire dialect: a ROLLBACK envelope validates, an EVENT may carry a
compensation handle, an irreversible reversal is refused honestly, and the SDK models
enforce the Saga invariants (token iff reversible, idempotent replay).
"""

import json
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

import jsonschema
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from nilscript.sdk.refusals import RefusalCode
from nilscript.sdk.sentences import (
    Claim,
    Compensation,
    EventBody,
    EventKind,
    NilModel,
    Performative,
    ProposalBody,
    ResultEnvelope,
    Reversibility,
    RollbackBody,
    RollbackReason,
    Severity,
    make_envelope,
)

TS = datetime(2026, 6, 16, 7, 0, 0, tzinfo=UTC)
SENTENCE_ID = "a" * 16
TOKEN = "ctok-" + "9" * 16


def load_schema(name: str) -> dict[str, Any]:
    schema_file = files("nilscript.sdk") / "spec" / "0.1" / f"{name}.schema.json"
    return json.loads(schema_file.read_text(encoding="utf-8"))


def load_profile(domain: str, action: str) -> dict[str, Any]:
    profile = files("nilscript.sdk") / "spec" / "0.1" / "profiles" / domain / f"{action}.json"
    return json.loads(profile.read_text(encoding="utf-8"))


def assert_valid(instance: dict[str, Any], schema_name: str) -> None:
    jsonschema.validate(
        instance, load_schema(schema_name), format_checker=Draft202012Validator.FORMAT_CHECKER
    )


def wire(performative: Performative, body: NilModel) -> dict[str, Any]:
    return make_envelope(
        performative, body, sentence_id=SENTENCE_ID, grant="grant-001", workspace="ws-001", ts=TS
    ).to_wire()


# ── wire conformance ────────────────────────────────────────────────────────


def test_rollback_envelope_and_body_conform() -> None:
    body = RollbackBody(compensation_token=TOKEN, reason=RollbackReason.SAGA_UNWIND)
    env = wire(Performative.ROLLBACK, body)
    assert_valid(env, "envelope")
    assert_valid(env["body"], "rollback")
    assert env["performative"] == "ROLLBACK"


def test_rollback_carries_optional_idempotency_key() -> None:
    body = RollbackBody(
        compensation_token=TOKEN, reason=RollbackReason.OWNER_CANCEL, idempotency_key="k" * 16
    )
    assert_valid(wire(Performative.ROLLBACK, body)["body"], "rollback")


def test_event_result_may_carry_compensation_handle() -> None:
    """A COMMIT's EVENT tells the agent how the effect can later be reversed."""
    event = EventBody(
        event=EventKind.EXECUTED,
        severity=Severity.INFO,
        proposal="prop-0001",
        result=ResultEnvelope(
            claim=Claim.SUCCESS,
            changed=True,
            verified=True,
            compensation=Compensation(
                reversibility=Reversibility.REVERSIBLE, token=TOKEN, expires_at=TS
            ),
        ),
    )
    assert_valid(wire(Performative.EVENT, event)["body"], "event")


def test_compensated_event_kind_conforms() -> None:
    event = EventBody(
        event=EventKind.COMPENSATED,
        severity=Severity.INFO,
        proposal="prop-0001",
        result=ResultEnvelope(claim=Claim.SUCCESS, changed=True, verified=True),
    )
    assert_valid(wire(Performative.EVENT, event)["body"], "event")


def test_irreversible_reversal_is_refused_honestly() -> None:
    """ROLLBACK of an irreversible effect is answered by a refusal, never a silent write."""
    refusal = ProposalBody(
        outcome="refusal",
        code=RefusalCode.IRREVERSIBLE,
        message="commerce.send_message cannot be reversed",
    )
    assert_valid(wire(Performative.PROPOSAL, refusal)["body"], "proposal")


# ── model invariants ────────────────────────────────────────────────────────


def test_rollback_in_closed_performative_set() -> None:
    assert Performative.ROLLBACK in set(Performative)


def test_compensation_forbids_token_on_irreversible() -> None:
    with pytest.raises(ValidationError):
        Compensation(reversibility=Reversibility.IRREVERSIBLE, token=TOKEN)


def test_irreversible_compensation_without_token_is_valid() -> None:
    comp = Compensation(reversibility=Reversibility.IRREVERSIBLE)
    assert comp.token is None


def test_rollback_body_requires_token_and_reason() -> None:
    with pytest.raises(ValidationError):
        RollbackBody(reason=RollbackReason.SAGA_UNWIND)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        RollbackBody(compensation_token="short", reason=RollbackReason.SAGA_UNWIND)


def test_new_refusal_codes_exist() -> None:
    assert RefusalCode.IRREVERSIBLE and RefusalCode.COMPENSATION_EXPIRED


# ── profile reversibility tiers ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("domain", "action", "tier", "comp_verb"),
    [
        ("commerce-v1", "create_product", "REVERSIBLE", "commerce.delete_product"),
        ("commerce-v1", "record_payment", "COMPENSABLE", "commerce.process_refund"),
        ("commerce-v1", "send_message", "IRREVERSIBLE", None),
    ],
)
def test_profile_declares_reversibility(
    domain: str, action: str, tier: str, comp_verb: str | None
) -> None:
    profile = load_profile(domain, action)
    assert profile["reversibility"] == tier
    if comp_verb is None:
        assert "compensation" not in profile
    else:
        assert profile["compensation"]["verb"] == comp_verb
