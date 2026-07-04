"""Verb-routed NIL client — the primitive that lets ONE run span several adapters.

A plain run walks its plan against a single active adapter (every verb goes to the same backend). But
a governed cycle legitimately mixes backends: `crm.*` reads a client from Odoo, `comms.send_email`
sends through the comms adapter. Composition (`StageRunner`) already routes by NAMED stages, but a
hand-drawn cycle shouldn't have to be split into stages just to reach two systems.

`RoutingNilClient` duck-types `NilClient` and dispatches each call to the adapter that DECLARES the
verb. It is PURE — it holds real per-adapter `NilClient`s and a `{verb: client}` map; the control
plane builds that map from each active adapter's describe. Because `commit`/`status`/`rollback` carry
a proposal id or token (not a verb), the router REMEMBERS which adapter a proposal was proposed on and
follows it there — a proposal must always be committed on the same backend that held it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from nilscript.sdk.client import CommitOutcome, NilClient
from nilscript.sdk.sentences import (
    ProposalBody,
    ProposeBody,
    RollbackReason,
    StatusBody,
)


class RoutingNilClient:
    """A `NilClient`-shaped facade that routes each verb to its declaring adapter.

    `default` handles any verb with no explicit route (and single-adapter fallbacks). `routes` maps a
    verb to the `NilClient` for the adapter that serves it. Proposal ids and compensation tokens are
    bound to their originating client at propose/commit time so the follow-up commit/status/rollback
    lands on the SAME backend — never a sibling that never saw the proposal.
    """

    def __init__(self, *, default: NilClient, routes: dict[str, NilClient]) -> None:
        self._default = default
        self._routes = routes
        self._by_proposal: dict[str, NilClient] = {}
        self._by_token: dict[str, NilClient] = {}

    def _for_verb(self, verb: str) -> NilClient:
        return self._routes.get(verb, self._default)

    async def propose(
        self,
        verb: str,
        args: dict[str, Any],
        *,
        session_id: str,
        request_timestamp: datetime,
        trace: str | None = None,
    ) -> ProposalBody:
        client = self._for_verb(verb)
        proposal = await client.propose(
            verb, args, session_id=session_id, request_timestamp=request_timestamp, trace=trace
        )
        if proposal.id:
            self._by_proposal[proposal.id] = client
        return proposal

    async def propose_batch(
        self,
        proposes: Sequence[ProposeBody],
        *,
        session_id: str,
        request_timestamp: datetime,
        trace: str | None = None,
    ) -> tuple[ProposalBody, ...]:
        # Route each intent to its own verb's adapter, preserving order. Items in one batch may span
        # backends; each is proposed on the client that serves its verb and bound for later commit.
        results: list[ProposalBody] = []
        for propose in proposes:
            client = self._for_verb(propose.verb)
            (proposal,) = await client.propose_batch(
                (propose,),
                session_id=session_id,
                request_timestamp=request_timestamp,
                trace=trace,
            )
            if proposal.id:
                self._by_proposal[proposal.id] = client
            results.append(proposal)
        return tuple(results)

    async def commit(
        self,
        proposal_id: str,
        *,
        idempotency_key: str,
        ts: datetime | None = None,
        trace: str | None = None,
    ) -> CommitOutcome:
        # A proposal MUST commit on the backend that held it — follow the recorded binding.
        client = self._by_proposal.get(proposal_id, self._default)
        outcome = await client.commit(
            proposal_id, idempotency_key=idempotency_key, ts=ts, trace=trace
        )
        token = getattr(outcome, "compensation", None)
        if isinstance(token, str) and token:
            self._by_token[token] = client
        return outcome

    async def query(
        self,
        verb: str,
        args: dict[str, Any] | None = None,
        *,
        ts: datetime | None = None,
        trace: str | None = None,
    ) -> dict[str, Any]:
        return await self._for_verb(verb).query(verb, args, ts=ts, trace=trace)

    async def rollback(
        self,
        compensation_token: str,
        reason: RollbackReason,
        *,
        idempotency_key: str | None = None,
        ts: datetime | None = None,
        trace: str | None = None,
    ) -> ProposalBody:
        # Reverse on the backend that issued the token; fall back to default if unseen this session.
        client = self._by_token.get(compensation_token, self._default)
        return await client.rollback(
            compensation_token, reason, idempotency_key=idempotency_key, ts=ts, trace=trace
        )

    async def status(self, proposal_id: str) -> StatusBody:
        return await self._by_proposal.get(proposal_id, self._default).status(proposal_id)
