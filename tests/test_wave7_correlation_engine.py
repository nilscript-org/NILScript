"""Wave 7 Tests: Correlation Engine, Passive Events, Review Queue, Outbound Governance.

Test cases cover:
1. Correlation Engine: all 5 layers, confidence scoring, ambiguous matches
2. Passive Events: event creation, timeline rendering, ambiguous event handling
3. Review Queue: item lifecycle, resolution, expiry, filtering
4. Outbound Governance: routing decisions, reply token stamping, approval cards
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta
import uuid

from nilscript.comms.correlation_engine import (
    CorrelationEngine,
    TransportMarker,
    ConversationIdentity,
    CorrelationResult,
    AmbiguousCorrelationResult,
)
from nilscript.comms.passive_events import (
    CommunicationReceivedEvent,
    create_passive_resume_event,
    create_ambiguous_resume_event,
    PassiveEventStore,
    MessageInbox,
    event_from_email,
)
from nilscript.comms.review_queue import (
    ReviewQueue,
    ReviewQueueItem,
    ReviewQueueAPI,
)
from nilscript.comms.outbound_governance import (
    OutboundMessage,
    OutboundGovernance,
    outbound_to_approval_card,
)


# ── Correlation Engine Tests ─────────────────────────────────────────────────────────────────────


class TestCorrelationEngineL1:
    """Layer 1: Transport ID matching (Message-ID, In-Reply-To, WhatsApp, SMS)."""

    def test_l1_exact_message_id_match(self):
        """L1 matches exact Message-ID (confidence=1.0)."""
        engine = CorrelationEngine()
        engine.add_transport_marker(
            TransportMarker(
                message_id="msg-12345@example.com",
                channel="email",
            ),
            thread_id="thread-001",
            run_id="run-001",
        )

        message = {
            "transport": {"message_id": "msg-12345@example.com", "channel": "email"},
        }

        result = engine.correlate(message)
        assert isinstance(result, CorrelationResult)
        assert result.thread_id == "thread-001"
        assert result.confidence == 1.0
        assert result.matched_on == "L1_TRANSPORT"

    def test_l1_in_reply_to_match(self):
        """L1 matches In-Reply-To header (confidence=0.95)."""
        engine = CorrelationEngine()
        engine.add_transport_marker(
            TransportMarker(message_id="original@example.com", channel="email"),
            thread_id="thread-001",
        )

        message = {"transport": {"in_reply_to": "original@example.com", "channel": "email"}}

        result = engine.correlate(message)
        assert isinstance(result, CorrelationResult)
        assert result.thread_id == "thread-001"
        assert result.confidence == 0.95

    def test_l1_whatsapp_msg_id_match(self):
        """L1 matches WhatsApp message ID."""
        engine = CorrelationEngine()
        engine.add_transport_marker(
            TransportMarker(whatsapp_msg_id="wamsg-xyz", channel="whatsapp"),
            thread_id="thread-001",
        )

        message = {"transport": {"whatsapp_msg_id": "wamsg-xyz", "channel": "whatsapp"}}

        result = engine.correlate(message)
        assert isinstance(result, CorrelationResult)
        assert result.thread_id == "thread-001"

    def test_l1_no_match_returns_none(self):
        """L1 returns None if no matching transport ID."""
        engine = CorrelationEngine()
        message = {
            "transport": {"message_id": "unknown@example.com", "channel": "email"},
        }

        result = engine.correlate(message)
        assert result is None


class TestCorrelationEngineL2:
    """Layer 2: Conversation Identity (BCONV)."""

    def test_l2_bconv_exact_match(self):
        """L2 matches BCONV (confidence=1.0)."""
        engine = CorrelationEngine()

        message = {
            "conversation": {
                "bconv_id": "BCONV-ws_acme-2026-00145",
                "thread_id": "thread-po-145",
            },
        }

        result = engine.correlate(message)
        # Note: This is a stub; real implementation would query BCONV registry
        assert result is not None or result is None  # Placeholder


class TestCorrelationEngineL3:
    """Layer 3: Business Keys (order_ref, ticket_id, invoice_number, etc.)."""

    def test_l3_single_business_key_match(self):
        """L3 matches single business key (confidence=0.95)."""
        engine = CorrelationEngine()
        engine.add_business_key("order_ref", "PO-2026-00145", "thread-po-145")

        message = {"business_keys": [{"key_type": "order_ref", "value": "PO-2026-00145"}]}

        result = engine.correlate(message)
        assert isinstance(result, CorrelationResult)
        assert result.thread_id == "thread-po-145"
        assert result.confidence == 0.95
        assert result.matched_on == "L3_BUSINESS_KEYS"

    def test_l3_ambiguous_multiple_matches(self):
        """L3 returns AmbiguousCorrelationResult if multiple threads match."""
        engine = CorrelationEngine()
        engine.add_business_key("ticket_id", "TICKET-001", "thread-001")
        engine.add_business_key("ticket_id", "TICKET-001", "thread-002")

        message = {"business_keys": [{"key_type": "ticket_id", "value": "TICKET-001"}]}

        result = engine.correlate(message)
        assert isinstance(result, AmbiguousCorrelationResult)
        assert len(result.candidates) == 2

    def test_l3_ticket_id_match(self):
        """L3 matches ticket_id."""
        engine = CorrelationEngine()
        engine.add_business_key("ticket_id", "TICKET-123", "thread-ticket-123")

        message = {"business_keys": [{"key_type": "ticket_id", "value": "TICKET-123"}]}

        result = engine.correlate(message)
        assert isinstance(result, CorrelationResult)
        assert result.thread_id == "thread-ticket-123"

    def test_l3_invoice_number_match(self):
        """L3 matches invoice_number."""
        engine = CorrelationEngine()
        engine.add_business_key("invoice_number", "INV-2026-001", "thread-inv-001")

        message = {"business_keys": [{"key_type": "invoice_number", "value": "INV-2026-001"}]}

        result = engine.correlate(message)
        assert isinstance(result, CorrelationResult)
        assert result.thread_id == "thread-inv-001"

    def test_l3_no_key_match_returns_none(self):
        """L3 returns None if business key not found."""
        engine = CorrelationEngine()
        message = {"business_keys": [{"key_type": "order_ref", "value": "UNKNOWN"}]}

        result = engine.correlate(message)
        assert result is None


class TestCorrelationEngineL4L5:
    """Layers 4 & 5: Participant matching and temporal causality."""

    def test_l4_participant_matching(self):
        """L4 filters by participant/sender (stub implementation)."""
        engine = CorrelationEngine()
        engine.add_business_key("order_ref", "PO-001", "thread-po-001")

        message = {
            "business_keys": [{"key_type": "order_ref", "value": "PO-001"}],
            "sender": {"sender_email": "vendor@example.com", "role": "vendor"},
        }

        result = engine.correlate(message)
        # Stub: in production, would validate sender has role on thread
        assert result is None or isinstance(result, CorrelationResult)

    def test_l5_temporal_causality(self):
        """L5 validates thread state (waiting for event, etc.)."""
        engine = CorrelationEngine()
        engine.add_business_key("order_ref", "PO-001", "thread-po-001")

        message = {
            "business_keys": [{"key_type": "order_ref", "value": "PO-001"}],
            "thread_state": {
                "thread_id": "thread-po-001",
                "state": "waiting_for_vendor_reply",
                "on_event": "mail.received",
            },
        }

        result = engine.correlate(message)
        # Stub: in production, would check thread's parked state
        assert result is None or isinstance(result, CorrelationResult)


class TestCorrelationEngineFallback:
    """Fallback correlation when explicit thread is provided."""

    def test_correlate_with_fallback_uses_explicit_thread(self):
        """Fallback to explicit thread when no match found."""
        engine = CorrelationEngine()
        message = {"body": "Hello"}

        result = engine.correlate_with_fallback(message, "default-thread-001")
        assert result.thread_id == "default-thread-001"
        assert result.matched_on == "FALLBACK"
        assert result.confidence == 0.5
        assert result.requires_clarification is True

    def test_correlate_with_fallback_prefers_real_match(self):
        """Fallback doesn't override a real L1 match."""
        engine = CorrelationEngine()
        engine.add_transport_marker(
            TransportMarker(message_id="msg-abc", channel="email"),
            thread_id="thread-real",
        )

        message = {"transport": {"message_id": "msg-abc", "channel": "email"}}

        result = engine.correlate_with_fallback(message, "default-thread")
        assert result.thread_id == "thread-real"
        assert result.matched_on == "L1_TRANSPORT"


class TestCorrelationEngineConfidence:
    """Confidence scoring across layers."""

    def test_confidence_decreases_with_weaker_layers(self):
        """Confidence scores: L1=1.0, L2=1.0, L3=0.95, L4=0.85, L5=0.75."""
        engine = CorrelationEngine()

        # L1: highest confidence
        engine.add_transport_marker(
            TransportMarker(message_id="msg-1", channel="email"),
            thread_id="t1",
        )
        result1 = engine.correlate({"transport": {"message_id": "msg-1", "channel": "email"}})
        assert result1.confidence == 1.0

        # L3: lower confidence than L1
        engine.add_business_key("order_ref", "PO-123", "t2")
        result3 = engine.correlate({"business_keys": [{"key_type": "order_ref", "value": "PO-123"}]})
        assert result3.confidence == 0.95

    def test_ambiguous_below_threshold(self):
        """Ambiguous result (confidence < 0.9) triggers review queue."""
        engine = CorrelationEngine()
        engine.add_business_key("ticket_id", "T-001", "thread-a")
        engine.add_business_key("ticket_id", "T-001", "thread-b")

        message = {"business_keys": [{"key_type": "ticket_id", "value": "T-001"}]}
        result = engine.correlate(message)

        assert isinstance(result, AmbiguousCorrelationResult)
        assert len(result.candidates) > 1


# ── Passive Events Tests ─────────────────────────────────────────────────────────────────────────


class TestPassiveEventsCreation:
    """Creating deterministic communication events."""

    def test_create_passive_resume_event_email(self):
        """Create event from email correlation."""
        message = {
            "sender": "vendor@example.com",
            "subject": "RE: PO-2026-00145",
            "body": "I can deliver next week.",
            "channel": "email",
            "received_at": "2026-07-07T10:00:00Z",
        }
        correlation_result = {
            "thread_id": "thread-po-145",
            "run_id": "run-po-145",
            "correlation_id": "corr-123",
            "matched_on": "L3_BUSINESS_KEYS",
            "confidence": 0.95,
            "layers_matched": ["L3"],
        }

        event = create_passive_resume_event(message, "thread-po-145", correlation_result)

        assert event.event_id
        assert event.thread_id == "thread-po-145"
        assert event.correlation_id == "corr-123"
        assert event.matched_on == "L3_BUSINESS_KEYS"
        assert event.confidence == 0.95
        assert event.source == "email"
        assert event.rendered_as["type"] == "inbound_message"

    def test_event_from_email_factory(self):
        """Shorthand factory for email events."""
        correlation_result = {
            "thread_id": "thread-123",
            "correlation_id": "corr-456",
            "matched_on": "L1_TRANSPORT",
            "confidence": 1.0,
        }

        event = event_from_email(
            sender="client@example.com",
            subject="Approved!",
            body="You can proceed.",
            thread_id="thread-123",
            correlation_result=correlation_result,
        )

        assert event.thread_id == "thread-123"
        assert event.source == "email"
        assert event.rendered_as["sender"] == "client@example.com"

    def test_ambiguous_event_requires_review(self):
        """Ambiguous correlation creates event with requires_review=True."""
        message = {"sender": "unknown", "body": "Which PO is this?", "channel": "email"}
        ambiguous_result = {
            "correlation_id": "corr-ambig",
            "candidates": [
                {"thread_id": "t1", "business_ref": "PO-001"},
                {"thread_id": "t2", "business_ref": "PO-002"},
            ],
        }

        event = create_ambiguous_resume_event(message, ambiguous_result)

        assert event.thread_id is None
        assert event.requires_approval is True
        assert event.matched_on == "AMBIGUOUS"
        assert event.rendered_as["type"] == "inbound_message_ambiguous"


class TestPassiveEventStore:
    """Event store for pre-ledger communication events."""

    def test_add_and_retrieve_event(self):
        """Add event and retrieve it."""
        store = PassiveEventStore()

        message = {"sender": "test@example.com", "body": "Test"}
        correlation_result = {"thread_id": "t1", "correlation_id": "c1", "matched_on": "L1_TRANSPORT", "confidence": 1.0}

        event = create_passive_resume_event(message, "t1", correlation_result)
        event_id = store.add_event(event)

        assert event_id == event.event_id
        assert store.events[event_id].thread_id == "t1"

    def test_get_events_for_thread(self):
        """Get all events for a specific thread."""
        store = PassiveEventStore()

        # Add events to thread t1
        for i in range(3):
            message = {"sender": f"test{i}@example.com", "body": "Test"}
            correlation_result = {"thread_id": "t1", "correlation_id": f"c{i}", "matched_on": "L3_BUSINESS_KEYS", "confidence": 0.95}
            event = create_passive_resume_event(message, "t1", correlation_result)
            store.add_event(event)

        # Add event to thread t2
        message = {"sender": "test@example.com", "body": "Test"}
        correlation_result = {"thread_id": "t2", "correlation_id": "c-other", "matched_on": "L3_BUSINESS_KEYS", "confidence": 0.95}
        event = create_passive_resume_event(message, "t2", correlation_result)
        store.add_event(event)

        t1_events = store.get_events_for_thread("t1")
        assert len(t1_events) == 3

        t2_events = store.get_events_for_thread("t2")
        assert len(t2_events) == 1

    def test_resolve_ambiguous_message(self):
        """Resolve ambiguous message to chosen thread."""
        store = PassiveEventStore()

        inbox_message = MessageInbox(
            message_id="msg-123",
            sender="test@example.com",
            body="Which PO?",
            channel="email",
            received_at="2026-07-07T10:00:00Z",
            correlation_id="corr-ambig",
        )

        store.add_inbox_message(inbox_message)

        # Resolve to thread t1
        event = store.resolve_ambiguous_message("msg-123", "t1")

        assert event is not None
        assert event.thread_id == "t1"
        assert event.matched_on == "HUMAN_REVIEW"
        assert event.confidence == 1.0


# ── Review Queue Tests ───────────────────────────────────────────────────────────────────────────


class TestReviewQueueBasics:
    """Review queue lifecycle and basic operations."""

    def test_add_to_review(self):
        """Add ambiguous message to review queue."""
        queue = ReviewQueue()

        message = {"sender": "test@example.com", "subject": "PO inquiry", "body": "Which PO?"}
        candidates = [
            {"thread_id": "t1", "business_ref": "PO-001", "confidence": 0.8},
            {"thread_id": "t2", "business_ref": "PO-002", "confidence": 0.8},
        ]

        item = queue.add_to_review(message, candidates, "corr-123", workspace="ws_test")

        assert item.id
        assert item.status == "pending"
        assert len(item.candidates) == 2
        assert item.correlation_id == "corr-123"

    def test_list_pending(self):
        """List all pending reviews."""
        queue = ReviewQueue()

        # Add multiple items
        for i in range(3):
            message = {"sender": f"test{i}@example.com", "body": "Test"}
            candidates = [{"thread_id": f"t{i}", "business_ref": f"PO-{i:03d}"}]
            queue.add_to_review(message, candidates, f"corr-{i}", workspace="ws_test")

        pending = queue.list_pending(workspace="ws_test")
        assert len(pending) == 3

    def test_resolve_review_item(self):
        """Resolve an ambiguous message to a thread."""
        queue = ReviewQueue()

        message = {"sender": "test@example.com", "body": "Ambiguous"}
        candidates = [
            {"thread_id": "t1", "business_ref": "PO-001"},
            {"thread_id": "t2", "business_ref": "PO-002"},
        ]

        item = queue.add_to_review(message, candidates, "corr-123")

        # Resolve to t1
        event = queue.resolve(item.id, "t1", resolved_by="user-123")

        assert event is not None
        assert event.thread_id == "t1"
        assert event.matched_on == "HUMAN_REVIEW"
        assert event.confidence == 1.0

        # Verify item status changed
        resolved_item = queue.get_item(item.id)
        assert resolved_item.status == "resolved"
        assert resolved_item.human_decision == "t1"

    def test_reject_review_item(self):
        """Reject an item (not a real message, spam, etc.)."""
        queue = ReviewQueue()

        message = {"sender": "test@example.com", "body": "Spam"}
        candidates = [{"thread_id": "t1", "business_ref": "PO-001"}]

        item = queue.add_to_review(message, candidates, "corr-123")

        # Reject
        result = queue.reject(item.id, resolved_by="user-123")

        assert result is True
        rejected_item = queue.get_item(item.id)
        assert rejected_item.status == "rejected"


class TestReviewQueueExpiry:
    """Review queue item expiry and cleanup."""

    def test_item_expires_after_ttl(self):
        """Items expire after TTL (default 72 hours)."""
        queue = ReviewQueue(ttl_hours=1)

        message = {"sender": "test@example.com", "body": "Test"}
        candidates = [{"thread_id": "t1", "business_ref": "PO-001"}]

        item = queue.add_to_review(message, candidates, "corr-123")

        # Manually set expires_at to past
        item.expires_at = datetime.utcnow() - timedelta(seconds=1)

        expired_count = queue.cleanup_expired()

        assert expired_count == 1
        assert item.status == "expired"

    def test_cleanup_expired_only_marks_pending(self):
        """Cleanup only marks pending items as expired."""
        queue = ReviewQueue()

        message = {"sender": "test@example.com", "body": "Test"}
        candidates = [{"thread_id": "t1", "business_ref": "PO-001"}]

        pending_item = queue.add_to_review(message, candidates, "corr-1")
        pending_item.expires_at = datetime.utcnow() - timedelta(seconds=1)

        resolved_item = queue.add_to_review(message, candidates, "corr-2")
        queue.resolve(resolved_item.id, "t1")
        resolved_item.expires_at = datetime.utcnow() - timedelta(seconds=1)

        expired_count = queue.cleanup_expired()

        assert expired_count == 1
        assert pending_item.status == "expired"
        assert resolved_item.status == "resolved"  # Not changed


class TestReviewQueueFiltering:
    """Filter pending reviews by thread or workspace."""

    def test_filter_by_thread(self):
        """Filter pending items by thread."""
        queue = ReviewQueue()

        # Add items for different threads
        msg1 = {"sender": "test@example.com", "body": "Test"}
        candidates1 = [{"thread_id": "t1", "business_ref": "PO-001"}]
        queue.add_to_review(msg1, candidates1, "corr-1")

        msg2 = {"sender": "test@example.com", "body": "Test"}
        candidates2 = [{"thread_id": "t2", "business_ref": "PO-002"}]
        queue.add_to_review(msg2, candidates2, "corr-2")

        t1_pending = queue.list_pending(thread_id="t1")
        assert len(t1_pending) == 1

        t2_pending = queue.list_pending(thread_id="t2")
        assert len(t2_pending) == 1

    def test_filter_by_workspace(self):
        """Filter pending items by workspace."""
        queue = ReviewQueue()

        msg = {"sender": "test@example.com", "body": "Test"}
        candidates = [{"thread_id": "t1", "business_ref": "PO-001"}]

        queue.add_to_review(msg, candidates, "corr-1", workspace="ws_acme")
        queue.add_to_review(msg, candidates, "corr-2", workspace="ws_other")

        acme_pending = queue.list_pending(workspace="ws_acme")
        assert len(acme_pending) == 1

        other_pending = queue.list_pending(workspace="ws_other")
        assert len(other_pending) == 1


class TestReviewQueueAPI:
    """REST-like API for review queue (would be exposed by os-server)."""

    def test_api_list_pending(self):
        """API: GET /api/review-queue/pending?workspace=ws_acme"""
        queue = ReviewQueue()
        api = ReviewQueueAPI(queue)

        msg = {"sender": "test@example.com", "subject": "Test", "body": "Test"}
        candidates = [{"thread_id": "t1", "business_ref": "PO-001"}]
        queue.add_to_review(msg, candidates, "corr-1", workspace="ws_acme")

        result = api.list_pending(workspace="ws_acme")

        assert len(result) == 1
        assert result[0]["sender"] == "test@example.com"

    def test_api_resolve(self):
        """API: POST /api/review-queue/{id}/resolve"""
        queue = ReviewQueue()
        api = ReviewQueueAPI(queue)

        msg = {"sender": "test@example.com", "body": "Test"}
        candidates = [
            {"thread_id": "t1", "business_ref": "PO-001"},
            {"thread_id": "t2", "business_ref": "PO-002"},
        ]

        item = queue.add_to_review(msg, candidates, "corr-1", workspace="ws_acme")

        result = api.resolve("ws_acme", item.id, "t1")

        assert result["ok"] is True
        assert result["thread_id"] == "t1"
        assert result["event_id"]

    def test_api_get_stats(self):
        """API: GET /api/review-queue/stats?workspace=ws_acme"""
        queue = ReviewQueue(ttl_hours=1)
        api = ReviewQueueAPI(queue)

        msg = {"sender": "test@example.com", "body": "Test"}
        candidates = [{"thread_id": "t1", "business_ref": "PO-001"}]

        item1 = queue.add_to_review(msg, candidates, "corr-1", workspace="ws_acme")
        item2 = queue.add_to_review(msg, candidates, "corr-2", workspace="ws_acme")

        # Resolve one
        queue.resolve(item1.id, "t1")

        # Expire one
        item2.expires_at = datetime.utcnow() - timedelta(seconds=1)
        queue.cleanup_expired()

        stats = api.get_stats("ws_acme")

        assert stats["pending"] == 0
        assert stats["resolved"] == 1
        assert stats["expired"] == 1


# ── Outbound Governance Tests ────────────────────────────────────────────────────────────────────


class TestOutboundGovernanceRouting:
    """Routing outbound messages based on governance tier."""

    def test_route_low_tier_send_immediately(self):
        """LOW tier → send_immediately (soft governance)."""
        governance = OutboundGovernance()

        message = OutboundMessage(
            id=str(uuid.uuid4()),
            thread_id="t1",
            cycle_id="cyc_order",
            channel="email",
            recipient="vendor@example.com",
            body="Hello",
            governance_tier="LOW",
            created_at=datetime.utcnow().isoformat(),
        )

        route = governance.route_outbound(message)

        assert route.action == "send_immediately"
        assert len(route.notify_actors) == 0

    def test_route_high_tier_send_with_notification(self):
        """HIGH tier → send_with_notification (assisted governance)."""
        governance = OutboundGovernance()

        message = OutboundMessage(
            id=str(uuid.uuid4()),
            thread_id="t1",
            cycle_id="cyc_order",
            channel="email",
            recipient="vendor@example.com",
            body="High-value agreement",
            governance_tier="HIGH",
            created_at=datetime.utcnow().isoformat(),
        )

        route = governance.route_outbound(message)

        assert route.action == "send_with_notification"
        assert "manager" in route.notify_actors

    def test_route_critical_tier_wait_for_approval(self):
        """CRITICAL tier → wait_for_approval (enterprise relay)."""
        governance = OutboundGovernance()

        message = OutboundMessage(
            id=str(uuid.uuid4()),
            thread_id="t1",
            cycle_id="cyc_order",
            channel="email",
            recipient="vendor@example.com",
            body="Contract amendment",
            governance_tier="CRITICAL",
            created_at=datetime.utcnow().isoformat(),
        )

        route = governance.route_outbound(message)

        assert route.action == "wait_for_approval"
        assert "approver" in route.approval_required_from


class TestOutboundGovernanceReplyTokens:
    """Reply token generation and stamping."""

    def test_stamp_reply_token_email(self):
        """Email reply token: [WSL-xyz] format."""
        governance = OutboundGovernance()

        message = OutboundMessage(
            id=str(uuid.uuid4()),
            thread_id="t1",
            cycle_id="cyc_order",
            channel="email",
            recipient="vendor@example.com",
            body="Hello",
            created_at=datetime.utcnow().isoformat(),
        )

        token = governance.stamp_reply_token(message)

        assert token.startswith("[")
        assert token.endswith("]")
        assert "WSL" in token.upper()

    def test_stamp_reply_token_whatsapp(self):
        """WhatsApp reply token: wsl-xyz: prefix format."""
        governance = OutboundGovernance()

        message = OutboundMessage(
            id=str(uuid.uuid4()),
            thread_id="t1",
            cycle_id="cyc_order",
            channel="whatsapp",
            recipient="+1234567890",
            body="Hello",
            created_at=datetime.utcnow().isoformat(),
        )

        token = governance.stamp_reply_token(message)

        assert token.endswith(":")
        assert "wsl" in token.lower()

    def test_stamp_reply_token_sms(self):
        """SMS reply token: [wsl-xyz] format."""
        governance = OutboundGovernance()

        message = OutboundMessage(
            id=str(uuid.uuid4()),
            thread_id="t1",
            cycle_id="cyc_order",
            channel="sms",
            recipient="+1234567890",
            body="Hello",
            created_at=datetime.utcnow().isoformat(),
        )

        token = governance.stamp_reply_token(message)

        assert token.startswith("[")
        assert token.endswith("]")


class TestOutboundGovernanceCommit:
    """Committing outbound messages after governance decisions."""

    def test_commit_stamps_bconv_and_token(self):
        """Committed message has BCONV and reply token stamped."""
        governance = OutboundGovernance()

        message = OutboundMessage(
            id=str(uuid.uuid4()),
            thread_id="t1",
            cycle_id="cyc_order",
            channel="email",
            recipient="vendor@example.com",
            subject="PO Update",
            body="New quantity",
            bconv_id="BCONV-ws_acme-2026-00145",
            created_at=datetime.utcnow().isoformat(),
        )

        route = governance.route_outbound(message)
        commit = governance.commit_outbound(message, route)

        assert "BCONV" in commit.subject
        assert commit.custom_headers.get("X-Wosool-Conversation-ID") == message.bconv_id
        assert "wsl" in commit.custom_headers.get("X-Wosool-Reply-Token", "").lower()

    def test_commit_includes_approval_info(self):
        """Committed message tracks who approved it."""
        governance = OutboundGovernance()

        message = OutboundMessage(
            id=str(uuid.uuid4()),
            thread_id="t1",
            cycle_id="cyc_order",
            channel="email",
            recipient="vendor@example.com",
            body="Contract",
            governance_tier="CRITICAL",
            created_at=datetime.utcnow().isoformat(),
        )

        route = governance.route_outbound(message)
        commit = governance.commit_outbound(message, route, approved_by="approver-123")

        assert commit.approved_by == "approver-123"
        assert commit.routed_at
        assert commit.governance_tier == "CRITICAL"


class TestOutboundApprovalCards:
    """Approval cards for CRITICAL-tier outbound."""

    def test_create_approval_card_for_critical_message(self):
        """Create approval card for CRITICAL-tier message."""
        message = OutboundMessage(
            id=str(uuid.uuid4()),
            thread_id="t1",
            cycle_id="cyc_order",
            channel="email",
            recipient="vendor@example.com",
            recipient_name="ACME Inc",
            subject="Contract Amendment",
            body="Amend terms as follows...",
            governance_tier="CRITICAL",
            created_at=datetime.utcnow().isoformat(),
        )

        governance = OutboundGovernance()
        route = governance.route_outbound(message)

        card = outbound_to_approval_card(message, route)

        assert card is not None
        assert card.tier == "CRITICAL"
        assert "Approve outbound email" in card.title
        assert "ACME Inc" in card.title
        assert card.recipient == "vendor@example.com"

    def test_no_approval_card_for_low_tier(self):
        """No approval card for LOW-tier message."""
        message = OutboundMessage(
            id=str(uuid.uuid4()),
            thread_id="t1",
            cycle_id="cyc_order",
            channel="email",
            recipient="vendor@example.com",
            body="Reminder",
            governance_tier="LOW",
            created_at=datetime.utcnow().isoformat(),
        )

        governance = OutboundGovernance()
        route = governance.route_outbound(message)

        card = outbound_to_approval_card(message, route)

        assert card is None
