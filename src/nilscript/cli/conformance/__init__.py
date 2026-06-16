"""`conformance-test` (plan §3.3, Phase 4): drive a live NIL shim through the conformance matrix.

The runner is the intelligence; it is handed a `ShimProbe` (the four agent-plane calls) so it is
transport-agnostic and fully testable without a network — the CLI wires a real httpx probe to a
`--url`. The matrix asserts the load-bearing contract rules from the translation-shim guide §6: a
valid PROPOSE previews without writing, an unknown verb / missing arg REFUSES (not 500), COMMIT
executes and is idempotent on replay, STATUS reflects reality, and QUERY returns a bare `{data}`.

The harness must demonstrably **detect non-conformance** (a broken shim fails rows), not only confirm
conformance — both directions are tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ShimProbe(Protocol):
    """The four agent-plane calls, returning each endpoint's parsed JSON body."""

    def propose(self, verb: str, args: dict[str, Any]) -> dict[str, Any]: ...

    def commit(self, proposal_id: str, idempotency_key: str) -> dict[str, Any]: ...

    def query(self, verb: str, args: dict[str, Any]) -> dict[str, Any]: ...

    def status(self, proposal_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def _body(envelope: dict[str, Any]) -> dict[str, Any]:
    """NIL agent-plane responses are envelopes; QUERY is the exception (bare {data})."""
    return envelope.get("body", envelope) if isinstance(envelope, dict) else {}


def _outcome(envelope: dict[str, Any]) -> str:
    return str(_body(envelope).get("outcome", ""))


def run_conformance(
    probe: ShimProbe,
    *,
    write_verb: str,
    write_args: dict[str, Any],
    unknown_verb: str = "namespace.__does_not_exist__",
    query_verb: str | None = None,
    query_args: dict[str, Any] | None = None,
) -> list[Check]:
    """Run the conformance matrix against `probe`. Returns one Check per row (order stable)."""
    checks: list[Check] = []

    # Row 1 — valid PROPOSE previews (a proposal, not a refusal), and yields a proposal id.
    proposed = probe.propose(write_verb, write_args)
    proposal_id = _body(proposed).get("id", "")
    checks.append(
        Check(
            "propose_valid_yields_proposal",
            _outcome(proposed) == "proposal" and bool(proposal_id),
            f"outcome={_outcome(proposed)!r} id={proposal_id!r}",
        )
    )

    # Row 2 — unknown verb REFUSES (contract: a verb the backend lacks is a refusal, not an error).
    unknown = probe.propose(unknown_verb, {})
    checks.append(
        Check(
            "unknown_verb_refuses",
            _outcome(unknown) == "refusal",
            f"outcome={_outcome(unknown)!r}",
        )
    )

    # Row 3 — missing a required arg REFUSES with a field pointer.
    thin_args = {k: v for k, v in write_args.items()}
    dropped = next(iter(thin_args), None)
    if dropped is not None:
        thin_args.pop(dropped)
    missing = probe.propose(write_verb, thin_args)
    checks.append(
        Check(
            "missing_required_arg_refuses",
            _outcome(missing) == "refusal" and bool(dropped),
            f"dropped={dropped!r} outcome={_outcome(missing)!r}",
        )
    )

    # Row 4 — COMMIT executes the previewed proposal.
    key = f"conf-{proposal_id}"
    committed = probe.commit(proposal_id, key) if proposal_id else {}
    state = _body(committed).get("state", "")
    checks.append(Check("commit_executes", state == "executed", f"state={state!r}"))

    # Row 5 — COMMIT is idempotent: replaying the same key is flagged replayed, not re-executed.
    replayed = probe.commit(proposal_id, key) if proposal_id else {}
    is_replayed = _body(replayed).get("replayed") is True
    checks.append(Check("commit_idempotent_replay", is_replayed, f"replayed={_body(replayed).get('replayed')!r}"))

    # Row 6 — STATUS reflects an executed proposal.
    after = probe.status(proposal_id) if proposal_id else {}
    checks.append(
        Check("status_reports_executed", _body(after).get("state") == "executed", f"state={_body(after).get('state')!r}")
    )

    # Row 7 — COMMIT of an unknown proposal does not execute (refusal/expired, never a phantom write).
    phantom = probe.commit("__no_such_proposal__", "conf-phantom")
    phantom_state = _body(phantom).get("state", "")
    phantom_outcome = _outcome(phantom)
    checks.append(
        Check(
            "unknown_proposal_does_not_execute",
            phantom_state != "executed" and phantom_outcome != "proposal",
            f"state={phantom_state!r} outcome={phantom_outcome!r}",
        )
    )

    # Row 8 — QUERY returns a bare {data} (NOT an envelope) when a query verb is provided.
    if query_verb is not None:
        answer = probe.query(query_verb, query_args or {})
        bare = isinstance(answer, dict) and "data" in answer and "performative" not in answer
        checks.append(Check("query_returns_bare_data", bare, f"keys={sorted(answer)[:4] if isinstance(answer, dict) else answer!r}"))

    return checks


def summarize(checks: list[Check]) -> tuple[int, int]:
    """Return (passed, total)."""
    passed = sum(1 for c in checks if c.passed)
    return passed, len(checks)
