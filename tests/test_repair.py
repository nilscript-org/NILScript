"""Tests for prescriptive refusals + the bounded grounded repair loop (plan §5).

The headline scenario: invoicing "عبدالرحيم" who isn't created yet -> the refusal prescribes its own
fix -> the loop auto-creates the customer (as a proposal) and retries, succeeding. Ambiguity and the
attempt cap are also covered — the loop must never invent an entity.
"""

from __future__ import annotations

from nilscript.cli.repair import (
    RepairBlock,
    Resolution,
    make_refusal,
    repair_of,
    run_repair_loop,
)

_CUSTOMER_REPAIR = RepairBlock(
    missing_entity="customer", resolve_with="services.create_client", carry="party_id->name"
)


def test_refusal_carries_and_parses_a_repair_block() -> None:
    refusal = make_refusal("UNRESOLVED", "party_id", repair=_CUSTOMER_REPAIR)
    block = repair_of(refusal)
    assert block is not None
    assert block.missing_entity == "customer"
    assert block.target_arg == "party_id"
    assert block.source_field == "name"


def test_abdulrahim_scenario_auto_creates_then_invoices() -> None:
    refusal = make_refusal("UNRESOLVED", "party_id", repair=_CUSTOMER_REPAIR)
    created_log = []

    def resolve(entity: str) -> Resolution:
        assert entity == "customer"
        return Resolution(value="عبدالرحيم")  # the recent-entities pool resolves it unambiguously

    def propose_prerequisite(verb: str, value):
        assert verb == "services.create_client"
        created_log.append((verb, value))
        return {"name": "CUST-001", "customer_name": value}  # the confirmed proposal's result

    def retry_original(args):
        # the original now has a real party_id -> succeeds
        assert args["party_id"] == "CUST-001"
        return {"outcome": "proposal", "id": "INV-9", "verb": "services.create_invoice"}

    outcome = run_repair_loop(
        refusal,
        {"amount": 100, "currency": "SAR"},
        resolve=resolve,
        propose_prerequisite=propose_prerequisite,
        retry_original=retry_original,
    )
    assert outcome.status == "repaired"
    assert outcome.attempts == 1
    assert created_log == [("services.create_client", "عبدالرحيم")]
    assert outcome.final["id"] == "INV-9"


def test_ambiguity_surfaces_candidates_and_never_invents() -> None:
    refusal = make_refusal("UNRESOLVED", "party_id", repair=_CUSTOMER_REPAIR)

    def resolve(entity: str) -> Resolution:
        return Resolution(candidates=["عبدالرحيم", "عبدالرحمن"])  # a typo-risk pair

    calls = []
    outcome = run_repair_loop(
        refusal,
        {},
        resolve=resolve,
        propose_prerequisite=lambda v, x: calls.append((v, x)) or {"name": "X"},
        retry_original=lambda a: {"outcome": "proposal"},
    )
    assert outcome.status == "ambiguous"
    assert outcome.candidates == ["عبدالرحيم", "عبدالرحمن"]
    assert calls == []  # nothing was created


def test_unresolved_asks_the_human() -> None:
    refusal = make_refusal("UNRESOLVED", "party_id", repair=_CUSTOMER_REPAIR)
    outcome = run_repair_loop(
        refusal,
        {},
        resolve=lambda e: Resolution(),  # cannot resolve
        propose_prerequisite=lambda v, x: {"name": "X"},
        retry_original=lambda a: {"outcome": "proposal"},
    )
    assert outcome.status == "unresolved"


def test_loop_is_bounded_on_chained_prerequisites() -> None:
    # A retry that keeps returning a fresh repairable refusal must stop at the cap, not spin forever.
    refusal = make_refusal("UNRESOLVED", "party_id", repair=_CUSTOMER_REPAIR)

    def always_refuses(args):
        return make_refusal("UNRESOLVED", "party_id", repair=_CUSTOMER_REPAIR)

    outcome = run_repair_loop(
        refusal,
        {},
        resolve=lambda e: Resolution(value="X"),
        propose_prerequisite=lambda v, x: {"name": "N"},
        retry_original=always_refuses,
        max_attempts=2,
    )
    assert outcome.status == "exhausted"
    assert outcome.attempts == 2


def test_non_repairable_refusal_is_reported() -> None:
    plain = make_refusal("INVALID_ARGS", "amount")  # no repair block
    outcome = run_repair_loop(
        plain,
        {},
        resolve=lambda e: Resolution(value="X"),
        propose_prerequisite=lambda v, x: {"name": "N"},
        retry_original=lambda a: {"outcome": "proposal"},
    )
    assert outcome.status == "not_repairable"
