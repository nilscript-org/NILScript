"""Wave 6 §4: Permission Cards — Governance Gates Bridging Policy to Execution.

When a policy decision returns NeedsApproval, a Permission Card is created.
The card contains:
- What is being asked (action, resource, tier)
- Who is asking (actor and their authority)
- Who needs to approve (list of approvers)
- When approval expires (deadline)
- UI-friendly rendering (title, description, preview data)

Permission Cards live in the thread as governance context — visible to all
participants, updated as approvals come in, and resolved to Allow or Deny.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from nilscript.authority.layers import AuthorityLevel
from nilscript.authority.policy import Verdict, VerdictKind


class PermissionCard(BaseModel):
    """A governance gate — request for human approval.

    Permission Cards are immutable once created. Status transitions are:
    pending → approved → execution
    pending → approved (partial) → approved (all) → execution
    pending → rejected (authority override)
    pending → expired (deadline reached)
    """

    # Identity
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique card ID",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the card was created (UTC)",
    )

    # Request details
    action: str = Field(..., description="What action is being requested")
    resource: str = Field(..., description="What resource")
    actor_id: str = Field(..., description="Who is requesting it")
    tier: AuthorityLevel = Field(..., description="Governance tier")
    actor_authority_level: AuthorityLevel = Field(
        ..., description="Requester's max authority"
    )

    # Decision details
    approvers: list[str] = Field(
        default_factory=list,
        description="Who needs to approve (actor IDs or roles)",
    )
    approvals: dict[str, datetime] = Field(
        default_factory=dict,
        description="Approvals received (actor_id -> approval_timestamp)",
    )
    deadline: datetime = Field(
        ..., description="When approval expires (UTC)"
    )
    status: Literal["pending", "approved", "rejected", "expired"] = Field(
        default="pending",
        description="Card status",
    )

    # UI rendering
    title: str = Field(..., description="UI title (e.g., Approve High-Tier Purchase)")
    description: str = Field(
        default="", description="UI description (e.g., reason for request)"
    )
    preview: dict[str, Any] = Field(
        default_factory=dict,
        description="Data preview for UI (cycle params, estimated cost, etc.)",
    )

    # Audit trail
    rejection_reason: str = Field(
        default="", description="If rejected, why"
    )

    def approval_count(self) -> int:
        """How many approvals received so far."""
        return len(self.approvals)

    def is_fully_approved(self) -> bool:
        """Has everyone on the approvers list approved?"""
        return self.approval_count() == len(self.approvers) and self.approval_count() > 0

    def is_expired(self, now: datetime | None = None) -> bool:
        """Has the approval deadline passed?"""
        now = now or datetime.utcnow()
        return now > self.deadline

    def add_approval(self, approver_id: str, now: datetime | None = None) -> None:
        """Record an approval from an approver (in-place mutation).

        Raises ValueError if:
        - Card is not pending
        - Approver is not in the approvers list
        - Approver already approved
        """
        if self.status != "pending":
            raise ValueError(f"Cannot approve: card status is {self.status}")
        if approver_id not in self.approvers:
            raise ValueError(f"Approver {approver_id} is not on the approvers list")
        if approver_id in self.approvals:
            raise ValueError(f"Approver {approver_id} already approved")

        now = now or datetime.utcnow()
        self.approvals[approver_id] = now

        # Update status if fully approved
        if self.is_fully_approved():
            self.status = "approved"

    def reject(self, reason: str = "", now: datetime | None = None) -> None:
        """Reject the approval request (in-place mutation).

        Raises ValueError if card is not pending.
        """
        if self.status != "pending":
            raise ValueError(f"Cannot reject: card status is {self.status}")
        self.status = "rejected"
        self.rejection_reason = reason

    def mark_expired(self) -> None:
        """Mark card as expired if deadline has passed (in-place mutation).

        Raises ValueError if card is not pending.
        """
        if self.status != "pending":
            raise ValueError(f"Cannot expire: card status is {self.status}")
        self.status = "expired"


def create_permission_card_if_needed(
    verdict: Verdict,
    action: str,
    resource: str,
    actor_id: str,
    actor_authority_level: AuthorityLevel,
    tier: AuthorityLevel = AuthorityLevel.LOW,
    title: str = "",
    description: str = "",
    preview: dict[str, Any] | None = None,
    deadline_hours: int = 24,
) -> PermissionCard | None:
    """If policy says NeedsApproval, create a Permission Card.

    Args:
        verdict: Policy Engine Verdict
        action: Action being requested
        resource: Resource being accessed
        actor_id: Actor ID of requester
        actor_authority_level: Requester's max authority level
        tier: Governance tier of this request
        title: UI title for the card
        description: UI description
        preview: UI preview data (cycle parameters, cost estimate, etc.)
        deadline_hours: How many hours until approval expires (default 24)

    Returns:
        PermissionCard if verdict.kind == NeedsApproval, else None
    """
    if verdict.kind != VerdictKind.NEEDS_APPROVAL:
        return None

    return PermissionCard(
        action=action,
        resource=resource,
        actor_id=actor_id,
        actor_authority_level=actor_authority_level,
        tier=tier,
        approvers=verdict.approvers,
        deadline=datetime.utcnow() + timedelta(hours=deadline_hours),
        title=title or f"Approval needed: {action} on {resource}",
        description=description or verdict.reason,
        preview=preview or {},
    )


def permission_cards_for_actor(
    cards: list[PermissionCard], actor_id: str
) -> list[PermissionCard]:
    """Filter Permission Cards relevant to an actor (they're an approver).

    Returns cards where:
    - Status is "pending"
    - actor_id is in the approvers list
    - Deadline has not passed
    """
    relevant = []
    now = datetime.utcnow()
    for card in cards:
        if (
            card.status == "pending"
            and actor_id in card.approvers
            and not card.is_expired(now)
        ):
            relevant.append(card)
    return relevant


def permission_cards_pending_actor(
    cards: list[PermissionCard], actor_id: str
) -> list[PermissionCard]:
    """Filter Permission Cards that an actor created (they're waiting for approval).

    Returns cards where:
    - Status is "pending"
    - actor_id == card.actor_id (they initiated it)
    - Deadline has not passed
    """
    pending = []
    now = datetime.utcnow()
    for card in cards:
        if (
            card.status == "pending"
            and card.actor_id == actor_id
            and not card.is_expired(now)
        ):
            pending.append(card)
    return pending
