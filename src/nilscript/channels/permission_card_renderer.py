"""Permission Card Renderer — render governance gates in channel-native UI.

A permission card is a governance gate requesting approval for a cycle step.
Each channel renders the card in its native UI:
- WhatsApp: interactive message with button rows
- Slack: Block Kit message with action buttons
- SMS: text with reply codes
- Email: HTML + plain text with action links

The renderer is responsible for:
1. Converting the generic PermissionCard to channel-specific format
2. Capturing user responses via channel-native callbacks
3. Mapping responses back to the governance system
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .adapter_contract import PermissionCard, PermissionCardResponse


@dataclass
class RenderedCard:
    """The channel-native representation of a permission card."""

    channel: str
    payload: dict[str, Any]
    """Channel-specific payload (WhatsApp JSON, Slack Block Kit, etc.)."""

    interaction_id: str | None = None
    """ID for tracking this rendered card's responses."""


class PermissionCardRenderer:
    """Render permission cards in channel-native formats."""

    def __init__(self) -> None:
        """Initialize the renderer."""
        self._renderers: dict[str, BaseCardRenderer] = {
            "whatsapp": WhatsAppCardRenderer(),
            "slack": SlackCardRenderer(),
            "sms": SMSCardRenderer(),
            "email": EmailCardRenderer(),
        }

    async def render_for_channel(
        self, channel: str, card: PermissionCard
    ) -> RenderedCard:
        """Render a card for a specific channel.

        Args:
            channel: The channel name (whatsapp, slack, sms, email)
            card: The permission card to render

        Returns:
            RenderedCard with channel-native payload

        Raises:
            ValueError: If channel is not supported
        """
        if channel not in self._renderers:
            raise ValueError(f"No renderer for channel: {channel}")
        renderer = self._renderers[channel]
        return await renderer.render(card)

    async def render_for_whatsapp(self, card: PermissionCard) -> RenderedCard:
        """Render for WhatsApp using Evolution API interactive messages."""
        return await self._renderers["whatsapp"].render(card)

    async def render_for_slack(self, card: PermissionCard) -> RenderedCard:
        """Render for Slack using Block Kit."""
        return await self._renderers["slack"].render(card)

    async def render_for_sms(self, card: PermissionCard) -> RenderedCard:
        """Render for SMS using text codes."""
        return await self._renderers["sms"].render(card)

    async def render_for_email(self, card: PermissionCard) -> RenderedCard:
        """Render for Email using HTML + plain text."""
        return await self._renderers["email"].render(card)

    async def handle_card_response(
        self, channel: str, payload: dict[str, Any]
    ) -> PermissionCardResponse:
        """Process a user's response to a permission card.

        Args:
            channel: Which channel the response came from
            payload: The channel-native callback payload

        Returns:
            PermissionCardResponse with parsed action and responder

        Raises:
            ValueError: If channel is not supported
        """
        if channel not in self._renderers:
            raise ValueError(f"No renderer for channel: {channel}")
        renderer = self._renderers[channel]
        return await renderer.handle_response(payload)


class BaseCardRenderer(ABC):
    """Base class for channel-specific card renderers."""

    channel_name: str

    @abstractmethod
    async def render(self, card: PermissionCard) -> RenderedCard:
        """Render a permission card for this channel.

        Args:
            card: The permission card

        Returns:
            RenderedCard with channel-native payload
        """
        pass

    @abstractmethod
    async def handle_response(
        self, payload: dict[str, Any]
    ) -> PermissionCardResponse:
        """Parse a user's response to a rendered card.

        Args:
            payload: The channel callback payload

        Returns:
            PermissionCardResponse
        """
        pass

    def _tier_to_emoji(self, tier: str) -> str:
        """Map approval tier to emoji."""
        tier_emojis = {
            "LOW": "🟢",
            "MEDIUM": "🟡",
            "HIGH": "🔴",
            "CRITICAL": "🚨",
        }
        return tier_emojis.get(tier, "ℹ️")


class WhatsAppCardRenderer(BaseCardRenderer):
    """Render permission cards for WhatsApp using Evolution API.

    Uses WhatsApp interactive messages with button rows.
    Maximum 3 buttons per message.
    """

    channel_name = "whatsapp"

    async def render(self, card: PermissionCard) -> RenderedCard:
        """Render card as WhatsApp interactive message.

        Example payload:
        {
            "interactive": {
                "type": "button",
                "body": {
                    "text": "Approve invoice?"
                },
                "footer": {
                    "text": "Proposal ID: ..."
                },
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": "approve", "title": "✓ Approve"}},
                        {"type": "reply", "reply": {"id": "deny", "title": "✗ Deny"}},
                        {"type": "reply", "reply": {"id": "escalate", "title": "⬆ Escalate"}}
                    ]
                }
            }
        }
        """
        # Truncate to WhatsApp limits (interactive messages max 3 buttons)
        action_buttons = list(card.actions.items())[:3]

        buttons = [
            {
                "type": "reply",
                "reply": {
                    "id": action_key,
                    "title": action_label[:20],  # WhatsApp button text limit
                },
            }
            for action_key, action_label in action_buttons
        ]

        payload = {
            "interactive": {
                "type": "button",
                "body": {
                    "text": f"{self._tier_to_emoji(card.tier)} {card.title}\n\n{card.description}",
                },
                "footer": {
                    "text": f"ID: {card.proposal_id}",
                },
                "action": {
                    "buttons": buttons,
                },
            }
        }

        return RenderedCard(
            channel="whatsapp",
            payload=payload,
            interaction_id=card.proposal_id,
        )

    async def handle_response(
        self, payload: dict[str, Any]
    ) -> PermissionCardResponse:
        """Parse WhatsApp interactive message response.

        Expected payload from Evolution webhook:
        {
            "message": {
                "fromMe": false,
                "id": "...",
                "timestamp": 1234567890,
                "status": "RECEIVED",
                "body": "button_id",  # This is the action we took
                "messageType": "interactive"
            },
            "sender": {
                "id": "1234567890"
            }
        }
        """
        # Extract from WhatsApp message structure
        message = payload.get("message", {})
        sender_id = payload.get("sender", {}).get("id", "unknown")

        # The action is in the message body for WhatsApp interactive replies
        action = message.get("body", "unknown").lower()
        timestamp_seconds = message.get("timestamp", 0)

        return PermissionCardResponse(
            proposal_id=message.get("id", "unknown"),  # Proposal ID from metadata
            action=action,
            timestamp=datetime.fromtimestamp(timestamp_seconds) if timestamp_seconds else datetime.now(),
            responder=sender_id,
            channel="whatsapp",
        )


class SlackCardRenderer(BaseCardRenderer):
    """Render permission cards for Slack using Block Kit.

    Uses rich block layout with context, text, and action buttons.
    """

    channel_name = "slack"

    async def render(self, card: PermissionCard) -> RenderedCard:
        """Render card as Slack Block Kit message.

        Example:
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Approve Invoice?*\nVendor Acme $1000"
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve"},
                "value": "approve",
                "action_id": "card_approve_..."
            }
        }
        """
        action_buttons = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": action_label},
                "value": action_key,
                "action_id": f"card_{action_key}_{card.proposal_id}",
            }
            for action_key, action_label in card.actions.items()
        ]

        # Slack uses blocks array
        blocks = [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"{self._tier_to_emoji(card.tier)} Approval Required — {card.tier} tier",
                    }
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{card.title}*\n{card.description}",
                },
            },
            {
                "type": "divider",
            },
            {
                "type": "actions",
                "elements": action_buttons,
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Proposal: `{card.proposal_id}`",
                    }
                ],
            },
        ]

        payload = {
            "blocks": blocks,
        }

        return RenderedCard(
            channel="slack",
            payload=payload,
            interaction_id=card.proposal_id,
        )

    async def handle_response(
        self, payload: dict[str, Any]
    ) -> PermissionCardResponse:
        """Parse Slack block action response.

        Expected payload from Slack interactions:
        {
            "actions": [
                {
                    "type": "button",
                    "action_id": "card_approve_proposal-123",
                    "value": "approve"
                }
            ],
            "user": {
                "id": "U123456"
            },
            "trigger_id": "..."
        }
        """
        actions = payload.get("actions", [])
        if not actions:
            raise ValueError("No actions in Slack payload")

        action = actions[0]
        action_value = action.get("value", "unknown")
        user_id = payload.get("user", {}).get("id", "unknown")

        # Extract proposal ID from action_id (format: "card_approve_proposal-123")
        action_id = action.get("action_id", "")
        proposal_id = action_id.split("_", 2)[2] if "_" in action_id else "unknown"

        return PermissionCardResponse(
            proposal_id=proposal_id,
            action=action_value,
            timestamp=datetime.now(),
            responder=user_id,
            channel="slack",
        )


class SMSCardRenderer(BaseCardRenderer):
    """Render permission cards for SMS using text codes.

    SMS messages are short, so we use codes:
    Reply: A (Approve), D (Deny), E (Escalate)
    """

    channel_name = "sms"

    async def render(self, card: PermissionCard) -> RenderedCard:
        """Render card as SMS text with reply codes.

        Example:
        "Approval needed: Approve invoice? Vendor Acme $1000. Reply: A (Approve), D (Deny), E (Escalate). ID: proposal-123"
        """
        # Build reply codes from actions
        codes = []
        for i, (action_key, action_label) in enumerate(card.actions.items()):
            # Use first letter or provided code
            code = action_key[0].upper()
            codes.append(f"{code} ({action_label[:10]})")

        code_text = ", ".join(codes)

        message = f"{self._tier_to_emoji(card.tier)} {card.title}\n\n{card.description}\n\nReply: {code_text}\n\nID: {card.proposal_id}"

        payload = {
            "body": message,
            "proposal_id": card.proposal_id,
        }

        return RenderedCard(
            channel="sms",
            payload=payload,
            interaction_id=card.proposal_id,
        )

    async def handle_response(
        self, payload: dict[str, Any]
    ) -> PermissionCardResponse:
        """Parse SMS reply.

        Expected payload:
        {
            "from": "+1234567890",
            "body": "A",  # The code
            "proposal_id": "proposal-123"
        }
        """
        body = payload.get("body", "").strip().upper()

        # Map single letter to action
        code_to_action = {
            "A": "approve",
            "D": "deny",
            "E": "escalate",
        }

        action = code_to_action.get(body[0] if body else "", "unknown")

        return PermissionCardResponse(
            proposal_id=payload.get("proposal_id", "unknown"),
            action=action,
            timestamp=datetime.now(),
            responder=payload.get("from", "unknown"),
            channel="sms",
        )


class EmailCardRenderer(BaseCardRenderer):
    """Render permission cards for email using HTML + plain text.

    Includes clickable action links for web clients and instructions for reply-based actions.
    """

    channel_name = "email"

    async def render(self, card: PermissionCard) -> RenderedCard:
        """Render card as HTML + plain text email.

        Returns both formats for maximum compatibility.
        """
        # Build action links
        action_links = "\n".join(
            [
                f"<a href='https://app.wosool.ai/approvals/{card.proposal_id}?action={action_key}'>{action_label}</a>"
                for action_key, action_label in card.actions.items()
            ]
        )

        html_body = f"""
<html>
<body style="font-family: Arial, sans-serif; margin: 20px;">
    <h2>{card.title}</h2>
    <p style="color: #555;">{card.description}</p>

    <div style="margin: 20px 0; padding: 10px; background-color: #f0f0f0; border-left: 4px solid #007bff;">
        <strong>Actions:</strong><br/>
        {action_links}
    </div>

    <p style="color: #888; font-size: 12px;">
        Tier: <strong>{card.tier}</strong><br/>
        Proposal ID: <code>{card.proposal_id}</code>
    </p>
</body>
</html>
        """

        # Plain text fallback
        action_text = "\n".join(
            [
                f"- {action_label} (reply with '{action_key}')"
                for action_key, action_label in card.actions.items()
            ]
        )

        plain_body = f"""
{card.title}

{card.description}

Actions:
{action_text}

Tier: {card.tier}
Proposal ID: {card.proposal_id}

---
Reply to this email with your decision or click the link above.
        """

        payload = {
            "html": html_body,
            "plain": plain_body,
            "subject": f"Approval Needed: {card.title} [{card.tier}]",
            "proposal_id": card.proposal_id,
        }

        return RenderedCard(
            channel="email",
            payload=payload,
            interaction_id=card.proposal_id,
        )

    async def handle_response(
        self, payload: dict[str, Any]
    ) -> PermissionCardResponse:
        """Parse email response (reply body or link click).

        Expected payload:
        {
            "from": "user@example.com",
            "subject": "Re: Approval Needed: ...",
            "body": "approve",  # or "A", "Approve", etc.
            "proposal_id": "proposal-123"
        }
        """
        body = payload.get("body", "").strip().lower()

        # Normalize response
        action = body
        if body.startswith("a"):
            action = "approve"
        elif body.startswith("d"):
            action = "deny"
        elif body.startswith("e"):
            action = "escalate"

        return PermissionCardResponse(
            proposal_id=payload.get("proposal_id", "unknown"),
            action=action,
            timestamp=datetime.now(),
            responder=payload.get("from", "unknown"),
            channel="email",
        )
