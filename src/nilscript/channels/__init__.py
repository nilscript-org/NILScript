"""nilscript channel integrations — outbound/inbound adapters for messaging surfaces.

Wave 8: Omnichannel Terminals — all messaging surfaces via a standardized adapter contract.

Modules:
  - adapter_contract: Abstract ChannelAdapter + registry
  - invocation_parser: Parse channel messages for cycle invocations
  - permission_card_renderer: Render governance gates in channel-native UI
  - mobile_terminal: Mobile app API surface

Each channel is self-contained (no cross-channel coupling).
Implementations: whatsapp (Evolution API), slack (Bolt), sms (Twilio), email (SMTP+IMAP)
"""

from .adapter_contract import (
    ChannelAdapter,
    ChannelAdapterRegistry,
    ChannelAuthError,
    ChannelError,
    ChannelRateLimitError,
    ChannelTimeoutError,
    ChannelUnsupportedError,
    ConversationMessage,
    InboundMessage,
    MessageStatus,
    MessageType,
    OutboundMessage,
    PermissionCard,
    PermissionCardResponse,
)
from .invocation_parser import InvocationMatch, InvocationParser
from .permission_card_renderer import (
    BaseCardRenderer,
    EmailCardRenderer,
    PermissionCardRenderer,
    RenderedCard,
    SMSCardRenderer,
    SlackCardRenderer,
    WhatsAppCardRenderer,
)
from .mobile_terminal import (
    ApprovalProposal,
    ApprovalStatus,
    DocumentRef,
    Message,
    MobileNotification,
    MobileTerminal,
    MobileTerminalConfig,
    ThreadDetail,
    ThreadStatus,
    ThreadSummary,
    TimelineEvent,
)

__all__ = [
    # Adapter contract
    "ChannelAdapter",
    "ChannelAdapterRegistry",
    "ChannelError",
    "ChannelAuthError",
    "ChannelRateLimitError",
    "ChannelTimeoutError",
    "ChannelUnsupportedError",
    "MessageType",
    "MessageStatus",
    "OutboundMessage",
    "InboundMessage",
    "PermissionCard",
    "PermissionCardResponse",
    "ConversationMessage",
    # Invocation parser
    "InvocationParser",
    "InvocationMatch",
    # Permission card renderer
    "PermissionCardRenderer",
    "RenderedCard",
    "BaseCardRenderer",
    "WhatsAppCardRenderer",
    "SlackCardRenderer",
    "SMSCardRenderer",
    "EmailCardRenderer",
    # Mobile terminal
    "MobileTerminal",
    "MobileTerminalConfig",
    "MobileNotification",
    "ThreadSummary",
    "ThreadDetail",
    "ThreadStatus",
    "ApprovalProposal",
    "ApprovalStatus",
    "TimelineEvent",
    "Message",
    "DocumentRef",
]
