"""Wave 7: Communication Engine — correlation, passive events, review queue, governance.

This module implements the 5-layer correlation cascade for routing inbound messages to Business
Threads, passive thread eventing for message-driven thread resumption, review queue for ambiguous
correlations, and outbound governance for sending.

Public API:
  - CorrelationEngine: Route inbound messages to threads (5-layer cascade)
  - CommunicationReceivedEvent: Ledger-backed inbound event
  - ReviewQueue: Manage ambiguous correlations
  - OutboundGovernance: Route outbound messages by governance tier
"""

from nilscript.comms.correlation_engine import (
    CorrelationEngine,
    CorrelationResult,
    AmbiguousCorrelationResult,
    TransportMarker,
    ConversationIdentity,
    BusinessKey,
    ParticipantInfo,
    ThreadState,
)
from nilscript.comms.passive_events import (
    CommunicationReceivedEvent,
    MessageInbox,
    PassiveEventStore,
    create_passive_resume_event,
    create_ambiguous_resume_event,
    event_from_email,
    event_from_whatsapp,
    event_from_sms,
)
from nilscript.comms.review_queue import (
    ReviewQueue,
    ReviewQueueItem,
    ReviewQueueAPI,
    pending_reviews_for_display,
)
from nilscript.comms.outbound_governance import (
    OutboundMessage,
    OutboundGovernance,
    OutboundRoute,
    CommitOutboundMessage,
    OutboundApprovalCard,
    outbound_to_approval_card,
)

__all__ = [
    # Correlation
    "CorrelationEngine",
    "CorrelationResult",
    "AmbiguousCorrelationResult",
    "TransportMarker",
    "ConversationIdentity",
    "BusinessKey",
    "ParticipantInfo",
    "ThreadState",
    # Passive Events
    "CommunicationReceivedEvent",
    "MessageInbox",
    "PassiveEventStore",
    "create_passive_resume_event",
    "create_ambiguous_resume_event",
    "event_from_email",
    "event_from_whatsapp",
    "event_from_sms",
    # Review Queue
    "ReviewQueue",
    "ReviewQueueItem",
    "ReviewQueueAPI",
    "pending_reviews_for_display",
    # Outbound Governance
    "OutboundMessage",
    "OutboundGovernance",
    "OutboundRoute",
    "CommitOutboundMessage",
    "OutboundApprovalCard",
    "outbound_to_approval_card",
]
