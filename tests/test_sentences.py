"""Model-level rules: closed sets, frozen models, the PROPOSAL outcome shape."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from nilscript.sdk.refusals import RETRIABLE_REFUSALS, RefusalCode
from nilscript.sdk.sentences import (
    Candidate,
    Performative,
    ProposalBody,
    ProposeBody,
    Tier,
)

TS = datetime(2026, 6, 12, 7, 0, 0, tzinfo=UTC)


def test_decide_is_not_a_performative() -> None:
    assert "DECIDE" not in {p.value for p in Performative}


def test_propose_body_rejects_bad_verb_shape() -> None:
    with pytest.raises(ValidationError):
        ProposeBody(verb="Services.CreateInvoice", args={})


def test_propose_body_is_frozen() -> None:
    body = ProposeBody(verb="services.create_invoice", args={})
    with pytest.raises(ValidationError):
        body.verb = "services.other"  # type: ignore[misc]


def test_refusal_must_not_carry_preview() -> None:
    with pytest.raises(ValidationError, match="refusal"):
        ProposalBody(
            outcome="refusal",
            code=RefusalCode.UNRESOLVED,
            preview={"ar": "نص"},
        )


def test_proposal_requires_preview_and_tier() -> None:
    with pytest.raises(ValidationError, match="proposal"):
        ProposalBody(outcome="proposal", id="prop-0001", verb="services.create_invoice")


def test_ambiguous_requires_candidates() -> None:
    with pytest.raises(ValidationError, match="AMBIGUOUS"):
        ProposalBody(outcome="refusal", code=RefusalCode.AMBIGUOUS)


def test_candidates_capped_at_eight() -> None:
    too_many = tuple(Candidate(id=f"c{i}", name=f"n{i}") for i in range(9))
    with pytest.raises(ValidationError):
        ProposalBody(outcome="refusal", code=RefusalCode.AMBIGUOUS, candidates=too_many)


def test_preview_for_exact_locale_and_fallback() -> None:
    body = ProposalBody(
        outcome="proposal",
        id="prop-0001",
        verb="services.create_invoice",
        tier=Tier.LOW,
        preview={"ar": "معاينة", "en": "preview"},
        expires_at=TS,
    )
    assert body.preview_for("en") == "preview"
    assert body.preview_for("fr") == "معاينة"  # falls back to primary ar


def test_annex_a_is_complete() -> None:
    assert len(RefusalCode) == 15
    assert {RefusalCode.RATE_LIMITED, RefusalCode.UPSTREAM_UNAVAILABLE} == RETRIABLE_REFUSALS
