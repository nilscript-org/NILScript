"""Security regression: EVENT proposal ids are validated at the boundary (M1a).

An EVENT's `proposal` is used to look up the owning conversation and to build a Temporal
workflow id; a malformed id must be rejected by the model, like CommitBody/StatusBody.
"""

import pytest
from pydantic import ValidationError
from nilscript.sdk.sentences import EventBody, EventKind, Severity


def test_rejects_malformed_proposal_id() -> None:
    with pytest.raises(ValidationError):
        EventBody(event=EventKind.APPROVED, severity=Severity.INFO, proposal="bad id: spaces!")


def test_accepts_valid_proposal_id() -> None:
    event = EventBody(event=EventKind.APPROVED, severity=Severity.INFO, proposal="prop-0001")
    assert event.proposal == "prop-0001"


def test_allows_absent_proposal_for_operational_event() -> None:
    event = EventBody(event=EventKind.PROPOSED, severity=Severity.INFO)
    assert event.proposal is None
