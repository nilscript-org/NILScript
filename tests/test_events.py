"""Inbound EVENT parsing and at-least-once dedup by (workspace, sequence)."""

import pytest
from nilscript.sdk.errors import NilProtocolError
from nilscript.sdk.events import EventDeduper, parse_event
from nilscript.sdk.sentences import EventKind


def event_wire() -> dict[str, object]:
    return {
        "nil": "0.1",
        "id": "evt-sentence-0001",
        "performative": "EVENT",
        "grant": "grant-001",
        "workspace": "ws-001",
        "ts": "2026-06-12T07:00:01Z",
        "body": {"event": "approved", "severity": "info", "proposal": "prop-0001"},
    }


def test_parse_event_returns_envelope_and_body() -> None:
    envelope, body = parse_event(event_wire())
    assert envelope.workspace == "ws-001"
    assert body.event is EventKind.APPROVED


def test_parse_event_rejects_other_performatives() -> None:
    wire = event_wire() | {"performative": "QUERY"}
    with pytest.raises(NilProtocolError):
        parse_event(wire)


def test_deduper_drops_duplicates_within_workspace_only() -> None:
    deduper = EventDeduper()
    assert deduper.is_new("ws-001", 1)
    assert not deduper.is_new("ws-001", 1)
    assert deduper.is_new("ws-002", 1)
    assert deduper.is_new("ws-001", 2)


def test_deduper_evicts_oldest_beyond_capacity() -> None:
    deduper = EventDeduper(max_entries=2)
    assert deduper.is_new("ws", 1)
    assert deduper.is_new("ws", 2)
    assert deduper.is_new("ws", 3)  # evicts (ws, 1)
    assert deduper.is_new("ws", 1)  # forgotten, treated as new again
    assert not deduper.is_new("ws", 3)
