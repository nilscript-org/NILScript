"""Contract tests: every sentence we serialize validates against the vendored nilscript schemas."""

import json
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

import jsonschema
import pytest
from jsonschema import Draft202012Validator
from nilscript.sdk.refusals import RefusalCode
from nilscript.sdk.sentences import (
    Candidate,
    Claim,
    CommitBody,
    EventBody,
    EventKind,
    NilModel,
    Performative,
    ProposalBody,
    ProposeBody,
    QueryBody,
    ResultEnvelope,
    Severity,
    StatusBody,
    Tier,
    make_envelope,
)

TS = datetime(2026, 6, 12, 7, 0, 0, tzinfo=UTC)
SENTENCE_ID = "a" * 16


def load_schema(name: str) -> dict[str, Any]:
    schema_file = files("nilscript.sdk") / "spec" / "0.1" / f"{name}.schema.json"
    return json.loads(schema_file.read_text(encoding="utf-8"))


def assert_valid(instance: dict[str, Any], schema_name: str) -> None:
    jsonschema.validate(
        instance, load_schema(schema_name), format_checker=Draft202012Validator.FORMAT_CHECKER
    )


def wire_envelope(performative: Performative, body: NilModel) -> dict[str, Any]:
    envelope = make_envelope(
        performative,
        body,
        sentence_id=SENTENCE_ID,
        grant="grant-001",
        workspace="ws-001",
        ts=TS,
        trace="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
    )
    return envelope.to_wire()


PROPOSE = ProposeBody(verb="services.create_invoice", args={"party_id": "p1", "amount": 500})
COMMIT = CommitBody(proposal="prop-0001", idempotency_key="b" * 64)
QUERY = QueryBody(verb="services.list_clients", args={"limit": 5})
STATUS = StatusBody(proposal="prop-0001")

PROPOSAL_OK = ProposalBody(
    outcome="proposal",
    id="prop-0001",
    verb="services.create_invoice",
    tier=Tier.HIGH,
    preview={"ar": "فاتورة بمبلغ ٥٠٠٫٠٠ ر.س. للعميل أحمد", "en": "Invoice of SAR 500.00 for Ahmed"},
    resolved={"party_id": "p1", "amount": 500.0, "currency": "SAR"},
    modifiable=("amount",),
    expires_at=TS,
)
REFUSAL_PLAIN = ProposalBody(
    outcome="refusal", code=RefusalCode.BUDGET_EXHAUSTED, message="monthly budget exhausted"
)
REFUSAL_AMBIGUOUS = ProposalBody(
    outcome="refusal",
    code=RefusalCode.AMBIGUOUS,
    field="party_id",
    candidates=(
        Candidate(id="c1", name="أحمد الغامدي", source="records"),
        Candidate(id="c2", name="أحمد العتيبي", source="records"),
    ),
)
EVENT_EXECUTED = EventBody(
    event=EventKind.EXECUTED,
    severity=Severity.INFO,
    proposal="prop-0001",
    result=ResultEnvelope(
        claim=Claim.SUCCESS,
        changed=True,
        verified=True,
        data={"invoice_id": "inv-9"},
    ),
)


@pytest.mark.parametrize(
    ("performative", "body", "body_schema"),
    [
        (Performative.PROPOSE, PROPOSE, "propose"),
        (Performative.COMMIT, COMMIT, "commit"),
        (Performative.QUERY, QUERY, "query"),
        (Performative.STATUS, STATUS, "status"),
        (Performative.PROPOSAL, PROPOSAL_OK, "proposal"),
        (Performative.PROPOSAL, REFUSAL_PLAIN, "proposal"),
        (Performative.PROPOSAL, REFUSAL_AMBIGUOUS, "proposal"),
        (Performative.EVENT, EVENT_EXECUTED, "event"),
    ],
)
def test_sentence_conforms_to_spec(
    performative: Performative, body: NilModel, body_schema: str
) -> None:
    wire = wire_envelope(performative, body)
    assert_valid(wire, "envelope")
    assert_valid(wire["body"], body_schema)


def test_trace_is_omitted_when_absent() -> None:
    envelope = make_envelope(
        Performative.QUERY,
        QUERY,
        sentence_id=SENTENCE_ID,
        grant="grant-001",
        workspace="ws-001",
        ts=TS,
    )
    wire = envelope.to_wire()
    assert "trace" not in wire
    assert_valid(wire, "envelope")
