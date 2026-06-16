"""Tests for the conformance-test runner (plan §3.3). It must confirm conformance AND detect
non-conformance — both directions are exercised with in-memory fake probes (no network)."""

from __future__ import annotations

from typing import Any

from nilscript.cli.conformance import run_conformance, summarize


class ConformantProbe:
    """A faithful in-memory NIL shim: previews without writing, executes + replays on COMMIT."""

    def __init__(self) -> None:
        self._proposals: dict[str, dict] = {}
        self._ledger: dict[str, dict] = {}
        self._executed: set[str] = set()
        self._n = 0

    def propose(self, verb: str, args: dict[str, Any]) -> dict[str, Any]:
        if verb != "services.create_invoice":
            return {"body": {"outcome": "refusal", "code": "UNSUPPORTED"}}
        for required in ("party_id", "amount", "currency"):
            if not args.get(required):
                return {"body": {"outcome": "refusal", "code": "INVALID_ARGS", "field": required}}
        self._n += 1
        pid = f"p{self._n}"
        self._proposals[pid] = {"verb": verb, "args": args}
        return {"body": {"outcome": "proposal", "id": pid}}

    def commit(self, proposal_id: str, idempotency_key: str) -> dict[str, Any]:
        if idempotency_key in self._ledger:
            return {"body": {**self._ledger[idempotency_key], "replayed": True}}
        if proposal_id not in self._proposals:
            return {"body": {"outcome": "refusal", "code": "EXPIRED", "state": "expired"}}
        body = {"proposal": proposal_id, "state": "executed", "replayed": False}
        self._ledger[idempotency_key] = body
        self._executed.add(proposal_id)
        return {"body": body}

    def query(self, verb: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"data": {"clients": []}}  # bare {data}, not an envelope

    def status(self, proposal_id: str) -> dict[str, Any]:
        state = "executed" if proposal_id in self._executed else "expired"
        return {"body": {"proposal": proposal_id, "state": state}}


class BrokenProbe(ConformantProbe):
    """A shim that WRITES on PROPOSE and is NOT idempotent — the runner must catch this."""

    def commit(self, proposal_id: str, idempotency_key: str) -> dict[str, Any]:
        # never records the ledger -> replay re-executes (not idempotent), and unknown proposals
        # are happily "executed" (phantom write).
        body = {"proposal": proposal_id, "state": "executed", "replayed": False}
        self._executed.add(proposal_id)
        return {"body": body}


_ARGS = {"party_id": "C-1", "amount": 100, "currency": "SAR"}


def test_conformant_shim_passes_every_row() -> None:
    checks = run_conformance(
        ConformantProbe(),
        write_verb="services.create_invoice",
        write_args=_ARGS,
        query_verb="services.list_clients",
        query_args={},
    )
    failed = [c for c in checks if not c.passed]
    assert not failed, f"unexpected failures: {[(c.name, c.detail) for c in failed]}"
    passed, total = summarize(checks)
    assert passed == total == 8


def test_runner_detects_non_idempotent_and_phantom_writes() -> None:
    checks = run_conformance(BrokenProbe(), write_verb="services.create_invoice", write_args=_ARGS)
    names_failed = {c.name for c in checks if not c.passed}
    assert "commit_idempotent_replay" in names_failed
    assert "unknown_proposal_does_not_execute" in names_failed


def test_missing_arg_row_uses_a_dropped_required_field() -> None:
    checks = run_conformance(ConformantProbe(), write_verb="services.create_invoice", write_args=_ARGS)
    row = next(c for c in checks if c.name == "missing_required_arg_refuses")
    assert row.passed
