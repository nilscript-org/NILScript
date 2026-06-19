"""NilClient: deterministic envelope ids, refusal-as-value, replay-safe wire payloads."""

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from nilscript.sdk.breaker import CircuitBreaker
from nilscript.sdk.client import NilClient
from nilscript.sdk.errors import NilProtocolError
from nilscript.sdk.grants import GrantRef
from nilscript.sdk.idempotency import batch_tokens
from nilscript.sdk.refusals import RefusalCode
from nilscript.sdk.sentences import ProposalBody, ProposeBody, StatusBody
from nilscript.sdk.transport import NilTransport

BASE = "https://os.example.sa"
TS = datetime(2026, 6, 12, 7, 0, 0, tzinfo=UTC)
SESSION = "conv-7f3a"

GRANT = GrantRef.from_secret(
    grant_id="grant-001",
    workspace="ws-001",
    secret="s3cret-token",
    scopes=frozenset({"services.*"}),
)


def server_envelope(performative: str, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "nil": "0.1",
        "id": "srv-sentence-0001",
        "performative": performative,
        "grant": "grant-001",
        "workspace": "ws-001",
        "ts": "2026-06-12T07:00:01Z",
        "body": body,
    }


PROPOSAL_OK_BODY = {
    "outcome": "proposal",
    "id": "prop-0001",
    "verb": "services.create_invoice",
    "tier": "HIGH",
    "preview": {"ar": "فاتورة بمبلغ 500.00 ر.س. للعميل أحمد"},
    "expires_at": "2026-06-13T07:00:00Z",
}

REFUSAL_BODY = {"outcome": "refusal", "code": "BUDGET_EXHAUSTED", "message": "exhausted"}


async def no_sleep(_: float) -> None:
    return None


def make_client() -> NilClient:
    transport = NilTransport(
        base_url=BASE,
        bearer_secret=GRANT.bearer_secret(),
        breaker=CircuitBreaker(),
        sleep=no_sleep,
    )
    return NilClient(transport=transport, grant=GRANT)


@respx.mock
async def test_propose_batch_stamps_deterministic_ids_and_is_replay_safe() -> None:
    route = respx.post(f"{BASE}/nil/v0.1/propose").mock(
        return_value=httpx.Response(200, json=server_envelope("PROPOSAL", PROPOSAL_OK_BODY))
    )
    proposes = (
        ProposeBody(verb="services.create_invoice", args={"party_id": "أحمد", "amount": 500}),
        ProposeBody(verb="services.send_followup", args={"party_id": "أحمد"}),
    )
    client = make_client()
    first = await client.propose_batch(proposes, session_id=SESSION, request_timestamp=TS)
    await client.propose_batch(proposes, session_id=SESSION, request_timestamp=TS)  # retry

    assert len(first) == 2 and all(not p.is_refusal for p in first)
    expected_ids = batch_tokens(SESSION, TS.isoformat(), 2)
    sent = [json.loads(call.request.content) for call in route.calls]
    assert [wire["id"] for wire in sent[:2]] == list(expected_ids)
    # Replay safety: a retry of the same batch produces byte-identical sentences.
    assert sent[:2] == sent[2:]


@respx.mock
async def test_refusal_is_returned_not_raised() -> None:
    respx.post(f"{BASE}/nil/v0.1/propose").mock(
        return_value=httpx.Response(200, json=server_envelope("PROPOSAL", REFUSAL_BODY))
    )
    result = await make_client().propose(
        "services.create_invoice",
        {"party_id": "غير معروف"},
        session_id=SESSION,
        request_timestamp=TS,
    )
    assert isinstance(result, ProposalBody)
    assert result.is_refusal
    assert result.code is RefusalCode.BUDGET_EXHAUSTED


@respx.mock
async def test_commit_reuses_key_as_sentence_id_and_surfaces_replay() -> None:
    route = respx.post(f"{BASE}/nil/v0.1/commit").mock(
        return_value=httpx.Response(
            200,
            json=server_envelope(
                "STATUS", {"proposal": "prop-0001", "state": "executed", "replayed": True}
            ),
        )
    )
    key = "c" * 64
    outcome = await make_client().commit("prop-0001", idempotency_key=key)
    assert isinstance(outcome, StatusBody)
    assert outcome.replayed is True
    wire = json.loads(route.calls.last.request.content)
    assert wire["id"] == key
    assert wire["body"] == {"proposal": "prop-0001", "idempotency_key": key}


@respx.mock
async def test_commit_refusal_returns_proposal_body() -> None:
    respx.post(f"{BASE}/nil/v0.1/commit").mock(
        return_value=httpx.Response(
            200, json=server_envelope("PROPOSAL", {"outcome": "refusal", "code": "EXPIRED"})
        )
    )
    outcome = await make_client().commit("prop-0001", idempotency_key="d" * 64)
    assert isinstance(outcome, ProposalBody)
    assert outcome.code is RefusalCode.EXPIRED


ROLLBACK_PREVIEW_BODY = {
    "outcome": "proposal",
    "id": "comp-0001",
    "verb": "services.issue_credit_note",
    "tier": "HIGH",
    "preview": {"ar": "إشعار دائن لعكس الفاتورة"},
    "expires_at": "2026-06-13T07:00:00Z",
}


@respx.mock
async def test_rollback_requests_compensation_preview() -> None:
    from nilscript.sdk.sentences import RollbackReason

    route = respx.post(f"{BASE}/nil/v0.1/rollback").mock(
        return_value=httpx.Response(200, json=server_envelope("PROPOSAL", ROLLBACK_PREVIEW_BODY))
    )
    preview = await make_client().rollback("token-abcdefgh", RollbackReason.OWNER_CANCEL)
    assert isinstance(preview, ProposalBody)
    assert not preview.is_refusal
    assert preview.verb == "services.issue_credit_note"
    wire = json.loads(route.calls.last.request.content)
    assert wire["performative"] == "ROLLBACK"
    assert wire["body"]["compensation_token"] == "token-abcdefgh"
    assert wire["body"]["reason"] == "owner_cancel"


@respx.mock
async def test_rollback_irreversible_is_refusal_not_raise() -> None:
    from nilscript.sdk.sentences import RollbackReason

    respx.post(f"{BASE}/nil/v0.1/rollback").mock(
        return_value=httpx.Response(
            200,
            json=server_envelope(
                "PROPOSAL", {"outcome": "refusal", "code": "IRREVERSIBLE", "message": "cannot un-send"}
            ),
        )
    )
    result = await make_client().rollback("token-abcdefgh", RollbackReason.AGENT_REPAIR)
    assert result.is_refusal
    assert result.code is RefusalCode.IRREVERSIBLE


@respx.mock
async def test_query_returns_data_dict() -> None:
    respx.post(f"{BASE}/nil/v0.1/query").mock(
        return_value=httpx.Response(
            200, json=server_envelope("EVENT", {"event": "proposed", "severity": "info"})
        )
    )
    # Wrong performative for a query answer ⇒ protocol error.
    with pytest.raises(NilProtocolError):
        await make_client().query("services.list_clients")


@respx.mock
async def test_status_round_trip() -> None:
    respx.get(f"{BASE}/nil/v0.1/status/prop-0001").mock(
        return_value=httpx.Response(
            200, json=server_envelope("STATUS", {"proposal": "prop-0001", "state": "executing"})
        )
    )
    status = await make_client().status("prop-0001")
    assert status.state is not None and status.state.value == "executing"


@respx.mock
async def test_malformed_server_answer_is_protocol_error() -> None:
    respx.post(f"{BASE}/nil/v0.1/propose").mock(
        return_value=httpx.Response(200, json={"weird": "shape"})
    )
    with pytest.raises(NilProtocolError):
        await make_client().propose(
            "services.create_invoice", {}, session_id=SESSION, request_timestamp=TS
        )


@respx.mock
async def test_status_refuses_non_url_safe_proposal_ids() -> None:
    with pytest.raises(NilProtocolError, match="URL-safe"):
        await make_client().status("../../../etc/anything")
    assert respx.calls.call_count == 0  # no HTTP request was built


@respx.mock
async def test_query_sentence_ids_are_unique_per_call() -> None:
    route = respx.post(f"{BASE}/nil/v0.1/query").mock(
        return_value=httpx.Response(200, json={"data": {"ok": True}})
    )
    client = make_client()
    await client.query("services.list_clients")
    await client.query("services.list_clients")
    ids = {json.loads(call.request.content)["id"] for call in route.calls}
    assert len(ids) == 2
