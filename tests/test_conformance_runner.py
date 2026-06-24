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
        self._tokens: set[str] = set()
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
        token = f"ctok-{proposal_id}-{'z' * 12}"
        self._tokens.add(token)
        body = {
            "proposal": proposal_id,
            "state": "executed",
            "replayed": False,
            "compensation": {"reversibility": "COMPENSABLE", "token": token},
        }
        self._ledger[idempotency_key] = body
        self._executed.add(proposal_id)
        return {"body": body}

    def rollback(self, compensation_token: str, reason: str) -> dict[str, Any]:
        # A faithful reversal: a *previewed* compensation (a proposal), never a silent write.
        if compensation_token in self._tokens:
            return {"body": {"outcome": "proposal", "id": "comp-1", "verb": "commerce.process_refund"}}
        return {"body": {"outcome": "refusal", "code": "COMPENSATION_EXPIRED"}}

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


# ── rollback-honesty rows ────────────────────────────────────────────────────


class IrreversibleProbe(ConformantProbe):
    """A shim whose write verb is IRREVERSIBLE — every reversal must be refused honestly."""

    def commit(self, proposal_id: str, idempotency_key: str) -> dict[str, Any]:
        body = super().commit(proposal_id, idempotency_key)
        _body = body.get("body", {})
        _body.pop("compensation", None)  # IRREVERSIBLE effects carry no reversal token
        return body

    def rollback(self, compensation_token: str, reason: str) -> dict[str, Any]:
        return {"body": {"outcome": "refusal", "code": "IRREVERSIBLE"}}


class LyingProbe(ConformantProbe):
    """Claims to be reversible but *silently executes* the reversal — the runner must catch it."""

    def rollback(self, compensation_token: str, reason: str) -> dict[str, Any]:
        return {"body": {"state": "executed"}}  # no preview, no refusal: a silent write


def _rollback_names(checks: list) -> set[str]:
    return {c.name for c in checks}


def test_reversible_shim_passes_rollback_rows() -> None:
    checks = run_conformance(
        ConformantProbe(), write_verb="services.create_invoice", write_args=_ARGS,
        reversibility="COMPENSABLE",
    )
    rollback = [c for c in checks if c.name.startswith("rollback_")]
    assert {c.name for c in rollback} == {
        "rollback_previews_compensation", "rollback_no_silent_write", "rollback_unknown_token_refuses",
    }
    assert all(c.passed for c in rollback), [(c.name, c.detail) for c in rollback if not c.passed]


def test_irreversible_shim_refuses_reversal_honestly() -> None:
    checks = run_conformance(
        IrreversibleProbe(), write_verb="services.create_invoice", write_args=_ARGS,
        reversibility="IRREVERSIBLE",
    )
    row = next(c for c in checks if c.name == "rollback_irreversible_refuses")
    assert row.passed, row.detail


def test_runner_detects_silent_reversal_write() -> None:
    checks = run_conformance(
        LyingProbe(), write_verb="services.create_invoice", write_args=_ARGS,
        reversibility="COMPENSABLE",
    )
    failed = {c.name for c in checks if not c.passed}
    assert "rollback_no_silent_write" in failed
    assert "rollback_previews_compensation" in failed


def test_rollback_rows_absent_without_declared_reversibility() -> None:
    checks = run_conformance(ConformantProbe(), write_verb="services.create_invoice", write_args=_ARGS)
    assert not any(c.name.startswith("rollback_") for c in checks)


class _RefProbe(ConformantProbe):
    """Echoes a relational field by resolved NAME — the legible behavior the row enforces."""

    def __init__(self, legible: bool) -> None:
        super().__init__()
        self._legible = legible

    def propose(self, verb: str, args: dict[str, Any]) -> dict[str, Any]:
        if verb == "commerce.create_order" and args.get("party_id"):
            refs = {"party_id": {"value": "cli_88", "label": "Acme Corp"}} if self._legible else {}
            return {"body": {"outcome": "proposal", "id": "rp1", "resolved": {"references": refs}}}
        return super().propose(verb, args)


def test_references_echoed_by_name_passes_when_legible() -> None:
    checks = run_conformance(
        _RefProbe(legible=True), write_verb="services.create_invoice", write_args=_ARGS,
        reference_probe=("commerce.create_order", {"party_id": "Acme Corp"}),
    )
    row = next(c for c in checks if c.name == "references_echoed_by_name")
    assert row.passed, row.detail


def test_references_row_detects_bare_id_illegibility() -> None:
    checks = run_conformance(
        _RefProbe(legible=False), write_verb="services.create_invoice", write_args=_ARGS,
        reference_probe=("commerce.create_order", {"party_id": "Acme Corp"}),
    )
    row = next(c for c in checks if c.name == "references_echoed_by_name")
    assert not row.passed  # a bare id with no label must fail the row


def test_references_row_absent_without_probe() -> None:
    checks = run_conformance(ConformantProbe(), write_verb="services.create_invoice", write_args=_ARGS)
    assert not any(c.name == "references_echoed_by_name" for c in checks)
