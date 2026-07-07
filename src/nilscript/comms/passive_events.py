"""Wave 7: Passive Thread Events — inbound messages → deterministic events that resume threads.

A CommunicationReceivedEvent is the deterministic, idempotent envelope that transitions an inbound
message into the business thread's timeline and resumes any parked `wait_for_event` nodes waiting
for communication.

Design principle: Events are immutable, ledger-backed, and carry full provenance (correlation_id,
matched_on layer, rendered timeline entry). The thread resumes ONLY when an event matches its
parked criteria and is committed to the ledger.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from nilscript.kernel.models import DslModel


class CommunicationReceivedEvent(BaseModel):
    """Event: a message arrived and matched to a thread.

    This is the canonical, ledger-backed event. Once committed, it DETERMINISTICALLY resumes
    any parked `wait_for_event(mail.received)` or equivalent nodes on the thread.

    Note: Uses BaseModel (not DslModel) to allow mutation after creation.
    """

    event_id: str  # UUID, unique across all events
    thread_id: str | None = None  # Business thread ID (None for ambiguous events until resolved)
    run_id: str | None = None  # Control-plane run_id (if available)
    correlation_id: str  # The correlation_id from CorrelationEngine.correlate()

    # Full message metadata
    message: dict = Field(
        default_factory=dict,
        description="Full message dict: {sender, body, timestamp, channel, subject, attachments, ...}",
    )

    # Correlation metadata
    matched_on: str  # Which layer matched? (L1_TRANSPORT, L2_CONVERSATION, etc.)
    confidence: float = Field(ge=0.0, le=1.0)  # Confidence of the match (0.0-1.0)
    layers_matched: list[str] = Field(default_factory=list)  # Layers that matched, in order

    # Thread state at reception
    thread_state_before: str  # Thread state before resumption (e.g., "waiting_for_email")

    # Rendered timeline entry (for the thread case-file UI)
    rendered_as: dict = Field(
        default_factory=dict,
        description="{type: 'inbound_message', sender: '...', body: '...', timestamp: '...', avatar: '...'}",
    )

    # Ledger metadata
    received_at: str  # ISO timestamp when the event was created
    source: Literal["email", "whatsapp", "sms", "webhook"] = "email"  # Which channel

    # Governance
    tier: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "LOW"
    requires_approval: bool = False

    # Verification
    signed: bool = False  # If true, this event has been cryptographically signed (for audit)
    signature: str | None = None  # HMAC-SHA256 or equivalent


class MessageInbox(DslModel):
    """A message waiting to enter the ledger — pre-committed state."""

    message_id: str  # UUID
    thread_id: str | None = None  # May be None if correlation is ambiguous
    sender: str  # Email, phone, WhatsApp ID, etc.
    body: str
    subject: str | None = None  # Email subject
    channel: Literal["email", "whatsapp", "sms", "webhook"]
    received_at: str  # ISO timestamp
    raw_message: dict | None = None  # Full message object (for debugging)
    correlation_id: str | None = None  # From CorrelationEngine
    matched_on: str | None = None
    confidence: float = 0.0
    requires_review: bool = False  # If correlation was ambiguous


def create_passive_resume_event(
    message: dict, thread_id: str, correlation_result: Any, thread_state_before: str = "running"
) -> CommunicationReceivedEvent:
    """Inbound message + correlation result → deterministic resume event.

    This factory function creates a CommunicationReceivedEvent that will:
    1. Be written to the ledger (immutable)
    2. Resume any parked wait_for_event nodes on the thread
    3. Appear in the thread's case-file timeline

    Args:
        message: The inbound message dict (sender, body, subject, timestamp, channel, attachments)
        thread_id: The matched thread_id
        correlation_result: The CorrelationResult from correlation_engine.correlate()
        thread_state_before: The thread's state before this event resumes it

    Returns:
        CommunicationReceivedEvent ready for ledger commit
    """
    event_id = str(uuid.uuid4())

    # Extract message metadata
    sender = message.get("sender", "unknown")
    body = message.get("body", "")
    subject = message.get("subject", "")
    channel = message.get("channel", "email")
    received_at = message.get("received_at", datetime.utcnow().isoformat())

    # Build timeline entry
    rendered = {
        "type": "inbound_message",
        "sender": sender,
        "sender_avatar": message.get("sender_avatar"),
        "body": body,
        "subject": subject,
        "timestamp": received_at,
        "channel": channel,
        "attachments": message.get("attachments", []),
    }

    return CommunicationReceivedEvent(
        event_id=event_id,
        thread_id=thread_id,
        run_id=correlation_result.get("run_id"),
        correlation_id=correlation_result.get("correlation_id"),
        message=message,
        matched_on=correlation_result.get("matched_on"),
        confidence=correlation_result.get("confidence", 0.0),
        layers_matched=correlation_result.get("layers_matched", []),
        thread_state_before=thread_state_before,
        rendered_as=rendered,
        received_at=received_at,
        source=channel,
        tier="LOW",  # By default; escalate in governance layer if needed
        requires_approval=False,
    )


def create_ambiguous_resume_event(
    message: dict,
    ambiguous_correlation_result: Any,
    thread_state_before: str = "running",
) -> CommunicationReceivedEvent:
    """Handle ambiguous correlation by creating a pendable event.

    When correlation is ambiguous, the event is created but requires human review before
    it can resume any thread. The thread_id is None until resolved.

    Args:
        message: The inbound message dict
        ambiguous_correlation_result: The AmbiguousCorrelationResult from correlation_engine
        thread_state_before: The thread's state (if known)

    Returns:
        CommunicationReceivedEvent with requires_review=True and thread_id=None
    """
    event_id = str(uuid.uuid4())

    sender = message.get("sender", "unknown")
    body = message.get("body", "")
    subject = message.get("subject", "")
    channel = message.get("channel", "email")
    received_at = message.get("received_at", datetime.utcnow().isoformat())

    rendered = {
        "type": "inbound_message_ambiguous",
        "sender": sender,
        "body": body,
        "subject": subject,
        "timestamp": received_at,
        "channel": channel,
        "candidates": [c.get("business_ref") for c in ambiguous_correlation_result.get("candidates", [])],
    }

    # The event has no thread_id until the human picks one via review_queue.resolve()
    return CommunicationReceivedEvent(
        event_id=event_id,
        thread_id=None,  # Will be set after human review
        correlation_id=ambiguous_correlation_result.get("correlation_id"),
        message=message,
        matched_on="AMBIGUOUS",
        confidence=0.0,
        layers_matched=[],
        thread_state_before=thread_state_before,
        rendered_as=rendered,
        received_at=received_at,
        source=channel,
        tier="MEDIUM",  # Requires human attention
        requires_approval=True,
    )


class PassiveEventStore:
    """In-memory store for pending communication events (pre-ledger).

    In production, this would be backed by the control-plane's parked_runs table
    and the events ledger. For now, this is a simple in-memory store for testing.
    """

    def __init__(self):
        self.inbox: dict[str, MessageInbox] = {}  # message_id -> MessageInbox
        self.events: dict[str, CommunicationReceivedEvent] = {}  # event_id -> Event
        self.by_thread: dict[str, list[str]] = {}  # thread_id -> [event_ids]
        self.unmatched: dict[str, MessageInbox] = {}  # Waiting for correlation

    def add_inbox_message(self, message: MessageInbox) -> str:
        """Add an inbound message to the inbox (pre-correlation)."""
        self.inbox[message.message_id] = message
        if message.requires_review:
            self.unmatched[message.message_id] = message
        return message.message_id

    def add_event(self, event: CommunicationReceivedEvent) -> str:
        """Add a correlated event (post-correlation, pre-ledger)."""
        if event.thread_id:
            if event.thread_id not in self.by_thread:
                self.by_thread[event.thread_id] = []
            self.by_thread[event.thread_id].append(event.event_id)
        self.events[event.event_id] = event
        return event.event_id

    def get_events_for_thread(self, thread_id: str) -> list[CommunicationReceivedEvent]:
        """Get all communication events for a thread, in received order."""
        event_ids = self.by_thread.get(thread_id, [])
        return [self.events[eid] for eid in event_ids if eid in self.events]

    def get_unmatched_messages(self) -> list[MessageInbox]:
        """Get all messages waiting for correlation/review."""
        return list(self.unmatched.values())

    def resolve_ambiguous_message(
        self, message_id: str, chosen_thread_id: str
    ) -> CommunicationReceivedEvent | None:
        """After human review, resolve an ambiguous message to a thread.

        Args:
            message_id: The MessageInbox message_id
            chosen_thread_id: The thread_id the human selected

        Returns:
            The CommunicationReceivedEvent that will resume the thread
        """
        inbox_msg = self.inbox.get(message_id)
        if not inbox_msg:
            return None

        # Remove from unmatched
        if message_id in self.unmatched:
            del self.unmatched[message_id]

        # Create a resolved event
        message_dict = {
            "sender": inbox_msg.sender,
            "body": inbox_msg.body,
            "subject": inbox_msg.subject,
            "channel": inbox_msg.channel,
            "received_at": inbox_msg.received_at,
        }

        event = CommunicationReceivedEvent(
            event_id=str(uuid.uuid4()),
            thread_id=chosen_thread_id,
            correlation_id=inbox_msg.correlation_id or str(uuid.uuid4()),
            message=message_dict,
            matched_on="HUMAN_REVIEW",
            confidence=1.0,
            layers_matched=[],
            thread_state_before="running",
            rendered_as={
                "type": "inbound_message",
                "sender": inbox_msg.sender,
                "body": inbox_msg.body,
                "subject": inbox_msg.subject,
                "timestamp": inbox_msg.received_at,
                "channel": inbox_msg.channel,
            },
            received_at=inbox_msg.received_at,
            source=inbox_msg.channel,
            tier="LOW",
        )

        self.add_event(event)
        return event


# Shorthand factory functions for common scenarios
def event_from_email(
    sender: str, subject: str, body: str, thread_id: str, correlation_result: dict
) -> CommunicationReceivedEvent:
    """Factory for email-channel events."""
    return create_passive_resume_event(
        {
            "sender": sender,
            "subject": subject,
            "body": body,
            "channel": "email",
            "received_at": datetime.utcnow().isoformat(),
        },
        thread_id,
        correlation_result,
    )


def event_from_whatsapp(
    sender_name: str, body: str, thread_id: str, correlation_result: dict
) -> CommunicationReceivedEvent:
    """Factory for WhatsApp-channel events."""
    return create_passive_resume_event(
        {
            "sender": sender_name,
            "body": body,
            "channel": "whatsapp",
            "received_at": datetime.utcnow().isoformat(),
        },
        thread_id,
        correlation_result,
    )


def event_from_sms(
    sender_phone: str, body: str, thread_id: str, correlation_result: dict
) -> CommunicationReceivedEvent:
    """Factory for SMS-channel events."""
    return create_passive_resume_event(
        {
            "sender": sender_phone,
            "body": body,
            "channel": "sms",
            "received_at": datetime.utcnow().isoformat(),
        },
        thread_id,
        correlation_result,
    )
