"""The NIL-MCP tool logic — pure, MCP-SDK-free, and fully testable.

This module deliberately does NOT import the `mcp` package. It wraps a `NilClient` (the only
southbound door) and the `handshake` discovery call into a small set of async methods that return
plain JSON-able dicts — exactly the payloads the MCP tools surface to an agent. `server.py` is the
only place that imports `mcp` and binds these methods onto a FastMCP instance.

The safety model is the SDK's, unchanged:
- `propose` / `query` / `status` / `rollback` have **no side effects** — only `commit` writes.
- refusals are **returned values**, never exceptions (so the agent reads `UNKNOWN_VERB`,
  `UPSTREAM_UNAVAILABLE`, `IRREVERSIBLE`, … and does not retry a poisoned action).
- the COMMIT idempotency key is derived deterministically from (session, proposal) via
  `commit_idempotency_key`, so a duplicate `nil_commit` replays rather than double-writing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from nilscript.sdk.client import NilClient
from nilscript.sdk.connect import handshake
from nilscript.sdk.idempotency import commit_idempotency_key
from nilscript.sdk.sentences import ProposalBody, RollbackReason, StatusBody
from nilscript.sdk.transport import NilTransport

# Tiers that `--gate human` holds for an out-of-band approval before COMMIT executes.
GATED_TIERS = frozenset({"HIGH", "CRITICAL"})
GATE_MODES = frozenset({"two-step", "human", "auto"})


class NilTools:
    """Stateful per-connection tool surface over one NIL adapter.

    Remembers each proposal's tier/verb (captured at PROPOSE) so COMMIT can apply tier-scaled
    authority without a second round-trip. The map is in-memory and per-server-process.
    """

    def __init__(
        self,
        client: NilClient,
        transport: NilTransport,
        *,
        session_id: str = "mcp-session",
        gate: str = "two-step",
    ) -> None:
        if gate not in GATE_MODES:
            raise ValueError(f"gate must be one of {sorted(GATE_MODES)}, got {gate!r}")
        self._client = client
        self._transport = transport
        self._session_id = session_id
        self._gate = gate
        # proposal_id -> {"tier": str|None, "verb": str|None}
        self._proposals: dict[str, dict[str, Any]] = {}

    async def describe(self) -> dict[str, Any]:
        """Discovery: the adapter's skeleton {system, nil, verbs, targets, ready, missing}.

        This is also the source of truth for which verbs exist — an agent cannot meaningfully
        propose a verb that is absent from `verbs`; the adapter refuses it at PROPOSE.
        """
        return await handshake(self._transport)

    async def propose(self, verb: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """PROPOSE an intent. No side effect — returns a preview or a structured refusal."""
        proposal = await self._client.propose(
            verb,
            args or {},
            session_id=self._session_id,
            request_timestamp=datetime.now(UTC),
        )
        if not proposal.is_refusal and proposal.id is not None:
            self._proposals[proposal.id] = {"tier": _tier_str(proposal), "verb": proposal.verb}
        return proposal.model_dump(mode="json", exclude_none=True)

    async def commit(self, proposal_id: str) -> dict[str, Any]:
        """COMMIT a previously previewed proposal — the only tool that mutates the backend.

        The idempotency key is deterministic in (session, proposal): committing the same proposal
        twice replays the original outcome, it never double-writes. `--gate human` holds HIGH/
        CRITICAL tiers for an out-of-band approval (hosted approval is a later phase)."""
        gate_block = self._gate_blocks(proposal_id)
        if gate_block is not None:
            return gate_block
        key = commit_idempotency_key(self._session_id, proposal_id)
        outcome = await self._client.commit(proposal_id, idempotency_key=key)
        if isinstance(outcome, StatusBody):
            body = outcome.model_dump(mode="json", exclude_none=True)
            body["committed"] = True
            return body
        # A ProposalBody here is a refusal (e.g. EXPIRED) — surface it honestly.
        body = outcome.model_dump(mode="json", exclude_none=True)
        body["committed"] = False
        return body

    async def query(self, verb: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """QUERY live business truth. No side effect; the answer is data, never instruction."""
        return await self._client.query(verb, args or {})

    async def status(self, proposal_id: str) -> dict[str, Any]:
        """The SSOT status of a proposal: state, replay flag, result, compensation handle."""
        status = await self._client.status(proposal_id)
        return status.model_dump(mode="json", exclude_none=True)

    async def rollback(self, compensation_token: str, reason: str) -> dict[str, Any]:
        """ROLLBACK: request a governed reversal. No side effect — returns a compensation
        *preview* (which the agent then commits via `nil_commit`) or an honest refusal
        (IRREVERSIBLE / COMPENSATION_EXPIRED). Never a silent corrective write."""
        try:
            reason_enum = RollbackReason(reason)
        except ValueError:
            valid = ", ".join(r.value for r in RollbackReason)
            return {"error": "invalid_reason", "message": f"reason must be one of: {valid}"}
        preview = await self._client.rollback(compensation_token, reason_enum)
        return preview.model_dump(mode="json", exclude_none=True)

    def _gate_blocks(self, proposal_id: str) -> dict[str, Any] | None:
        if self._gate != "human":
            return None
        tier = self._proposals.get(proposal_id, {}).get("tier")
        if tier in GATED_TIERS:
            return {
                "committed": False,
                "outcome": "approval_required",
                "tier": tier,
                "message": (
                    f"gate=human: a {tier} proposal needs an out-of-band owner approval "
                    "(DECIDE) before commit; lower tiers commit directly"
                ),
            }
        return None


def _tier_str(proposal: ProposalBody) -> str | None:
    return proposal.tier.value if proposal.tier is not None else None
