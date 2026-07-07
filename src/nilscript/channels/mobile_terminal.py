"""Mobile Terminal — thin client into the Wosool Kernel.

The mobile app is designed as a lightweight terminal that talks to the backend kernel.
It provides:
1. Thread browsing and filtering
2. Thread detail view (timeline + documents + approvals + messages)
3. Approval responses (approve/deny/escalate)
4. Message replies
5. Thread search

This is NOT a rich editor — cycles are edited in the web UI. The mobile app is for
execution, approval, and communication.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ThreadStatus(str, Enum):
    """Thread status enum."""

    ACTIVE = "active"
    PENDING_APPROVAL = "pending_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class ApprovalStatus(str, Enum):
    """Approval status enum."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    ESCALATED = "escalated"


class ThreadSummary(BaseModel):
    """Brief summary of a thread for list view."""

    thread_id: str = Field(description="Unique thread ID")
    cycle_name: str = Field(description="Name of the cycle (e.g., 'order')")
    subject: str = Field(description="Human-readable subject")
    status: ThreadStatus = Field(description="Current status")
    last_update: datetime = Field(description="When was this last updated")
    pending_approvals: int = Field(default=0, description="How many approvals are waiting")
    unread_messages: int = Field(default=0, description="New messages in this thread")
    participants: list[str] = Field(default_factory=list, description="People involved")
    business_ref: str | None = Field(
        default=None, description="External reference (order number, etc.)"
    )


class DocumentRef(BaseModel):
    """Reference to a document in a thread."""

    document_id: str = Field(description="Unique document ID")
    title: str = Field(description="Document title")
    mime_type: str = Field(description="Document MIME type (e.g., 'application/pdf')")
    size_bytes: int = Field(description="File size in bytes")
    uploaded_at: datetime = Field(description="When uploaded")
    uploaded_by: str = Field(description="Who uploaded it")


class TimelineEvent(BaseModel):
    """A single event in the thread timeline."""

    event_id: str = Field(description="Unique event ID")
    event_type: str = Field(
        description="Type of event (message, step_completed, approval_needed, etc.)"
    )
    timestamp: datetime = Field(description="When it happened")
    actor: str | None = Field(default=None, description="Who caused this event")
    title: str = Field(description="Short title")
    description: str = Field(description="Longer description")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Event-specific data")


class ApprovalProposal(BaseModel):
    """An approval proposal (governance gate) waiting for response."""

    proposal_id: str = Field(description="Unique proposal ID")
    title: str = Field(description="What is being approved")
    description: str = Field(description="Details")
    tier: str = Field(description="Approval tier (LOW, MEDIUM, HIGH, CRITICAL)")
    status: ApprovalStatus = Field(description="Current status")
    created_at: datetime = Field(description="When proposal was created")
    expires_at: datetime | None = Field(default=None, description="When decision is required")
    actions: dict[str, str] = Field(
        description="Available actions {key: label}"
    )


class Message(BaseModel):
    """A message in the thread."""

    message_id: str = Field(description="Unique message ID")
    sender: str = Field(description="Who sent it")
    sender_name: str | None = Field(default=None, description="Display name")
    body: str = Field(description="Message content")
    timestamp: datetime = Field(description="When sent")
    channel: str = Field(description="Which channel (whatsapp, email, slack, web)")
    is_read: bool = Field(default=True, description="Has user read this")


class ThreadDetail(BaseModel):
    """Full thread detail with timeline, approvals, documents, and messages."""

    thread_id: str = Field(description="Unique thread ID")
    cycle_name: str = Field(description="Cycle name")
    subject: str = Field(description="Thread subject")
    business_ref: str | None = Field(default=None, description="External reference")
    status: ThreadStatus = Field(description="Current status")
    created_at: datetime = Field(description="When thread was created")
    created_by: str = Field(description="Who created it")
    updated_at: datetime = Field(description="Last update time")

    # Thread participants
    participants: list[dict[str, str]] = Field(
        default_factory=list, description="List of {id, name, role}"
    )

    # Timeline of events
    timeline: list[TimelineEvent] = Field(
        default_factory=list, description="Events in chronological order"
    )

    # Pending approvals
    approvals: list[ApprovalProposal] = Field(
        default_factory=list, description="Approval proposals"
    )

    # Attached documents
    documents: list[DocumentRef] = Field(
        default_factory=list, description="Documents attached to thread"
    )

    # Message history (most recent first)
    messages: list[Message] = Field(
        default_factory=list, description="Messages in thread"
    )

    # Additional metadata
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Extra thread-specific data"
    )


class MobileTerminal:
    """Mobile app API surface into the Kernel.

    All methods are async and represent network calls to the backend.
    The mobile app authenticates via token and filters by workspace/permissions.
    """

    async def fetch_threads(
        self,
        workspace_id: str,
        filter_by: dict[str, Any] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ThreadSummary], int]:
        """Fetch threads for a workspace with optional filtering.

        Args:
            workspace_id: The workspace to fetch from
            filter_by: Optional filters:
                - status: ThreadStatus (active, pending_approval, completed, etc.)
                - assigned_to: str (user ID)
                - cycle_name: str (filter by cycle)
                - business_ref: str (filter by external ref)
                - unread_only: bool (only unread threads)
            limit: Maximum threads to return (default 20)
            offset: Pagination offset (default 0)

        Returns:
            Tuple of (threads, total_count) for pagination

        Raises:
            AuthError: If user is not authorized for this workspace
        """
        pass

    async def fetch_thread_detail(self, thread_id: str) -> ThreadDetail:
        """Fetch full thread detail.

        Args:
            thread_id: The thread to fetch

        Returns:
            ThreadDetail with all timeline, approvals, documents, messages

        Raises:
            NotFoundError: If thread doesn't exist
            AuthError: If user is not authorized to view this thread
        """
        pass

    async def send_approval_response(
        self,
        proposal_id: str,
        action: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """Send approval response to a governance gate.

        Args:
            proposal_id: The proposal ID
            action: The action (approve, deny, escalate)
            comment: Optional comment with the decision

        Returns:
            Response metadata

        Raises:
            NotFoundError: If proposal doesn't exist
            ValidationError: If action is invalid
        """
        pass

    async def send_message(
        self,
        thread_id: str,
        body: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Send a message in a thread.

        Args:
            thread_id: Which thread to message
            body: Message content
            attachments: Optional file attachments [{file_name, mime_type, data_url}, ...]

        Returns:
            The sent Message object

        Raises:
            NotFoundError: If thread doesn't exist
            ValidationError: If message is too long
        """
        pass

    async def search_threads(
        self,
        workspace_id: str,
        query: str,
        limit: int = 10,
    ) -> list[ThreadSummary]:
        """Search threads by business_ref, subject, or participant names.

        Args:
            workspace_id: Search in this workspace
            query: Search query (e.g., "order-123", "acme", "john")
            limit: Max results (default 10)

        Returns:
            List of matching ThreadSummary objects

        Raises:
            ValidationError: If query is too short
        """
        pass

    async def mark_thread_read(self, thread_id: str) -> None:
        """Mark all messages in a thread as read.

        Args:
            thread_id: The thread to mark

        Raises:
            NotFoundError: If thread doesn't exist
        """
        pass

    async def fetch_document(self, document_id: str) -> bytes:
        """Download a document from a thread.

        Args:
            document_id: The document to download

        Returns:
            Binary file content

        Raises:
            NotFoundError: If document doesn't exist
            AuthError: If user is not authorized
        """
        pass

    async def list_my_pending_approvals(self, workspace_id: str) -> list[ApprovalProposal]:
        """List all pending approvals assigned to the current user.

        Returns:
            List of ApprovalProposal with status=PENDING

        Raises:
            AuthError: If user is not authorized for this workspace
        """
        pass


class MobileNotification:
    """Push notifications to the mobile app."""

    async def approval_needed(
        self,
        proposal_id: str,
        title: str,
        tier: str,
        recipient_user_id: str,
    ) -> None:
        """Notify user of a pending approval.

        Args:
            proposal_id: The proposal ID
            title: Notification title
            tier: Approval tier (for icon/color)
            recipient_user_id: Who to notify
        """
        pass

    async def thread_updated(
        self,
        thread_id: str,
        event: str,
        title: str,
        recipient_user_id: str | None = None,
    ) -> None:
        """Notify user that a thread was updated.

        Args:
            thread_id: Which thread changed
            event: What happened (message_added, step_completed, approval_completed, etc.)
            title: Notification title
            recipient_user_id: Who to notify (if None, notify all participants)
        """
        pass

    async def message_received(
        self,
        thread_id: str,
        sender_name: str,
        preview: str,
        recipient_user_id: str,
    ) -> None:
        """Notify user of a new message in a thread.

        Args:
            thread_id: Which thread
            sender_name: Who sent it
            preview: First ~50 chars of the message
            recipient_user_id: Who to notify
        """
        pass


class MobileTerminalConfig(BaseModel):
    """Configuration for mobile terminal."""

    base_url: str = Field(description="Backend API base URL")
    api_version: str = Field(default="v1", description="API version")
    timeout_seconds: int = Field(default=30, description="Request timeout")
    max_message_length: int = Field(default=5000, description="Max chars per message")
    max_attachment_size_mb: int = Field(
        default=10, description="Max file upload size"
    )
    push_notification_enabled: bool = Field(
        default=True, description="Enable push notifications"
    )
