"""The NIL client — the only southbound door (02-NIL-CLIENT).

Speaks PROPOSE / COMMIT / QUERY / STATUS; receives PROPOSAL / STATUS. Refusals are
returned values, never exceptions. Envelope ids for PROPOSE batches and idempotency
keys for COMMIT are deterministic (idempotency.nil_uuid) so retries replay byte-identically.
"""

import re
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from nilscript.sdk.errors import NilProtocolError, NilTransportError
from nilscript.sdk.grants import GrantRef
from nilscript.sdk.idempotency import nil_uuid
from nilscript.sdk.sentences import (
    PROPOSAL_ID_PATTERN,
    CommitBody,
    Envelope,
    Performative,
    ProposalBody,
    ProposeBody,
    QueryBody,
    StatusBody,
    make_envelope,
)
from nilscript.sdk.transport import NilTransport

_SAFE_PROPOSAL_ID = re.compile(PROPOSAL_ID_PATTERN)

PROPOSE_PATH = "/nil/v0.1/propose"
COMMIT_PATH = "/nil/v0.1/commit"
QUERY_PATH = "/nil/v0.1/query"
STATUS_PATH = "/nil/v0.1/status"

CommitOutcome = StatusBody | ProposalBody


def _fresh_id() -> str:
    return uuid.uuid4().hex


class NilClient:
    def __init__(
        self,
        *,
        transport: NilTransport,
        grant: GrantRef,
        id_factory: Callable[[], str] = _fresh_id,
    ) -> None:
        self._transport = transport
        self._grant = grant
        self._id_factory = id_factory

    async def propose_batch(
        self,
        proposes: Sequence[ProposeBody],
        *,
        session_id: str,
        request_timestamp: datetime,
        trace: str | None = None,
    ) -> tuple[ProposalBody, ...]:
        """One sentence per intent; ids are the batch's NIL_UUIDs — reuse-safe on retry."""
        results: list[ProposalBody] = []
        ts_key = request_timestamp.isoformat()
        for index, propose in enumerate(proposes):
            envelope = make_envelope(
                Performative.PROPOSE,
                propose,
                sentence_id=nil_uuid(session_id, ts_key, index),
                grant=self._grant.grant_id,
                workspace=self._grant.workspace,
                ts=request_timestamp,
                trace=trace,
            )
            try:
                answer = await self._transport.post_sentence(PROPOSE_PATH, envelope.to_wire())
            except NilTransportError as exc:
                # The batch split: earlier sentences already landed (idempotency makes
                # the retry safe), but surface how far we got for the operator.
                exc.add_note(
                    f"batch split: {len(results)}/{len(proposes)} sentences answered "
                    "before the transport failure; retry replays safely"
                )
                raise
            results.append(self._parse_proposal(answer))
        return tuple(results)

    async def propose(
        self,
        verb: str,
        args: dict[str, Any],
        *,
        session_id: str,
        request_timestamp: datetime,
        trace: str | None = None,
    ) -> ProposalBody:
        batch = await self.propose_batch(
            (ProposeBody(verb=verb, args=args),),
            session_id=session_id,
            request_timestamp=request_timestamp,
            trace=trace,
        )
        return batch[0]

    async def commit(
        self,
        proposal_id: str,
        *,
        idempotency_key: str,
        ts: datetime | None = None,
        trace: str | None = None,
    ) -> CommitOutcome:
        """The key is supplied by the caller (minted once at emission), never minted here."""
        envelope = make_envelope(
            Performative.COMMIT,
            CommitBody(proposal=proposal_id, idempotency_key=idempotency_key),
            sentence_id=idempotency_key,
            grant=self._grant.grant_id,
            workspace=self._grant.workspace,
            ts=ts if ts is not None else _utcnow(),
            trace=trace,
        )
        answer = await self._transport.post_sentence(COMMIT_PATH, envelope.to_wire())
        performative, body = self._parse_sentence(
            answer, {Performative.STATUS, Performative.PROPOSAL}
        )
        if performative is Performative.STATUS:
            return StatusBody.model_validate(body)
        return ProposalBody.model_validate(body)

    async def query(
        self,
        verb: str,
        args: dict[str, Any] | None = None,
        *,
        ts: datetime | None = None,
        trace: str | None = None,
    ) -> dict[str, Any]:
        """Read business truth fresh — the answer is data, never instruction (§11.2)."""
        envelope = make_envelope(
            Performative.QUERY,
            QueryBody(verb=verb, args=args),
            sentence_id=self._id_factory(),  # reads are not idempotent-keyed; ids stay unique
            grant=self._grant.grant_id,
            workspace=self._grant.workspace,
            ts=ts if ts is not None else _utcnow(),
            trace=trace,
        )
        answer = await self._transport.post_sentence(QUERY_PATH, envelope.to_wire())
        data = answer.get("data")
        if not isinstance(data, dict):
            raise NilProtocolError("query answer must be an object with a 'data' member")
        return data

    async def status(self, proposal_id: str) -> StatusBody:
        if not _SAFE_PROPOSAL_ID.match(proposal_id):
            raise NilProtocolError("proposal id is not URL-safe; refusing to build the path")
        answer = await self._transport.get(f"{STATUS_PATH}/{proposal_id}")
        _, body = self._parse_sentence(answer, {Performative.STATUS})
        return StatusBody.model_validate(body)

    def _parse_proposal(self, answer: dict[str, Any]) -> ProposalBody:
        _, body = self._parse_sentence(answer, {Performative.PROPOSAL})
        return ProposalBody.model_validate(body)

    def _parse_sentence(
        self, answer: dict[str, Any], expected: set[Performative]
    ) -> tuple[Performative, dict[str, Any]]:
        try:
            envelope = Envelope.model_validate(answer)
        except ValidationError as exc:
            # Fixed message: the validation error embeds response fragments (possible PII)
            # and belongs in debug tooling via the cause chain, not in operator logs.
            raise NilProtocolError("server answer is not a NIL sentence") from exc
        if envelope.performative not in expected:
            raise NilProtocolError(
                f"expected {sorted(p.value for p in expected)}, got {envelope.performative}"
            )
        return envelope.performative, envelope.body


def _utcnow() -> datetime:
    return datetime.now(UTC)
