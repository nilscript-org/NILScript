"""Wave 7: Correlation Engine — 5-layer cascade to match inbound messages to threads.

The Correlation Engine deterministically routes incoming messages (email, WhatsApp, SMS) to their
originating Business Threads via a 5-layer cascade:

  L1: TRANSPORT IDs (Message-ID, In-Reply-To, WhatsApp msg_id, SMS timestamp)
  L2: CONVERSATION IDENTITY (BCONV / Business Conversation ID)
  L3: BUSINESS KEYS (order_ref, ticket_id, invoice_number)
  L4: PARTICIPANT MATCHING (sender role, authority)
  L5: TEMPORAL CAUSALITY (thread state, action validity)

Design principle: Deterministic routing, high confidence scoring, explicit ambiguity escalation to
review queue. Never guess; ask when uncertain (confidence < 0.9).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, ClassVar

from pydantic import BaseModel, Field

from nilscript.kernel.models import DslModel


class CorrelationLayer:
    """Schema for the 5-layer correlation cascade."""

    L1_TRANSPORT: ClassVar[str] = "transport_ids"
    """L1: Message-ID, In-Reply-To, WhatsApp msg_id, SMS timestamp."""

    L2_CONVERSATION: ClassVar[str] = "conversation_identity"
    """L2: BCONV (Business Conversation ID) — the durable thread marker."""

    L3_BUSINESS_KEYS: ClassVar[str] = "business_keys"
    """L3: order_ref, ticket_id, invoice_number, etc."""

    L4_PARTICIPANTS: ClassVar[str] = "participant_matching"
    """L4: Sender identity, role, authority level."""

    L5_TIME_CAUSALITY: ClassVar[str] = "temporal_causality"
    """L5: Thread state validation, action validity in context."""


class TransportMarker(DslModel):
    """L1: Transport-level identifiers that thread together messages."""

    message_id: str | None = None  # SMTP Message-ID header
    in_reply_to: str | None = None  # SMTP In-Reply-To header
    whatsapp_msg_id: str | None = None  # WhatsApp message identifier
    sms_timestamp: str | None = None  # SMS received timestamp (ISO)
    channel: Literal["email", "whatsapp", "sms", "webhook"]


class ConversationIdentity(DslModel):
    """L2: Business Conversation Identity (BCONV) — the durable thread anchor.

    BCONV is stamped outbound (email subject prefix, WhatsApp message prefix, SMS embed) so return
    messages carry it back. On inbound, presence of BCONV is a perfect match (confidence=1.0).
    """

    bconv_id: str  # e.g., "BCONV-ws_acme-2026-00145"
    workspace: str
    thread_id: str


class BusinessKey(DslModel):
    """L3: Business-level keys (order_ref, invoice_number, ticket_id, etc.)

    Multiple keys can exist on a thread; the cascade matches on ANY key found in the message.
    If N keys exist on different threads, this is ambiguous (escalates to review queue).
    """

    key_type: Literal["order_ref", "ticket_id", "invoice_number", "po_number", "custom"]
    value: str
    thread_id: str | None = None


class ParticipantInfo(DslModel):
    """L4: Sender identity, role, and authority.

    Enables validation that a sender has authority to update/reply on a thread, and helps
    disambiguate when multiple threads have similar business keys.
    """

    sender_email: str | None = None
    sender_whatsapp: str | None = None
    sender_id: str | None = None  # Generic identifier (person_id, contact_id, etc.)
    role: Literal["vendor", "customer", "internal", "approver", "other"] = "other"
    authority_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None


class ThreadState(DslModel):
    """L5: Thread state snapshot for temporal validation.

    Ensures the incoming message makes sense in the thread's current state. E.g., a "vendor
    reply" only matches if thread is in 'waiting_for_vendor' state, not 'completed'.
    """

    thread_id: str
    state: str  # e.g., "running", "waiting_for_approval", "completed"
    parked_node_id: str | None = None  # If parked on a wait_for_event node
    on_event: str | None = None  # The event type the thread is waiting for (e.g., "mail.received")
    match_criteria: dict | None = None  # Shallow field filters for event matching


class CorrelationResult(DslModel):
    """Successful match: incoming message → thread."""

    thread_id: str
    run_id: str | None = None  # Control-plane run_id, if available
    confidence: float = Field(ge=0.0, le=1.0)  # 0.0-1.0 (1.0 = exact, <0.9 = ambiguous)
    matched_on: str  # Which layer made the match? (L1, L2, L3, L4, L5)
    correlation_id: str  # Unique identifier for this correlation (UUID)
    layers_matched: list[str] = Field(default_factory=list)  # All layers that matched, in order
    requires_clarification: bool = False


class AmbiguousCorrelationResult(DslModel):
    """Multiple threads match; ask human."""

    candidates: list[dict] = Field(
        default_factory=list,
        description="[{'thread_id': '...', 'business_ref': 'PO-2026-00145', 'confidence': 0.85}, ...]",
    )
    question: str  # "Which PO is this for? (PO-001 $5k, PO-002 $10k)"
    correlation_id: str  # Unique identifier for this ambiguous match


class CorrelationMatchKind:
    """Classification of the match quality."""

    EXACT: ClassVar[str] = "exact"  # confidence=1.0, single layer or reinforced across layers
    STRONG: ClassVar[str] = "strong"  # confidence>=0.9, multiple layers agree
    WEAK: ClassVar[str] = "weak"  # confidence<0.9, ambiguous or single weak layer


class CorrelationEngine:
    """Deterministic message → thread routing via 5-layer cascade.

    API:
      - correlate(message) -> CorrelationResult | AmbiguousCorrelationResult
      - correlate_with_fallback(message, default_thread_id) -> CorrelationResult
    """

    def __init__(self, transport_index: dict | None = None, business_key_index: dict | None = None):
        """Initialize the engine with optional pre-built indices.

        Args:
            transport_index: Dict mapping transport_id -> thread_id (for L1 dedup)
            business_key_index: Dict mapping (key_type, value) -> [thread_ids] (for L3 lookups)
        """
        self.transport_index = transport_index or {}
        self.business_key_index = business_key_index or {}

    def correlate(
        self, message: dict
    ) -> CorrelationResult | AmbiguousCorrelationResult | None:
        """Match incoming message to a thread via 5-layer cascade.

        Args:
            message: Inbound message dict with:
              - transport: {message_id, in_reply_to, whatsapp_msg_id, sms_timestamp, channel}
              - conversation: {bconv_id} (optional)
              - business_keys: [{key_type, value}, ...] (optional)
              - sender: {sender_email, sender_whatsapp, sender_id, role, authority_level}
              - thread_state: Optional thread state for L5 validation

        Returns:
            CorrelationResult (confident match)
            AmbiguousCorrelationResult (multiple candidates, ask human)
            None (no match found)
        """
        correlation_id = str(uuid.uuid4())
        layers_matched = []

        # L1: Transport IDs
        l1_result = self._match_layer_1_transport(message.get("transport", {}))
        if l1_result:
            layers_matched.append("L1")
            return CorrelationResult(
                thread_id=l1_result["thread_id"],
                run_id=l1_result.get("run_id"),
                confidence=l1_result.get("confidence", 1.0),
                matched_on="L1_TRANSPORT",
                correlation_id=correlation_id,
                layers_matched=layers_matched,
            )

        # L2: Conversation Identity (BCONV)
        l2_result = self._match_layer_2_conversation(message.get("conversation", {}))
        if l2_result:
            layers_matched.append("L2")
            return CorrelationResult(
                thread_id=l2_result["thread_id"],
                run_id=l2_result.get("run_id"),
                confidence=l2_result.get("confidence", 1.0),
                matched_on="L2_CONVERSATION",
                correlation_id=correlation_id,
                layers_matched=layers_matched,
            )

        # L3: Business Keys
        l3_candidates = self._match_layer_3_business_keys(message.get("business_keys", []))
        if l3_candidates:
            layers_matched.append("L3")
            if len(l3_candidates) == 1:
                return CorrelationResult(
                    thread_id=l3_candidates[0]["thread_id"],
                    run_id=l3_candidates[0].get("run_id"),
                    confidence=0.95,
                    matched_on="L3_BUSINESS_KEYS",
                    correlation_id=correlation_id,
                    layers_matched=layers_matched,
                )
            elif len(l3_candidates) > 1:
                # Multiple threads match on L3; escalate to review
                return AmbiguousCorrelationResult(
                    candidates=l3_candidates,
                    question=self._build_disambiguation_question(l3_candidates),
                    correlation_id=correlation_id,
                )

        # L4: Participant Matching (sender validation + role-based filtering)
        l4_candidates = self._match_layer_4_participants(
            message.get("sender", {}), l3_candidates or []
        )
        if l4_candidates:
            layers_matched.append("L4")
            if len(l4_candidates) == 1:
                return CorrelationResult(
                    thread_id=l4_candidates[0]["thread_id"],
                    run_id=l4_candidates[0].get("run_id"),
                    confidence=0.85,
                    matched_on="L4_PARTICIPANTS",
                    correlation_id=correlation_id,
                    layers_matched=layers_matched,
                )
            elif len(l4_candidates) > 1:
                return AmbiguousCorrelationResult(
                    candidates=l4_candidates,
                    question=self._build_disambiguation_question(l4_candidates),
                    correlation_id=correlation_id,
                )

        # L5: Temporal Causality (thread state + event waiting state)
        l5_candidates = self._match_layer_5_temporal(
            message.get("thread_state"), l4_candidates or l3_candidates or []
        )
        if l5_candidates:
            layers_matched.append("L5")
            if len(l5_candidates) == 1:
                return CorrelationResult(
                    thread_id=l5_candidates[0]["thread_id"],
                    run_id=l5_candidates[0].get("run_id"),
                    confidence=0.75,
                    matched_on="L5_TIME_CAUSALITY",
                    correlation_id=correlation_id,
                    layers_matched=layers_matched,
                )
            elif len(l5_candidates) > 1:
                return AmbiguousCorrelationResult(
                    candidates=l5_candidates,
                    question=self._build_disambiguation_question(l5_candidates),
                    correlation_id=correlation_id,
                )

        return None

    def correlate_with_fallback(
        self, message: dict, default_thread_id: str
    ) -> CorrelationResult:
        """Correlate, but fall back to a default thread if no match found.

        Useful for explicit user selection: "Reply to thread X" button, or fallback to thread
        the user was viewing when they sent the message.
        """
        result = self.correlate(message)
        if result is None:
            return CorrelationResult(
                thread_id=default_thread_id,
                confidence=0.5,
                matched_on="FALLBACK",
                correlation_id=str(uuid.uuid4()),
                requires_clarification=True,
            )
        if isinstance(result, AmbiguousCorrelationResult):
            # Still ambiguous even with fallback; human still needs to pick
            return None
        return result

    def _match_layer_1_transport(self, transport: dict) -> dict | None:
        """L1: Match via Message-ID, In-Reply-To, WhatsApp msg_id, SMS timestamp.

        Returns: {thread_id, confidence, run_id} or None
        """
        # Check if this message_id was already seen (perfect dedup)
        if transport.get("message_id"):
            if transport["message_id"] in self.transport_index:
                return {
                    "thread_id": self.transport_index[transport["message_id"]]["thread_id"],
                    "run_id": self.transport_index[transport["message_id"]].get("run_id"),
                    "confidence": 1.0,
                }

        # Check In-Reply-To to find the original message thread
        if transport.get("in_reply_to"):
            if transport["in_reply_to"] in self.transport_index:
                return {
                    "thread_id": self.transport_index[transport["in_reply_to"]]["thread_id"],
                    "run_id": self.transport_index[transport["in_reply_to"]].get("run_id"),
                    "confidence": 0.95,
                }

        # WhatsApp and SMS would follow similar logic with their channel-specific IDs
        if transport.get("whatsapp_msg_id"):
            key = ("whatsapp", transport["whatsapp_msg_id"])
            if key in self.transport_index:
                return {
                    "thread_id": self.transport_index[key]["thread_id"],
                    "run_id": self.transport_index[key].get("run_id"),
                    "confidence": 0.95,
                }

        return None

    def _match_layer_2_conversation(self, conversation: dict) -> dict | None:
        """L2: Match via BCONV (Business Conversation ID).

        BCONV is the canonical, durable thread marker. Presence = perfect match (confidence=1.0).

        Returns: {thread_id, confidence, run_id} or None
        """
        if conversation.get("bconv_id"):
            # In a real system, look up the BCONV in the thread registry
            # For now, this is a stub that would query the control-plane
            # Example: bconv_lookup(conversation["bconv_id"]) -> {thread_id, run_id}
            # Placeholder:
            return {
                "thread_id": conversation.get("thread_id"),
                "run_id": conversation.get("run_id"),
                "confidence": 1.0,
            }
        return None

    def _match_layer_3_business_keys(self, business_keys: list[dict]) -> list[dict]:
        """L3: Match via business keys (order_ref, ticket_id, invoice_number, etc.).

        Returns: List of matching candidates [{thread_id, business_ref, confidence}, ...]
        """
        candidates = []
        for key in business_keys:
            key_type = key.get("key_type")
            value = key.get("value")
            if key_type and value:
                lookup_key = (key_type, value)
                if lookup_key in self.business_key_index:
                    thread_ids = self.business_key_index[lookup_key]
                    for tid in thread_ids:
                        if tid not in [c["thread_id"] for c in candidates]:
                            candidates.append(
                                {
                                    "thread_id": tid,
                                    "business_ref": key.get("business_ref"),
                                    "confidence": 0.95,
                                }
                            )
        return candidates

    def _match_layer_4_participants(
        self, sender: dict, candidate_threads: list[dict]
    ) -> list[dict]:
        """L4: Validate sender and filter by role/authority.

        If candidate_threads is non-empty, filter them by sender validity.
        Otherwise, fall back to an empty list.

        Returns: Filtered list of candidates
        """
        # This is a stub; in production, you'd look up the sender's role on each thread
        # and validate they have permission to reply
        # For now, just pass through candidates (assumes L3 did the filtering)
        if not candidate_threads:
            return []

        # Placeholder: in reality, for each candidate, check if the sender has a valid
        # role on that thread (e.g., vendor is authorized to reply to PO threads)
        # Stub: assume all candidates pass (confidence 0.85)
        return [
            {**c, "confidence": min(0.85, c.get("confidence", 0.95))}
            for c in candidate_threads
        ]

    def _match_layer_5_temporal(
        self, thread_state: dict | None, candidate_threads: list[dict]
    ) -> list[dict]:
        """L5: Validate temporal causality — thread state + event waiting criteria.

        Ensures the message makes sense in the thread's current state.
        E.g., a "vendor reply" only matches if the thread is waiting for vendor input.

        Returns: Validated list of candidates
        """
        if not candidate_threads or not thread_state:
            return candidate_threads

        # Stub: in production, you'd check each candidate's run state in the control-plane:
        # - Is the thread currently parked on a wait_for_event node?
        # - Does the event match the waiting criteria (e.g., on_event="mail.received")?
        # - Is the thread in a state where it expects external input?
        # For now, assume all pass (confidence 0.75)
        return [
            {**c, "confidence": min(0.75, c.get("confidence", 0.95))}
            for c in candidate_threads
        ]

    def _build_disambiguation_question(self, candidates: list[dict]) -> str:
        """Generate a human-friendly question to disambiguate between candidates.

        Args:
            candidates: List of ambiguous candidates with thread_id, business_ref, etc.

        Returns: A question string
        """
        lines = ["Which thread is this message for?"]
        for i, cand in enumerate(candidates, 1):
            business_ref = cand.get("business_ref", cand.get("thread_id"))
            lines.append(f"  {i}. {business_ref}")
        return "\n".join(lines)

    def add_transport_marker(self, marker: TransportMarker, thread_id: str, run_id: str | None = None):
        """Register a transport marker so future replies are deduped.

        Args:
            marker: TransportMarker with message IDs
            thread_id: The thread this marker belongs to
            run_id: Optional control-plane run_id
        """
        if marker.message_id:
            self.transport_index[marker.message_id] = {"thread_id": thread_id, "run_id": run_id}
        if marker.in_reply_to:
            self.transport_index[marker.in_reply_to] = {"thread_id": thread_id, "run_id": run_id}
        if marker.whatsapp_msg_id:
            key = ("whatsapp", marker.whatsapp_msg_id)
            self.transport_index[key] = {"thread_id": thread_id, "run_id": run_id}

    def add_business_key(self, key_type: str, value: str, thread_id: str):
        """Register a business key so future messages referencing it are correlated.

        Args:
            key_type: The type of key (order_ref, ticket_id, etc.)
            value: The key value
            thread_id: The thread this key belongs to
        """
        lookup_key = (key_type, value)
        if lookup_key not in self.business_key_index:
            self.business_key_index[lookup_key] = []
        if thread_id not in self.business_key_index[lookup_key]:
            self.business_key_index[lookup_key].append(thread_id)
