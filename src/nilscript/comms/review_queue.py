"""Wave 7: Correlation Review Queue — manage ambiguous correlations.

When a message matches multiple threads (ambiguous correlation), it enters the review queue
waiting for a human to pick the correct thread. Once resolved, a deterministic event is issued
and the thread resumes.

Design principle: Review items are time-bounded (3 days default), searchable by thread/workspace,
and track decision provenance.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Literal, TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from nilscript.comms.passive_events import CommunicationReceivedEvent


class ReviewQueueItem(BaseModel):
    """A message waiting for human clarification: which thread does it belong to?

    Lifecycle:
      pending -> (human picks) -> resolved -> (converted to event)
      pending -> (expires) -> expired

    Note: Uses BaseModel (not DslModel) to allow mutation (status, resolved_at, etc.)
    """

    id: str  # UUID
    message: dict  # The incoming message {sender, body, subject, channel, timestamp}
    candidates: list[dict] = Field(
        default_factory=list,
        description="Possible threads: [{'thread_id': '...', 'business_ref': 'PO-001', 'confidence': 0.85}, ...]",
    )
    status: Literal["pending", "resolved", "expired", "rejected"] = "pending"
    human_decision: str | None = None  # Which thread_id the human picked (only if resolved)
    correlation_id: str  # From CorrelationEngine.correlate()
    reason_for_ambiguity: str | None = None  # Why was this ambiguous? (debug)

    # Temporal metadata
    created_at: datetime
    expires_at: datetime  # 3 days default
    resolved_at: datetime | None = None
    resolved_by: str | None = None  # User ID / actor who resolved it

    # Associated event (created after resolution)
    event_id: str | None = None


class ReviewQueue:
    """Manage ambiguous correlations — a time-bounded, interactive review surface."""

    def __init__(self, ttl_hours: int = 72):
        """Initialize the review queue.

        Args:
            ttl_hours: How long to keep pending items before expiry (default 72h = 3 days)
        """
        self.items: dict[str, ReviewQueueItem] = {}  # id -> ReviewQueueItem
        self.by_thread: dict[str, list[str]] = {}  # thread_id -> [review_item_ids] (for filtering)
        self.by_workspace: dict[str, list[str]] = {}  # workspace -> [review_item_ids]
        self.ttl_hours = ttl_hours

    def add_to_review(
        self,
        message: dict,
        candidates: list[dict],
        correlation_id: str,
        workspace: str = "default",
        reason: str | None = None,
    ) -> ReviewQueueItem:
        """Add an ambiguous message to the review queue.

        Args:
            message: The incoming message {sender, body, subject, channel, timestamp}
            candidates: Ambiguous thread candidates [{thread_id, business_ref, confidence}, ...]
            correlation_id: From the CorrelationEngine
            workspace: Workspace ID (for filtering)
            reason: Human-readable reason for ambiguity (debug)

        Returns:
            The ReviewQueueItem
        """
        item_id = str(uuid.uuid4())
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=self.ttl_hours)

        item = ReviewQueueItem(
            id=item_id,
            message=message,
            candidates=candidates,
            status="pending",
            correlation_id=correlation_id,
            reason_for_ambiguity=reason,
            created_at=now,
            expires_at=expires_at,
        )

        self.items[item_id] = item

        # Index by workspace
        if workspace not in self.by_workspace:
            self.by_workspace[workspace] = []
        self.by_workspace[workspace].append(item_id)

        # Index by thread (for each candidate)
        for cand in candidates:
            thread_id = cand.get("thread_id")
            if thread_id:
                if thread_id not in self.by_thread:
                    self.by_thread[thread_id] = []
                self.by_thread[thread_id].append(item_id)

        return item

    def resolve(
        self, review_item_id: str, chosen_thread_id: str, resolved_by: str = "unknown"
    ) -> BaseModel | None:
        """Human picks the correct thread; emit a resume event.

        Args:
            review_item_id: The ReviewQueueItem.id
            chosen_thread_id: The thread_id the human selected
            resolved_by: User ID / actor making the decision

        Returns:
            The CommunicationReceivedEvent that will resume the thread (ready for ledger commit)
        """
        item = self.items.get(review_item_id)
        if not item:
            return None

        if item.status != "pending":
            return None

        now = datetime.utcnow()
        item.status = "resolved"
        item.human_decision = chosen_thread_id
        item.resolved_at = now
        item.resolved_by = resolved_by

        # Create the resume event
        from nilscript.comms.passive_events import create_passive_resume_event

        correlation_result = {
            "thread_id": chosen_thread_id,
            "correlation_id": item.correlation_id,
            "matched_on": "HUMAN_REVIEW",
            "confidence": 1.0,
            "layers_matched": [],
        }

        event = create_passive_resume_event(item.message, chosen_thread_id, correlation_result)
        item.event_id = event.event_id

        return event

    def reject(self, review_item_id: str, resolved_by: str = "unknown") -> bool:
        """Mark an item as rejected (not a real message, spam, etc.).

        Args:
            review_item_id: The ReviewQueueItem.id
            resolved_by: User ID / actor rejecting it

        Returns:
            True if rejected, False if item not found
        """
        item = self.items.get(review_item_id)
        if not item:
            return False

        item.status = "rejected"
        item.resolved_at = datetime.utcnow()
        item.resolved_by = resolved_by
        return True

    def list_pending(
        self, thread_id: str | None = None, workspace: str | None = None
    ) -> list[ReviewQueueItem]:
        """Get all pending reviews, optionally filtered by thread or workspace.

        Args:
            thread_id: Filter to reviews for this thread (optional)
            workspace: Filter to reviews in this workspace (optional)

        Returns:
            List of pending ReviewQueueItems
        """
        if thread_id:
            item_ids = self.by_thread.get(thread_id, [])
        elif workspace:
            item_ids = self.by_workspace.get(workspace, [])
        else:
            item_ids = list(self.items.keys())

        pending = []
        for item_id in item_ids:
            item = self.items.get(item_id)
            if item and item.status == "pending":
                pending.append(item)

        return sorted(pending, key=lambda x: x.created_at, reverse=True)

    def get_pending_count(self, workspace: str | None = None) -> int:
        """Get the number of pending reviews."""
        return len(self.list_pending(workspace=workspace))

    def cleanup_expired(self) -> int:
        """Mark expired items as 'expired' and return count.

        Run periodically to clean up old pending items.

        Returns:
            Number of items marked as expired
        """
        now = datetime.utcnow()
        expired_count = 0

        for item in self.items.values():
            if item.status == "pending" and item.expires_at <= now:
                item.status = "expired"
                expired_count += 1

        return expired_count

    def get_item(self, review_item_id: str) -> ReviewQueueItem | None:
        """Get a specific review item by ID."""
        return self.items.get(review_item_id)

    def get_all_by_status(self, status: Literal["pending", "resolved", "expired", "rejected"]) -> list[ReviewQueueItem]:
        """Get all items with a specific status."""
        return [item for item in self.items.values() if item.status == status]


# Convenience function for a UI endpoint: list pending reviews for display
def pending_reviews_for_display(
    review_queue: ReviewQueue, workspace: str
) -> list[dict]:
    """Format pending reviews for UI display.

    Returns a list of dicts with essential info for a human to make a decision.
    """
    pending = review_queue.list_pending(workspace=workspace)
    return [
        {
            "id": item.id,
            "sender": item.message.get("sender", "unknown"),
            "subject": item.message.get("subject", ""),
            "body_preview": item.message.get("body", "")[:100],
            "channel": item.message.get("channel", "email"),
            "received_at": item.message.get("received_at"),
            "candidates": [
                {
                    "thread_id": c["thread_id"],
                    "business_ref": c.get("business_ref"),
                    "confidence": c.get("confidence"),
                }
                for c in item.candidates
            ],
            "created_at": item.created_at.isoformat(),
            "expires_at": item.expires_at.isoformat(),
            "reason_for_ambiguity": item.reason_for_ambiguity,
        }
        for item in pending
    ]


# API-like interface (as if exposed by os-server)
class ReviewQueueAPI:
    """RESTful-ish API for the review queue (would be exposed by os-server)."""

    def __init__(self, review_queue: ReviewQueue):
        self.queue = review_queue

    def list_pending(self, workspace: str, thread_id: str | None = None) -> list[dict]:
        """GET /api/review-queue/pending?workspace=ws_acme&thread_id=...

        Args:
            workspace: Workspace to filter by
            thread_id: Optional thread filter

        Returns:
            List of pending review items for display
        """
        items = self.queue.list_pending(thread_id=thread_id, workspace=workspace)
        return [
            {
                "id": item.id,
                "sender": item.message.get("sender"),
                "subject": item.message.get("subject"),
                "candidates": [
                    {"thread_id": c["thread_id"], "business_ref": c.get("business_ref")}
                    for c in item.candidates
                ],
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ]

    def resolve(self, workspace: str, review_item_id: str, chosen_thread_id: str) -> dict:
        """POST /api/review-queue/{review_item_id}/resolve

        Args:
            workspace: Workspace (for validation)
            review_item_id: The review item ID
            chosen_thread_id: The selected thread

        Returns:
            {ok: True, event_id: "...", thread_id: "..."} or {ok: False, error: "..."}
        """
        item = self.queue.get_item(review_item_id)
        if not item:
            return {"ok": False, "error": "Review item not found"}

        event = self.queue.resolve(review_item_id, chosen_thread_id, resolved_by=workspace)
        if not event:
            return {"ok": False, "error": "Could not resolve item"}

        return {"ok": True, "event_id": event.event_id, "thread_id": chosen_thread_id}

    def get_stats(self, workspace: str) -> dict:
        """GET /api/review-queue/stats?workspace=ws_acme

        Returns:
            {pending: N, resolved: N, expired: N, oldest_pending_age_minutes: N}
        """
        pending_items = self.queue.list_pending(workspace=workspace)
        resolved = len(self.queue.get_all_by_status("resolved"))
        expired = len(self.queue.get_all_by_status("expired"))

        oldest_age_minutes = None
        if pending_items:
            oldest = min(pending_items, key=lambda x: x.created_at)
            age = datetime.utcnow() - oldest.created_at
            oldest_age_minutes = int(age.total_seconds() / 60)

        return {
            "pending": len(pending_items),
            "resolved": resolved,
            "expired": expired,
            "oldest_pending_age_minutes": oldest_age_minutes,
        }
