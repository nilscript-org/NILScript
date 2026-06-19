"""Control-plane event store + ingest API (audit single-pane)."""

import hashlib
import hmac
import json

import pytest

pytest.importorskip("fastapi", reason="needs fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from nilscript.controlplane.app import create_app  # noqa: E402
from nilscript.controlplane.store import EventStore  # noqa: E402


def _store():
    return EventStore(":memory:")


def _event(seq, *, ws="ws1", ev="executed", verb="commerce.create_product", proposal="p1"):
    return {
        "nil": "0.1", "id": f"id{seq}", "performative": "EVENT", "grant": "g1", "workspace": ws,
        "ts": "2026-06-19T00:00:00Z",
        "body": {"event": ev, "severity": "info", "proposal": proposal, "verb": verb, "tier": "MEDIUM"},
    }


def test_ingest_stores_and_recent_reads_newest_first() -> None:
    s = _store()
    assert s.ingest(_event(1, verb="a"), 1) is True
    assert s.ingest(_event(2, verb="b"), 2) is True
    rows = s.recent()
    assert [r["verb"] for r in rows] == ["b", "a"]  # newest first
    assert s.count() == 2


def test_ingest_dedups_by_event_id() -> None:
    s = _store()
    assert s.ingest(_event(1), 7) is True
    assert s.ingest(_event(1), 7) is False  # same envelope id → no-op (at-least-once retry)
    assert s.count() == 1


def test_same_sequence_different_event_id_not_a_dup() -> None:
    # The adapter resets its in-memory sequence on restart, so two distinct events can share a
    # (workspace, sequence) — they must NOT be deduped. Distinct envelope ids keep them apart.
    s = _store()
    assert s.ingest(_event(1, proposal="a"), 5) is True
    assert s.ingest(_event(2, proposal="b"), 5) is True  # same seq=5, different id → stored
    assert s.count() == 2


def test_ingest_endpoint_verifies_hmac_and_stores() -> None:
    s = _store()
    secret = "topsecret"
    client = TestClient(create_app(s, secret=secret))
    payload = _event(1, verb="commerce.create_coupon")
    raw = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    bad = client.post("/events/ingest", content=raw, headers={"X-NIL-Signature": "deadbeef", "X-NIL-Sequence": "1"})
    assert bad.status_code == 401

    ok = client.post("/events/ingest", content=raw, headers={"X-NIL-Signature": sig, "X-NIL-Sequence": "1"})
    assert ok.status_code == 200 and ok.json() == {"ok": True, "new": True}

    listed = client.get("/api/events").json()["events"]
    assert len(listed) == 1 and listed[0]["verb"] == "commerce.create_coupon"


def test_ingest_endpoint_open_when_no_secret() -> None:
    client = TestClient(create_app(_store(), secret=""))
    r = client.post("/events/ingest", content=json.dumps(_event(1)).encode(), headers={"X-NIL-Sequence": "1"})
    assert r.status_code == 200 and r.json()["new"] is True


def test_healthz_reports_count() -> None:
    s = _store()
    s.ingest(_event(1), 1)
    client = TestClient(create_app(s, secret=""))
    assert client.get("/healthz").json() == {"status": "ok", "events": 1}


# ── human-approval gate (Phase 2) ────────────────────────────────────────────────────────────

def _proposed(seq, *, proposal, verb="commerce.process_refund", tier="HIGH"):
    return {
        "nil": "0.1", "id": f"prop{seq}", "performative": "EVENT", "grant": "g1", "workspace": "",
        "body": {"event": "proposed", "proposal": proposal, "verb": verb, "tier": tier,
                 "preview": {"en": f"Refund {proposal}", "ar": "استرداد"}},
    }


def test_await_then_decision_flow() -> None:
    s = _store()
    s.ingest(_proposed(1, proposal="px"), 1)  # the control plane saw the intent
    assert s.decision("px") == "unknown"
    s.await_approval("px")
    assert s.decision("px") == "pending"
    # the pending card is enriched from the proposed event
    p = s.pending()[0]
    assert p["proposal_id"] == "px" and p["verb"] == "commerce.process_refund" and p["tier"] == "HIGH"
    assert s.decide("px", "approved", actor="owner") is True
    assert s.decision("px") == "approved"
    assert s.pending() == []


def test_decide_only_transitions_pending() -> None:
    s = _store()
    s.await_approval("py")
    assert s.decide("py", "rejected") is True
    assert s.decide("py", "approved") is False  # already decided → no-op
    assert s.decision("py") == "rejected"


def test_await_is_idempotent() -> None:
    s = _store()
    s.await_approval("pz")
    s.decide("pz", "approved")
    s.await_approval("pz")  # must not reset an approved decision
    assert s.decision("pz") == "approved"


def test_approval_endpoints() -> None:
    s = _store()
    s.ingest(_proposed(1, proposal="pe", verb="commerce.create_product", tier="HIGH"), 1)
    client = TestClient(create_app(s, secret=""))
    assert client.post("/proposals/pe/await").json()["status"] == "pending"
    assert client.get("/proposals/pe/decision").json()["status"] == "pending"
    assert client.get("/api/pending").json()["pending"][0]["proposal_id"] == "pe"
    bad = client.post("/proposals/pe/decision", json={"status": "maybe"})
    assert bad.status_code == 400
    ok = client.post("/proposals/pe/decision", json={"status": "approved", "actor": "me"})
    assert ok.json()["status"] == "approved"
    assert client.get("/proposals/pe/decision").json()["status"] == "approved"
    assert client.get("/api/pending").json()["pending"] == []
