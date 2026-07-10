"""Wave 7: Outbound Communication Governance — route outbound messages through Wosool.

Outbound messages from cycles/capabilities must go through the Wosool governed routing layer, which
enforces governance tiers (LOW/MEDIUM/HIGH/CRITICAL), approval requirements, and audit trails.

Design principle: All outbound is soft (sent directly), assisted (notify human), or enterprise
(wait for approval) based on governance tier. Governance metadata (reply-token, BCONV) is stamped
on outbound so return messages correlate back.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from nilscript.kernel.models import DslModel


class OutboundMessage(DslModel):
    """A cycle/capability wants to send a message.

    This is the INPUT to the governance layer. Once routed and approved (if needed),
    it becomes a CommitOutboundMessage that the adapter executes.
    """

    id: str  # UUID
    thread_id: str
    run_id: str | None = None
    cycle_id: str
    capability: str = "communication.send_email"  # "communication.send_email", "communication.send_whatsapp"
    channel: Literal["email", "whatsapp", "sms"] = "email"
    recipient: str  # Email address, phone number, WhatsApp ID, etc.
    recipient_name: str | None = None

    # Message content
    subject: str | None = None  # Email only
    body: str
    html_body: str | None = None  # Email: alternative HTML version
    attachments: list[dict] = Field(default_factory=list)  # [{"filename": "...", "url": "..."}]

    # Governance
    governance_tier: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "LOW"
    requires_approval: bool = False  # If tier=HIGH or CRITICAL

    # Correlation & reply handling
    reply_token: str | None = None  # For stamping outbound so replies correlate back
    bconv_id: str | None = None  # Business Conversation ID to stamp on outbound

    # Metadata
    created_at: str  # ISO timestamp
    created_by: str = "system"


class OutboundRoute(DslModel):
    """The routing decision after governance tier evaluation."""

    outbound_id: str
    governance_tier: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    action: Literal["send_immediately", "send_with_notification", "wait_for_approval"]

    # If send_with_notification: notify this actor(s)
    notify_actors: list[str] = Field(default_factory=list)

    # If wait_for_approval: need approval from these role(s)
    approval_required_from: list[str] = Field(default_factory=list)  # ["approver", "manager"]


class CommitOutboundMessage(DslModel):
    """An OutboundMessage after governance approval, ready for the adapter to execute.

    This carries the governance decision and any stamped metadata.
    """

    id: str  # Same as OutboundMessage.id
    outbound_id: str  # Reference to the original OutboundMessage
    thread_id: str
    run_id: str | None = None

    # Message (verbatim from OutboundMessage, plus any governance edits)
    channel: Literal["email", "whatsapp", "sms"]
    recipient: str
    recipient_name: str | None = None
    subject: str | None = None
    body: str
    html_body: str | None = None
    attachments: list[dict] = Field(default_factory=list)

    # Governance + correlation metadata
    governance_tier: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    bconv_stamp: str | None = None  # BCONV to stamp on outbound (e.g., "[BCONV-...]" in subject)
    reply_token_stamp: str | None = None  # Token to stamp (e.g., "[WSL-...]" in subject/Reply-To)

    # Headers/metadata to inject
    custom_headers: dict = Field(default_factory=dict)  # {"X-Wosool-Conversation-ID": "BCONV-..."}

    # Audit
    routed_at: str  # ISO timestamp
    routed_by: str = "system"
    approved_by: str | None = None  # If approval was required


class OutboundGovernance:
    """Route outbound messages through Wosool governance tiers.

    API:
      - route_outbound(message) -> OutboundRoute
      - commit_outbound(route, message) -> CommitOutboundMessage
      - stamp_reply_token(message) -> str (the stamped reply token)
    """

    def __init__(self):
        self.routes: dict[str, OutboundRoute] = {}  # outbound_id -> OutboundRoute
        self.messages: dict[str, OutboundMessage] = {}  # outbound_id -> OutboundMessage
        self.commits: dict[str, CommitOutboundMessage] = {}  # outbound_id -> CommitOutboundMessage

    def route_outbound(self, message: OutboundMessage) -> OutboundRoute:
        """Route: governance tier → approval level.

        Governance routing:
          - LOW/MEDIUM: send immediately (soft governance)
          - HIGH: notify human(s) + send anyway (assisted governance)
          - CRITICAL: wait for human approval before sending (enterprise relay)

        Args:
            message: The OutboundMessage to route

        Returns:
            OutboundRoute with the governance decision
        """
        self.messages[message.id] = message

        tier = message.governance_tier
        requires_approval = message.requires_approval or tier in ["HIGH", "CRITICAL"]

        action = "send_immediately"
        notify_actors = []
        approval_required_from = []

        if tier == "MEDIUM":
            action = "send_immediately"
            # Could optionally notify on MEDIUM; depends on policy
        elif tier == "HIGH":
            action = "send_with_notification"
            notify_actors = ["manager", "audit"]
        elif tier == "CRITICAL":
            action = "wait_for_approval"
            approval_required_from = ["approver", "manager"]

        route = OutboundRoute(
            outbound_id=message.id,
            governance_tier=tier,
            action=action,
            notify_actors=notify_actors,
            approval_required_from=approval_required_from,
        )

        self.routes[message.id] = route
        return route

    def commit_outbound(
        self, message: OutboundMessage, route: OutboundRoute, approved_by: str | None = None
    ) -> CommitOutboundMessage:
        """Commit an outbound message (after any approvals).

        This creates a CommitOutboundMessage with governance metadata and reply tokens stamped.

        Args:
            message: The original OutboundMessage
            route: The routing decision
            approved_by: If approval was required, who approved it?

        Returns:
            CommitOutboundMessage ready for the adapter to execute
        """
        commit_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        # Stamp reply token on the outbound
        reply_token = message.reply_token or self._generate_reply_token(message)
        reply_token_stamp = self._stamp_reply_token(message.channel, reply_token)

        # Stamp BCONV if present
        bconv_stamp = message.bconv_id
        if bconv_stamp and message.channel == "email":
            # For email, BCONV goes in subject prefix
            bconv_stamp = f"[{bconv_stamp}]"

        # Build custom headers
        custom_headers = {}
        if message.channel == "email":
            custom_headers["X-Wosool-Conversation-ID"] = message.bconv_id or ""
            custom_headers["X-Wosool-Reply-Token"] = reply_token
            # Reply-To will be set by adapter to include the reply token
            custom_headers["Reply-To"] = f"wsl-{reply_token}@wosool.ai"

        # Build subject with BCONV stamp
        subject = message.subject or ""
        if bconv_stamp and message.channel == "email":
            subject = f"{bconv_stamp} {subject}".strip()

        commit = CommitOutboundMessage(
            id=commit_id,
            outbound_id=message.id,
            thread_id=message.thread_id,
            run_id=message.run_id,
            channel=message.channel,
            recipient=message.recipient,
            recipient_name=message.recipient_name,
            subject=subject,
            body=message.body,
            html_body=message.html_body,
            attachments=message.attachments,
            governance_tier=message.governance_tier,
            bconv_stamp=message.bconv_id,
            reply_token_stamp=reply_token_stamp,
            custom_headers=custom_headers,
            routed_at=now,
            approved_by=approved_by,
        )

        self.commits[message.id] = commit
        return commit

    def stamp_reply_token(self, message: OutboundMessage) -> str:
        """Add reply-token header/prefix for return correlation.

        Different channels use different stamping strategies:
          - Email: X-Wosool-Conversation-ID header + Reply-To prefix
          - WhatsApp: Message prefix like "PO-2026-00145:"
          - SMS: Embed token in message like "[WSL-abc123]"

        Args:
            message: The OutboundMessage

        Returns:
            The stamped/embedded reply token
        """
        reply_token = message.reply_token or self._generate_reply_token(message)
        return self._stamp_reply_token(message.channel, reply_token)

    def _generate_reply_token(self, message: OutboundMessage) -> str:
        """Generate a unique reply token for this outbound message.

        The token is used to correlate return messages back to this thread.
        """
        # Simple UUID-based token; could be shorter in production
        return f"wsl-{uuid.uuid4().hex[:16]}"

    def _stamp_reply_token(self, channel: Literal["email", "whatsapp", "sms"], token: str) -> str:
        """Format the reply token for a specific channel.

        Args:
            channel: The communication channel
            token: The reply token (e.g., "wsl-abc123")

        Returns:
            Stamped format (e.g., "[WSL-abc123]" for email subject)
        """
        if channel == "email":
            return f"[{token.upper()}]"
        elif channel == "whatsapp":
            return f"{token}:"  # Prefix like "wsl-abc123: Your message"
        elif channel == "sms":
            return f"[{token}]"
        return token

    def get_outbound(self, outbound_id: str) -> OutboundMessage | None:
        """Get an outbound message by ID."""
        return self.messages.get(outbound_id)

    def get_route(self, outbound_id: str) -> OutboundRoute | None:
        """Get the routing decision for an outbound message."""
        return self.routes.get(outbound_id)

    def get_commit(self, outbound_id: str) -> CommitOutboundMessage | None:
        """Get the committed outbound message (post-approval)."""
        return self.commits.get(outbound_id)


class OutboundApprovalCard(DslModel):
    """An approval card for CRITICAL-tier outbound messages."""

    id: str  # UUID / proposal_id
    outbound_id: str
    thread_id: str
    created_at: str  # ISO timestamp
    status: Literal["pending", "approved", "rejected"] = "pending"

    # Card details
    title: str  # "Approve outbound email"
    channel: Literal["email", "whatsapp", "sms"]
    recipient: str
    subject: str | None = None
    body_preview: str  # First 200 chars of body

    # Risk
    tier: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    reason_for_approval: str | None = None

    # Approval metadata
    requires_role: str = "approver"
    approved_by: str | None = None
    approved_at: str | None = None
    decision_reason: str | None = None


def outbound_to_approval_card(message: OutboundMessage, route: OutboundRoute) -> OutboundApprovalCard | None:
    """Convert an OutboundMessage that requires approval into an approval card.

    Args:
        message: The OutboundMessage
        route: The routing decision

    Returns:
        An OutboundApprovalCard if approval is required, else None
    """
    if route.action != "wait_for_approval":
        return None

    body_preview = message.body[:200] if message.body else ""

    card = OutboundApprovalCard(
        id=str(uuid.uuid4()),
        outbound_id=message.id,
        thread_id=message.thread_id,
        created_at=datetime.utcnow().isoformat(),
        title=f"Approve outbound {message.channel} to {message.recipient_name or message.recipient}",
        channel=message.channel,
        recipient=message.recipient,
        subject=message.subject,
        body_preview=body_preview,
        tier=message.governance_tier,
        requires_role="approver",
    )

    return card
