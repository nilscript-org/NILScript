"""Channel Adapter Contract — standardized interface for all messaging channels.

Every channel (WhatsApp, Email, SMS, Slack) implements this contract. The adapter is
responsible for:
1. Sending outbound messages
2. Rendering and sending permission cards (governance gates)
3. Handling inbound messages
4. Fetching conversation history for correlation

This design enables:
- Protocol-agnostic message routing
- Channel-native permission card rendering
- Inbound message standardization
- Conversation correlation across channels
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """Message type enum."""

    TEXT = "text"
    MEDIA = "media"
    AUDIO = "audio"
    DOCUMENT = "document"
    INTERACTIVE = "interactive"
    SYSTEM = "system"


class MessageStatus(str, Enum):
    """Message delivery status."""

    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    PENDING = "pending"


class OutboundMessage(BaseModel):
    """Contract for outbound messages returned by channel adapters."""

    message_id: str = Field(description="Unique message ID from the channel")
    recipient: str = Field(description="Recipient identifier (phone, email, user ID, etc.)")
    timestamp: datetime = Field(description="When the message was sent")
    status: MessageStatus = Field(default=MessageStatus.SENT)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InboundMessage(BaseModel):
    """Standardized inbound message from any channel."""

    sender: str = Field(description="Sender identifier (phone, email, user ID, etc.)")
    body: str = Field(description="Message content")
    timestamp: datetime = Field(description="When the message was received")
    channel: str = Field(description="Channel name (whatsapp, email, sms, slack)")
    channel_message_id: str = Field(description="Channel-native message ID")
    reply_to: str | None = Field(default=None, description="ID of message being replied to")
    message_type: MessageType = Field(default=MessageType.TEXT)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PermissionCard(BaseModel):
    """Governance gate (approval request) to be rendered in channel-native UI."""

    proposal_id: str = Field(description="Unique ID for this approval proposal")
    thread_id: str = Field(description="Associated thread/cycle instance ID")
    title: str = Field(description="Short title of what needs approval")
    description: str = Field(description="Longer explanation")
    actions: dict[str, str] = Field(
        description="Available actions: {action_key: action_label}"
    )
    # action_key examples: "approve", "deny", "escalate"
    # action_label examples: "✓ Approve", "✗ Deny", "⬆ Escalate"
    tier: str = Field(description="Approval tier: LOW, MEDIUM, HIGH, CRITICAL")
    metadata: dict[str, Any] = Field(default_factory=dict)


class PermissionCardResponse(BaseModel):
    """User's response to a permission card."""

    proposal_id: str = Field(description="Which proposal was responded to")
    action: str = Field(description="Which action was chosen (approve, deny, escalate, etc.)")
    timestamp: datetime = Field(description="When the response was recorded")
    responder: str = Field(description="Who responded (user ID, phone, email, etc.)")
    channel: str = Field(description="Which channel the response came from")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationMessage(BaseModel):
    """A single message in conversation history."""

    sender: str = Field(description="Who sent this message")
    body: str = Field(description="Message content")
    timestamp: datetime = Field(description="When it was sent")
    direction: str = Field(description="inbound or outbound")


class ChannelAdapter(ABC):
    """Abstract base class for all channel adapters.

    Every channel adapter MUST implement this interface. Subclasses include:
    - WhatsAppAdapter (via Evolution API)
    - EmailAdapter (SMTP + IMAP)
    - SlackAdapter (Bolt framework)
    - SMSAdapter (Twilio, Nexmo, etc.)
    """

    CHANNEL_NAME: str
    """The canonical name of this channel (e.g., 'whatsapp', 'email', 'slack', 'sms')."""

    @abstractmethod
    async def send_message(self, recipient: str, body: str, metadata: dict | None = None) -> OutboundMessage:
        """Send a text message to a recipient.

        Args:
            recipient: Channel-specific recipient ID (phone, email, user ID, etc.)
            body: Message body/content
            metadata: Channel-specific metadata (optional attachments, format hints, etc.)

        Returns:
            OutboundMessage with channel-assigned message ID and timestamp

        Raises:
            ChannelError: If send fails (network, auth, rate limit, etc.)
        """
        pass

    @abstractmethod
    async def send_permission_card(self, recipient: str, card: PermissionCard) -> str:
        """Send a governance gate (permission card) in channel-native UI.

        The adapter is responsible for rendering the card in channel-specific format:
        - WhatsApp: interactive message with button rows
        - Slack: Block Kit message with action buttons
        - SMS: text with reply codes
        - Email: HTML + plain text with action links

        Args:
            recipient: Who receives this card
            card: The permission card to render and send

        Returns:
            The interaction ID (or message ID) assigned by the channel

        Raises:
            ChannelError: If send fails or card rendering is unsupported
        """
        pass

    @abstractmethod
    async def handle_inbound(self, webhook_payload: dict[str, Any]) -> InboundMessage:
        """Process an inbound webhook from the channel.

        Each channel sends webhooks in its own format (WhatsApp Evolution,
        Slack Events API, Email IMAP, SMS callback). This method parses
        the channel-native format and returns a standardized InboundMessage.

        Args:
            webhook_payload: Raw webhook payload from the channel

        Returns:
            Standardized InboundMessage

        Raises:
            ChannelError: If payload is malformed or unsupported
        """
        pass

    @abstractmethod
    async def handle_permission_response(
        self, webhook_payload: dict[str, Any]
    ) -> PermissionCardResponse:
        """Process a user's response to a permission card.

        When a user clicks an action button on a permission card, the channel
        sends a callback. This method extracts the action, proposal ID, and
        responder from the channel-native format.

        Args:
            webhook_payload: Raw callback payload from the channel

        Returns:
            PermissionCardResponse with action and responder info

        Raises:
            ChannelError: If payload is malformed
        """
        pass

    @abstractmethod
    async def fetch_conversation_history(
        self, recipient: str, limit: int = 10
    ) -> list[ConversationMessage]:
        """Fetch recent message history with a recipient.

        Used by the Correlation Engine to link inbound messages to threads.
        Returns the N most recent messages in reverse chronological order
        (newest first).

        Args:
            recipient: Who to fetch history for
            limit: How many messages to return (default 10)

        Returns:
            List of ConversationMessage in reverse chronological order

        Raises:
            ChannelError: If fetch fails
        """
        pass


class ChannelAdapterRegistry:
    """Registry of all active channel adapters.

    Channels are registered at startup. The registry is queried by:
    - Invocation parser (which channel is this message from?)
    - Message router (which channel should this go out on?)
    - Correlation engine (fetch history for deduplication)
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ChannelAdapter] = {}

    def register(self, adapter: ChannelAdapter) -> None:
        """Register a channel adapter.

        Args:
            adapter: The adapter to register

        Raises:
            ValueError: If channel name is already registered
        """
        if adapter.CHANNEL_NAME in self._adapters:
            raise ValueError(f"Channel {adapter.CHANNEL_NAME} already registered")
        self._adapters[adapter.CHANNEL_NAME] = adapter

    def get(self, channel_name: str) -> ChannelAdapter:
        """Get a registered adapter by channel name.

        Args:
            channel_name: The channel name (e.g., 'whatsapp')

        Returns:
            The ChannelAdapter

        Raises:
            KeyError: If channel is not registered
        """
        if channel_name not in self._adapters:
            raise KeyError(f"Channel {channel_name} not registered")
        return self._adapters[channel_name]

    def list_channels(self) -> list[str]:
        """List all registered channel names.

        Returns:
            List of channel names in alphabetical order
        """
        return sorted(self._adapters.keys())

    def has_channel(self, channel_name: str) -> bool:
        """Check if a channel is registered.

        Args:
            channel_name: The channel name

        Returns:
            True if registered, False otherwise
        """
        return channel_name in self._adapters


class ChannelError(Exception):
    """Base exception for all channel-related errors."""

    pass


class ChannelAuthError(ChannelError):
    """Authentication/authorization failure with the channel."""

    pass


class ChannelRateLimitError(ChannelError):
    """Rate limit exceeded on the channel."""

    pass


class ChannelTimeoutError(ChannelError):
    """Operation timed out on the channel."""

    pass


class ChannelUnsupportedError(ChannelError):
    """Operation is not supported by this channel."""

    pass
