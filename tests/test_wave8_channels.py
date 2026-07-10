"""Wave 8 Omnichannel Terminals — comprehensive tests for channel infrastructure.

Tests cover:
1. Channel adapter contract (15 tests total)
2. Invocation parser (channel-specific patterns)
3. Permission card rendering (all channels)
4. Inbound/outbound message handling
5. Conversation correlation
"""

import pytest
from datetime import datetime

from nilscript.channels.adapter_contract import (
    ChannelAdapter,
    ChannelAdapterRegistry,
    ChannelError,
    ConversationMessage,
    InboundMessage,
    MessageStatus,
    MessageType,
    OutboundMessage,
    PermissionCard,
    PermissionCardResponse,
)
from nilscript.channels.invocation_parser import InvocationMatch, InvocationParser
from nilscript.channels.permission_card_renderer import (
    EmailCardRenderer,
    PermissionCardRenderer,
    SMSCardRenderer,
    SlackCardRenderer,
    WhatsAppCardRenderer,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Channel Adapter Contract Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class MockChannelAdapter(ChannelAdapter):
    """Mock adapter for testing the contract."""

    CHANNEL_NAME = "mock"

    async def send_message(self, recipient: str, body: str, metadata: dict | None = None) -> OutboundMessage:
        return OutboundMessage(
            message_id="msg_123",
            recipient=recipient,
            timestamp=datetime.now(),
            status=MessageStatus.SENT,
        )

    async def send_permission_card(self, recipient: str, card: PermissionCard) -> str:
        return f"interaction_{card.proposal_id}"

    async def handle_inbound(self, webhook_payload: dict) -> InboundMessage:
        return InboundMessage(
            sender=webhook_payload.get("sender", "unknown"),
            body=webhook_payload.get("body", ""),
            timestamp=datetime.now(),
            channel="mock",
            channel_message_id="ch_msg_123",
        )

    async def handle_permission_response(self, webhook_payload: dict) -> PermissionCardResponse:
        return PermissionCardResponse(
            proposal_id=webhook_payload.get("proposal_id", ""),
            action=webhook_payload.get("action", ""),
            timestamp=datetime.now(),
            responder=webhook_payload.get("responder", ""),
            channel="mock",
        )

    async def fetch_conversation_history(self, recipient: str, limit: int = 10) -> list[ConversationMessage]:
        return [
            ConversationMessage(
                sender=recipient,
                body="Hello",
                timestamp=datetime.now(),
                direction="inbound",
            )
        ]


def test_adapter_registry_register_and_get() -> None:
    """Test registering and retrieving adapters."""
    registry = ChannelAdapterRegistry()
    adapter = MockChannelAdapter()
    registry.register(adapter)

    retrieved = registry.get("mock")
    assert retrieved.CHANNEL_NAME == "mock"


def test_adapter_registry_duplicate_registration() -> None:
    """Test that duplicate registrations are rejected."""
    registry = ChannelAdapterRegistry()
    adapter1 = MockChannelAdapter()
    adapter2 = MockChannelAdapter()

    registry.register(adapter1)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(adapter2)


def test_adapter_registry_get_nonexistent() -> None:
    """Test that getting nonexistent adapter raises KeyError."""
    registry = ChannelAdapterRegistry()
    with pytest.raises(KeyError):
        registry.get("nonexistent")


def test_adapter_registry_list_channels() -> None:
    """Test listing registered channels."""
    registry = ChannelAdapterRegistry()
    adapter1 = MockChannelAdapter()
    adapter1.CHANNEL_NAME = "whatsapp"
    registry.register(adapter1)

    adapter2 = MockChannelAdapter()
    adapter2.CHANNEL_NAME = "slack"
    registry.register(adapter2)

    channels = registry.list_channels()
    assert channels == ["slack", "whatsapp"]  # Alphabetical


def test_adapter_registry_has_channel() -> None:
    """Test checking if channel is registered."""
    registry = ChannelAdapterRegistry()
    adapter = MockChannelAdapter()
    registry.register(adapter)

    assert registry.has_channel("mock")
    assert not registry.has_channel("nonexistent")


@pytest.mark.asyncio
async def test_outbound_message_model() -> None:
    """Test OutboundMessage pydantic model."""
    msg = OutboundMessage(
        message_id="msg_123",
        recipient="+1234567890",
        timestamp=datetime.now(),
        status=MessageStatus.DELIVERED,
    )
    assert msg.message_id == "msg_123"
    assert msg.status == MessageStatus.DELIVERED


@pytest.mark.asyncio
async def test_inbound_message_model() -> None:
    """Test InboundMessage pydantic model."""
    msg = InboundMessage(
        sender="+1234567890",
        body="Hello",
        timestamp=datetime.now(),
        channel="whatsapp",
        channel_message_id="ch_msg_123",
    )
    assert msg.sender == "+1234567890"
    assert msg.message_type == MessageType.TEXT


@pytest.mark.asyncio
async def test_permission_card_model() -> None:
    """Test PermissionCard pydantic model."""
    card = PermissionCard(
        proposal_id="prop_123",
        thread_id="thread_123",
        title="Approve invoice",
        description="Vendor Acme $1000",
        actions={"approve": "Approve", "deny": "Deny"},
        tier="MEDIUM",
    )
    assert card.proposal_id == "prop_123"
    assert len(card.actions) == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Invocation Parser Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_invocation_parser_whatsapp_prefix() -> None:
    """Test parsing WhatsApp message with @wosool prefix."""
    parser = InvocationParser()
    match = parser.parse("@wosool order Acme 100", "whatsapp", sender="user_123")

    assert match is not None
    assert match.cycle_name == "order"
    assert match.channel == "whatsapp"
    assert match.confidence >= 0.90


def test_invocation_parser_whatsapp_slash_command() -> None:
    """Test parsing WhatsApp message with slash command."""
    parser = InvocationParser()
    match = parser.parse("/wosool order Acme 100", "whatsapp")

    assert match is not None
    assert match.cycle_name == "order"


def test_invocation_parser_slack_mention() -> None:
    """Test parsing Slack message with bot mention."""
    parser = InvocationParser()
    match = parser.parse("@wosool-bot approve_invoice vendor=Acme", "slack")

    assert match is not None
    assert match.cycle_name == "approve_invoice"
    assert match.parameters.get("vendor") == "Acme"


def test_invocation_parser_slack_slash() -> None:
    """Test parsing Slack slash command."""
    parser = InvocationParser()
    match = parser.parse("/wosool order param1=value1", "slack")

    assert match is not None
    assert match.cycle_name == "order"


def test_invocation_parser_sms() -> None:
    """Test parsing SMS message."""
    parser = InvocationParser()
    match = parser.parse("wosool: order Acme 100", "sms", sender="+1234567890")

    assert match is not None
    assert match.cycle_name == "order"
    assert match.channel == "sms"
    assert match.confidence >= 0.90


def test_invocation_parser_email_subject() -> None:
    """Test parsing email subject line."""
    parser = InvocationParser()
    match = parser.parse("Cycle: order Acme 100", "email")

    assert match is not None
    assert match.cycle_name == "order"


def test_invocation_parser_parameter_extraction() -> None:
    """Test extracting key=value parameters."""
    parser = InvocationParser()
    match = parser.parse("@wosool order vendor=Acme amount=1000", "whatsapp")

    assert match is not None
    assert match.parameters.get("vendor") == "Acme"
    assert match.parameters.get("amount") == "1000"


def test_invocation_parser_no_match() -> None:
    """Test that non-invocation messages return None."""
    parser = InvocationParser()
    match = parser.parse("Just a regular message", "whatsapp")

    assert match is None


def test_invocation_parser_fill_missing_slots() -> None:
    """Test filling in missing parameters from thread context."""
    parser = InvocationParser()
    match = InvocationMatch(
        intent="ExecuteCycle",
        cycle_name="approve_invoice",
        parameters={},
        channel="whatsapp",
        confidence=0.70,
    )

    context = {
        "vendor": "Acme",
        "amount": 1000,
    }

    filled = parser.fill_missing_slots(match, context)

    assert filled.parameters.get("vendor") == "Acme"
    assert filled.parameters.get("amount") == 1000
    assert filled.confidence >= match.confidence  # May increase but capped at 1.0


def test_invocation_parser_list_supported_channels() -> None:
    """Test listing supported channels."""
    parser = InvocationParser()
    channels = parser.list_supported_channels()

    assert "whatsapp" in channels
    assert "slack" in channels
    assert "sms" in channels
    assert "email" in channels


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. Permission Card Rendering Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_whatsapp_card_rendering() -> None:
    """Test rendering permission card for WhatsApp."""
    renderer = WhatsAppCardRenderer()
    card = PermissionCard(
        proposal_id="prop_123",
        thread_id="thread_123",
        title="Approve invoice",
        description="Vendor Acme $1000",
        actions={"approve": "✓ Approve", "deny": "✗ Deny"},
        tier="MEDIUM",
    )

    rendered = await renderer.render(card)

    assert rendered.channel == "whatsapp"
    assert rendered.interaction_id == "prop_123"
    assert "interactive" in rendered.payload
    assert "button" in rendered.payload["interactive"]["type"]


@pytest.mark.asyncio
async def test_slack_card_rendering() -> None:
    """Test rendering permission card for Slack."""
    renderer = SlackCardRenderer()
    card = PermissionCard(
        proposal_id="prop_123",
        thread_id="thread_123",
        title="Approve invoice",
        description="Vendor Acme $1000",
        actions={"approve": "Approve", "deny": "Deny", "escalate": "Escalate"},
        tier="HIGH",
    )

    rendered = await renderer.render(card)

    assert rendered.channel == "slack"
    assert "blocks" in rendered.payload
    assert len(rendered.payload["blocks"]) > 0


@pytest.mark.asyncio
async def test_sms_card_rendering() -> None:
    """Test rendering permission card for SMS."""
    renderer = SMSCardRenderer()
    card = PermissionCard(
        proposal_id="prop_123",
        thread_id="thread_123",
        title="Approve",
        description="Invoice $1000",
        actions={"approve": "Approve", "deny": "Deny"},
        tier="MEDIUM",
    )

    rendered = await renderer.render(card)

    assert rendered.channel == "sms"
    assert "body" in rendered.payload
    assert "A (Approve)" in rendered.payload["body"]
    assert "D (Deny)" in rendered.payload["body"]


@pytest.mark.asyncio
async def test_email_card_rendering() -> None:
    """Test rendering permission card for Email."""
    renderer = EmailCardRenderer()
    card = PermissionCard(
        proposal_id="prop_123",
        thread_id="thread_123",
        title="Approve invoice",
        description="Vendor Acme $1000",
        actions={"approve": "Approve", "deny": "Deny"},
        tier="CRITICAL",
    )

    rendered = await renderer.render(card)

    assert rendered.channel == "email"
    assert "html" in rendered.payload
    assert "plain" in rendered.payload
    assert "subject" in rendered.payload


@pytest.mark.asyncio
async def test_whatsapp_response_parsing() -> None:
    """Test parsing WhatsApp response to permission card."""
    renderer = WhatsAppCardRenderer()
    payload = {
        "message": {
            "fromMe": False,
            "id": "wamid_123",
            "timestamp": 1234567890,
            "body": "approve",
        },
        "sender": {
            "id": "1234567890",
        },
    }

    response = await renderer.handle_response(payload)

    assert response.action == "approve"
    assert response.responder == "1234567890"
    assert response.channel == "whatsapp"


@pytest.mark.asyncio
async def test_slack_response_parsing() -> None:
    """Test parsing Slack response to permission card."""
    renderer = SlackCardRenderer()
    payload = {
        "actions": [
            {
                "type": "button",
                "action_id": "card_approve_prop_123",
                "value": "approve",
            }
        ],
        "user": {
            "id": "U123456",
        },
    }

    response = await renderer.handle_response(payload)

    assert response.action == "approve"
    assert response.responder == "U123456"
    assert response.proposal_id == "prop_123"


@pytest.mark.asyncio
async def test_sms_response_parsing() -> None:
    """Test parsing SMS response to permission card."""
    renderer = SMSCardRenderer()
    payload = {
        "from": "+1234567890",
        "body": "A",
        "proposal_id": "prop_123",
    }

    response = await renderer.handle_response(payload)

    assert response.action == "approve"
    assert response.responder == "+1234567890"
    assert response.channel == "sms"


@pytest.mark.asyncio
async def test_email_response_parsing() -> None:
    """Test parsing email response to permission card."""
    renderer = EmailCardRenderer()
    payload = {
        "from": "user@example.com",
        "body": "approve",
        "proposal_id": "prop_123",
    }

    response = await renderer.handle_response(payload)

    assert response.action == "approve"
    assert response.responder == "user@example.com"
    assert response.channel == "email"


@pytest.mark.asyncio
async def test_permission_card_renderer_dispatch() -> None:
    """Test PermissionCardRenderer dispatching to channel-specific renderers."""
    renderer = PermissionCardRenderer()
    card = PermissionCard(
        proposal_id="prop_123",
        thread_id="thread_123",
        title="Approve",
        description="Invoice",
        actions={"approve": "Approve"},
        tier="MEDIUM",
    )

    # Test WhatsApp
    whatsapp_rendered = await renderer.render_for_channel("whatsapp", card)
    assert whatsapp_rendered.channel == "whatsapp"

    # Test Slack
    slack_rendered = await renderer.render_for_channel("slack", card)
    assert slack_rendered.channel == "slack"

    # Test SMS
    sms_rendered = await renderer.render_for_channel("sms", card)
    assert sms_rendered.channel == "sms"

    # Test Email
    email_rendered = await renderer.render_for_channel("email", card)
    assert email_rendered.channel == "email"


@pytest.mark.asyncio
async def test_permission_card_renderer_unsupported_channel() -> None:
    """Test that unsupported channels raise ValueError."""
    renderer = PermissionCardRenderer()
    card = PermissionCard(
        proposal_id="prop_123",
        thread_id="thread_123",
        title="Approve",
        description="Invoice",
        actions={"approve": "Approve"},
        tier="MEDIUM",
    )

    with pytest.raises(ValueError):
        await renderer.render_for_channel("unsupported_channel", card)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. Integration Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_end_to_end_whatsapp_approval_flow() -> None:
    """Test full flow: render card -> send -> receive response -> parse response."""
    # 1. Render card for WhatsApp
    card = PermissionCard(
        proposal_id="prop_123",
        thread_id="thread_456",
        title="Approve invoice",
        description="Vendor Acme $1000",
        actions={"approve": "✓ Approve", "deny": "✗ Deny"},
        tier="MEDIUM",
    )

    renderer = WhatsAppCardRenderer()
    rendered = await renderer.render(card)
    assert rendered.channel == "whatsapp"

    # 2. Simulate user response via webhook
    response_payload = {
        "message": {
            "fromMe": False,
            "id": "wamid_123",
            "timestamp": 1234567890,
            "body": "approve",
        },
        "sender": {
            "id": "1234567890",
        },
    }

    # 3. Parse response
    response = await renderer.handle_response(response_payload)
    assert response.action == "approve"
    assert response.channel == "whatsapp"
    assert response.responder == "1234567890"
    # thread_id is set by correlation engine, not included in adapter response


def test_cycle_invocation_from_message() -> None:
    """Test detecting and parsing a cycle invocation from a message."""
    parser = InvocationParser()

    # User sends: "@wosool order Acme 100 units"
    message = "@wosool order Acme 100 units"
    match = parser.parse(message, "whatsapp", sender="user_123")

    assert match is not None
    assert match.intent == "ExecuteCycle"
    assert match.cycle_name == "order"
    assert match.channel == "whatsapp"
    assert match.sender == "user_123"
