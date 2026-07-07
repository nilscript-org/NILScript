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

`GovernedRoutingNilClient` is the D8 cutover: it replaces implicit "newest-declarer-wins" routing with
explicit Domain-based backend bindings. Proposals route to adapters specified in the cycle's Domain,
and the binding follows through commit/status/rollback (same as RoutingNilClient). This is the
governance-first router — all backends are known at cycle registration, never auto-discovered.
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


class GovernedRoutingNilClient:
    """Routes calls via explicit Domain backend bindings (D8 governance).

    Unlike RoutingNilClient (which discovers verbs from active adapters), this router uses
    explicit bindings from the cycle's Domain definition. Each capability is bound to a specific
    backend adapter at compile time; the binding follows through propose→commit→status/rollback.
    This is governance-first: all valid backends are known upfront, never inferred.

    Args:
        domain_id: The cycle's Domain identifier (e.g., "ws_acme_procurement@1.0.0")
        backend_bindings: A dict mapping capability names to adapter addresses
                         (e.g., {"procurement.create_purchase_invoice": "odoo"})
        adapter_clients: A dict mapping adapter names to their NilClient instances
                        (e.g., {"odoo": odoo_client, "comms": comms_client})
    """

    def __init__(
        self,
        domain_id: str,
        backend_bindings: dict[str, str],
        adapter_clients: dict[str, NilClient],
    ) -> None:
        self._domain_id = domain_id
        self._backend_bindings = backend_bindings
        self._adapter_clients = adapter_clients
        self._by_proposal: dict[str, NilClient] = {}
        self._by_token: dict[str, NilClient] = {}

    def _adapter_for_capability(self, capability: str) -> NilClient:
        """Resolve a capability to its bound adapter client.

        Raises:
            RuntimeError: If the capability has no explicit binding in this Domain.
        """
        adapter_name = self._backend_bindings.get(capability)
        if adapter_name is None:
            raise RuntimeError(
                f"No backend binding for '{capability}' in Domain '{self._domain_id}'. "
                f"Available bindings: {list(self._backend_bindings.keys())}"
            )
        adapter = self._adapter_clients.get(adapter_name)
        if adapter is None:
            raise RuntimeError(
                f"Adapter '{adapter_name}' for capability '{capability}' is not available. "
                f"Available adapters: {list(self._adapter_clients.keys())}"
            )
        return adapter

    async def propose(
        self,
        verb: str,
        args: dict[str, Any],
        *,
        session_id: str,
        request_timestamp: datetime,
        trace: str | None = None,
    ) -> ProposalBody:
        """Propose to the adapter bound for this verb."""
        client = self._adapter_for_capability(verb)
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
        """Route each intent to its bound adapter, preserving order.

        Items in one batch may span backends; each is proposed on the adapter bound to its verb.
        """
        results: list[ProposalBody] = []
        for propose in proposes:
            client = self._adapter_for_capability(propose.verb)
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
        """Commit to the adapter that held the proposal.

        A proposal MUST commit on the backend that held it — we follow the recorded binding.
        Falls back to raising an error if the proposal is unknown (governance safety).
        """
        client = self._by_proposal.get(proposal_id)
        if client is None:
            raise RuntimeError(
                f"Proposal '{proposal_id}' is unknown in Domain '{self._domain_id}'. "
                "A proposal must be committed on the adapter that held it; "
                "ensure the proposal was proposed in this execution context."
            )
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
        """Query the adapter bound for this verb."""
        client = self._adapter_for_capability(verb)
        return await client.query(verb, args, ts=ts, trace=trace)

    async def rollback(
        self,
        compensation_token: str,
        reason: RollbackReason,
        *,
        idempotency_key: str | None = None,
        ts: datetime | None = None,
        trace: str | None = None,
    ) -> ProposalBody:
        """Reverse on the backend that issued the token.

        Raises RuntimeError if the token is unknown (governance safety).
        """
        client = self._by_token.get(compensation_token)
        if client is None:
            raise RuntimeError(
                f"Compensation token '{compensation_token}' is unknown in Domain '{self._domain_id}'. "
                "A rollback must reverse on the adapter that issued the token; "
                "ensure the token was generated in this execution context."
            )
        return await client.rollback(
            compensation_token, reason, idempotency_key=idempotency_key, ts=ts, trace=trace
        )

    async def status(self, proposal_id: str) -> StatusBody:
        """Check status on the adapter that held the proposal.

        Raises RuntimeError if the proposal is unknown (governance safety).
        """
        client = self._by_proposal.get(proposal_id)
        if client is None:
            raise RuntimeError(
                f"Proposal '{proposal_id}' is unknown in Domain '{self._domain_id}'. "
                "A proposal must be checked on the adapter that held it."
            )
        return await client.status(proposal_id)
