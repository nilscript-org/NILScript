"""Invocation Parser — parse channel messages to extract cycle invocations.

An invocation is a user request to execute a cycle from a messaging channel.
Examples:
  - WhatsApp: "@wosool order Acme 100 units"
  - Slack: "@wosool-bot order Acme 100 units"
  - SMS: "wosool: order Acme 100 units"
  - Email: Subject: "Cycle: order Acme 100 units"

The parser:
1. Recognizes the invocation syntax per channel
2. Extracts the cycle name and parameters
3. Fills in missing parameters from thread context
4. Returns a confidence score
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InvocationMatch:
    """A detected cycle invocation in a channel message."""

    intent: str
    """The detected intent. Currently only 'ExecuteCycle' is supported."""

    cycle_name: str
    """The name of the cycle to execute (e.g., 'order', 'approve_invoice')."""

    parameters: dict[str, Any] = field(default_factory=dict)
    """Extracted parameters from the message."""

    channel: str = ""
    """The channel this came from (whatsapp, slack, email, sms)."""

    sender: str = ""
    """Who sent this message."""

    confidence: float = 1.0
    """How confident we are in this match [0.0, 1.0]."""

    raw_message: str = ""
    """The original message text."""


class InvocationParser:
    """Parse channel messages for cycle invocations.

    Supports multiple invocation patterns per channel:
    - WhatsApp: "@wosool" prefix, slash commands
    - Slack: "@wosool-bot" mention, slash commands, threads
    - SMS: "wosool:" prefix, short codes
    - Email: Subject line parsing, body parsing
    """

    # Invocation prefixes per channel
    WHATSAPP_PREFIXES = [r"@wosool\b", r"/wosool\b", r"wosool:"]
    SLACK_PREFIXES = [r"@wosool-bot\b", r"/wosool\b", r"wosool:"]
    SMS_PREFIXES = [r"^wosool:\s*", r"^WOSOOL:\s*"]
    EMAIL_PREFIXES = [r"^Cycle:\s*", r"^cycle:\s*"]

    def __init__(self) -> None:
        """Initialize the parser with channel-specific patterns."""
        self.cycle_name_pattern = re.compile(r"^[a-z][a-z0-9_-]*$", re.IGNORECASE)

    def parse(self, message: str, channel: str, sender: str = "") -> InvocationMatch | None:
        """Parse a message and extract cycle invocation.

        Args:
            message: The message text to parse
            channel: The channel it came from (whatsapp, slack, email, sms)
            sender: Who sent the message (optional)

        Returns:
            InvocationMatch if a cycle invocation was detected, None otherwise
        """
        if not message or not channel:
            return None

        # Try channel-specific parsing
        if channel == "whatsapp":
            return self._parse_whatsapp(message, sender)
        elif channel == "slack":
            return self._parse_slack(message, sender)
        elif channel == "sms":
            return self._parse_sms(message, sender)
        elif channel == "email":
            return self._parse_email(message, sender)
        else:
            # Generic parsing for unknown channels
            return self._parse_generic(message, channel, sender)

    def _parse_whatsapp(self, message: str, sender: str) -> InvocationMatch | None:
        """Parse WhatsApp message for invocation.

        Examples:
          @wosool order Acme 100 units
          /order Acme 100 units
          wosool: order Acme 100 units
        """
        # Try each prefix pattern
        for prefix_pattern in self.WHATSAPP_PREFIXES:
            match = re.search(prefix_pattern, message)
            if match:
                # Extract everything after the prefix
                rest = message[match.end():].strip()
                return self._extract_cycle_and_params(
                    rest, "whatsapp", sender, message
                )
        return None

    def _parse_slack(self, message: str, sender: str) -> InvocationMatch | None:
        """Parse Slack message for invocation.

        Slack messages come with @mentions already stripped by the Bolt framework,
        so we look for slash commands or direct text invocation.
        """
        # Try each prefix pattern
        for prefix_pattern in self.SLACK_PREFIXES:
            match = re.search(prefix_pattern, message)
            if match:
                rest = message[match.end():].strip()
                return self._extract_cycle_and_params(
                    rest, "slack", sender, message
                )
        return None

    def _parse_sms(self, message: str, sender: str) -> InvocationMatch | None:
        """Parse SMS message for invocation.

        SMS messages are short and may use codes:
          wosool: order Acme 100
          wosool: approve 1000
        """
        # Try each prefix pattern
        for prefix_pattern in self.SMS_PREFIXES:
            match = re.match(prefix_pattern, message)
            if match:
                rest = message[match.end():].strip()
                return self._extract_cycle_and_params(
                    rest, "sms", sender, message, confidence=0.95
                )
        return None

    def _parse_email(self, message: str, sender: str) -> InvocationMatch | None:
        """Parse email for invocation.

        Email subject or body:
          Subject: Cycle: order Acme 100
          Subject: cycle: order Acme 100
        """
        lines = message.split("\n")
        for line in lines:
            line = line.strip()
            for prefix_pattern in self.EMAIL_PREFIXES:
                match = re.match(prefix_pattern, line)
                if match:
                    rest = line[match.end():].strip()
                    return self._extract_cycle_and_params(
                        rest, "email", sender, message, confidence=0.90
                    )
        return None

    def _parse_generic(
        self, message: str, channel: str, sender: str
    ) -> InvocationMatch | None:
        """Generic parsing for unknown channels.

        Just look for cycle names and basic structure.
        """
        words = message.split()
        if not words:
            return None

        first_word = words[0].lower()
        if self.cycle_name_pattern.match(first_word):
            return self._extract_cycle_and_params(
                message, channel, sender, message, confidence=0.70
            )
        return None

    def _extract_cycle_and_params(
        self,
        text: str,
        channel: str,
        sender: str,
        raw_message: str,
        confidence: float = 1.0,
    ) -> InvocationMatch | None:
        """Extract cycle name and parameters from text.

        Expected format:
          cycle_name param1 value1 param2 value2 ...

        Examples:
          order Acme 100 units
          approve_invoice vendor=Acme amount=1000
          send_message recipient=+1234567890 body="Hello"
        """
        words = text.split()
        if not words:
            return None

        cycle_name = words[0].lower()
        if not self.cycle_name_pattern.match(cycle_name):
            return None

        parameters = {}
        remaining_words = words[1:]

        # Try to parse key=value pairs
        for word in remaining_words:
            if "=" in word:
                key, value = word.split("=", 1)
                parameters[key.lower()] = value
            else:
                # Positional parameters (harder to parse without schema)
                # For now, store them with generic keys
                key = f"param_{len(parameters)}"
                parameters[key] = word

        return InvocationMatch(
            intent="ExecuteCycle",
            cycle_name=cycle_name,
            parameters=parameters,
            channel=channel,
            sender=sender,
            confidence=confidence,
            raw_message=raw_message,
        )

    def fill_missing_slots(
        self,
        match: InvocationMatch,
        thread_context: dict[str, Any],
    ) -> InvocationMatch:
        """Use thread context to fill in missing parameters.

        If a cycle requires certain parameters (e.g., vendor_id, amount) and the
        user didn't provide them in the message, try to extract them from:
        1. Previous messages in the thread
        2. Thread metadata (who is this thread between?)
        3. Derived values (e.g., total from line items)

        Args:
            match: The initial invocation match
            thread_context: Context from the thread (previous messages, metadata, etc.)

        Returns:
            Updated InvocationMatch with additional parameters filled in
        """
        # Make a copy to avoid mutating the original
        updated_match = InvocationMatch(
            intent=match.intent,
            cycle_name=match.cycle_name,
            parameters=dict(match.parameters),
            channel=match.channel,
            sender=match.sender,
            confidence=match.confidence,
            raw_message=match.raw_message,
        )

        # Try to extract common parameters from thread context
        if not updated_match.parameters.get("vendor") and thread_context.get("vendor"):
            updated_match.parameters["vendor"] = thread_context["vendor"]

        if not updated_match.parameters.get("vendor_id") and thread_context.get("vendor_id"):
            updated_match.parameters["vendor_id"] = thread_context["vendor_id"]

        if not updated_match.parameters.get("amount") and thread_context.get("amount"):
            updated_match.parameters["amount"] = thread_context["amount"]

        if not updated_match.parameters.get("recipient") and thread_context.get("recipient"):
            updated_match.parameters["recipient"] = thread_context["recipient"]

        # Increase confidence if we filled in parameters from context
        if len(updated_match.parameters) > len(match.parameters):
            updated_match.confidence = min(1.0, updated_match.confidence + 0.1)

        return updated_match

    def extract_from_subject_line(self, subject: str) -> InvocationMatch | None:
        """Extract cycle invocation from email subject line.

        Email subjects are often the first signal of intent.

        Args:
            subject: The email subject line

        Returns:
            InvocationMatch if detected, None otherwise
        """
        # Try email-specific parsing on the subject
        return self._parse_email(subject, "")

    def list_supported_channels(self) -> list[str]:
        """List channels this parser supports.

        Returns:
            List of supported channel names
        """
        return ["whatsapp", "slack", "sms", "email"]
