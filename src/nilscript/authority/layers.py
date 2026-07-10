"""Wave 6 §2: Authority Hierarchy Layers L3–L7.

L3: Authority Level — max governance tier this actor can approve
L4: Capability-scoped grants — fine-grained permission by capability
L5: Thread-relationship grants — permissions scoped to specific threads
L6: Time-scoped permissions — temporary, deadline-bound grants
L7: Delegation chains — transitive approval delegation

The ActorAuthority model bundles all 7 layers for a single actor, enabling
explainable access control decisions with full traceability.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class AuthorityLevel(str, Enum):
    """L3: Maximum governance tier this actor can approve.

    Tier hierarchy (ascending): LOW → MEDIUM → HIGH → CRITICAL

    An actor with authority level HIGH can approve LOW and MEDIUM tiers,
    but never CRITICAL. CRITICAL requires multiple approvers or escalation.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RoleBundle(BaseModel):
    """L2: Named collection of permissions and authority.

    A role bundles related capabilities with a consistent authority level.
    Examples: FinanceApprover, ProcurementManager, DataAnalyst.
    """

    name: str = Field(..., description="Role name (e.g., FinanceApprover)")
    permissions: list[str] = Field(
        default_factory=list,
        description="Granted permissions (e.g., [cycle.write, proposal.approve])",
    )
    authority_level: AuthorityLevel = Field(
        default=AuthorityLevel.LOW,
        description="Max tier this role can approve",
    )
    description: str = Field(default="", description="Role documentation")


class CapabilityScopeGrant(BaseModel):
    """L4: Capability-scoped permission grant.

    Grants fine-grained authority by capability. If a user can approve
    HIGH-tier cycles but only MEDIUM-tier procurement orders, this is encoded here.
    """

    capability: str = Field(..., description="Capability name (e.g., procurement.create_invoice)")
    authority_level: AuthorityLevel = Field(
        default=AuthorityLevel.LOW,
        description="Max tier for this specific capability",
    )


class ThreadRelationshipGrant(BaseModel):
    """L5: Permission scoped to a specific thread (cycle or case).

    Users can have special relationships to threads (owner, participant, observer).
    Permissions are then scoped to that relationship within that thread.
    """

    thread_id: str = Field(..., description="Thread ID (e.g., cycle:12345 or case:xyz)")
    relationships: list[str] = Field(
        default_factory=list,
        description="Relationships in this thread (e.g., [owner, participant])",
    )


class TimeScopedGrant(BaseModel):
    """L6: Temporary, deadline-bound permission grant.

    Used for temporary escalations, emergency access, or seasonal approvals.
    Grants automatically expire after the deadline.
    """

    action: str = Field(..., description="Action being granted (e.g., approve, execute)")
    authority_level: AuthorityLevel = Field(
        default=AuthorityLevel.LOW,
        description="Authority level for this action",
    )
    valid_until: datetime = Field(..., description="When this grant expires (UTC)")
    reason: str = Field(default="", description="Why this grant was issued")


class DelegationGrant(BaseModel):
    """L7: Delegation chain — transitive approval delegation.

    Actor A can delegate authority to Actor B, with optional constraints:
    - max_tier: B cannot approve beyond this tier (even if A could)
    - valid_until: delegation expires on this date
    - capabilities: optional list of capabilities B can approve (if empty, all)
    """

    delegate_id: str = Field(..., description="Actor ID this grant is delegated to")
    max_tier: AuthorityLevel = Field(
        default=AuthorityLevel.LOW,
        description="Max tier the delegate can approve (never exceeds delegator's tier)",
    )
    valid_until: datetime = Field(
        ..., description="When this delegation expires (UTC)"
    )
    capabilities: list[str] = Field(
        default_factory=list,
        description="Capabilities this delegate can approve (empty = all)",
    )
    reason: str = Field(default="", description="Why this delegation was issued")


class ActorAuthority(BaseModel):
    """L3–L7: Complete authority model for a single actor.

    Bundles all authority layers: roles, capability scopes, thread relationships,
    time-scoped grants, and delegation chains. This is the single source of truth
    for what an actor can do in the system.
    """

    actor_id: str = Field(..., description="Actor ID (user, service, Hermes)")
    authority_level: AuthorityLevel = Field(
        default=AuthorityLevel.LOW,
        description="L3: Max tier this actor can approve",
    )
    role_bundles: list[RoleBundle] = Field(
        default_factory=list,
        description="L2: Named collections of permissions",
    )
    capability_scopes: list[CapabilityScopeGrant] = Field(
        default_factory=list,
        description="L4: Fine-grained authority by capability",
    )
    thread_relationships: list[ThreadRelationshipGrant] = Field(
        default_factory=list,
        description="L5: Permissions scoped to specific threads",
    )
    time_scoped_grants: list[TimeScopedGrant] = Field(
        default_factory=list,
        description="L6: Temporary, deadline-bound grants",
    )
    delegations: list[DelegationGrant] = Field(
        default_factory=list,
        description="L7: Delegation chains",
    )

    def has_permission(self, action: str) -> bool:
        """Check if this actor has a permission (string-based, simple allowlist)."""
        for role in self.role_bundles:
            if action in role.permissions:
                return True
        return False

    def get_authority_for_capability(self, capability: str) -> AuthorityLevel:
        """Get the max authority level for a specific capability.

        L4 override: if capability_scopes has an entry for this capability, use it.
        Otherwise, use the default authority_level.
        """
        for scope in self.capability_scopes:
            if scope.capability == capability:
                return scope.authority_level
        return self.authority_level

    def is_in_thread(self, thread_id: str) -> bool:
        """Check if this actor has any relationship in a specific thread."""
        for thread_rel in self.thread_relationships:
            if thread_rel.thread_id == thread_id:
                return True
        return False

    def get_thread_relationships(self, thread_id: str) -> list[str]:
        """Get this actor's relationships in a specific thread (e.g., [owner, participant])."""
        for thread_rel in self.thread_relationships:
            if thread_rel.thread_id == thread_id:
                return thread_rel.relationships
        return []

    def has_active_time_scoped_grant(self, action: str, now: datetime | None = None) -> bool:
        """Check if this actor has an active time-scoped grant for an action."""
        from datetime import datetime as dt_class
        now = now or dt_class.now(dt_class.now().astimezone().tzinfo)
        for grant in self.time_scoped_grants:
            if grant.action == action and grant.valid_until > now:
                return True
        return False

    def clean_expired_grants(self, now: datetime | None = None) -> None:
        """Remove all expired time-scoped and delegation grants (in-place mutation for maintenance)."""
        from datetime import datetime as dt_class
        now = now or dt_class.now(dt_class.now().astimezone().tzinfo)
        self.time_scoped_grants = [g for g in self.time_scoped_grants if g.valid_until > now]
        self.delegations = [d for d in self.delegations if d.valid_until > now]


def can_approve(actor_authority: ActorAuthority, tier: AuthorityLevel) -> bool:
    """Check if actor's authority level permits approving this tier.

    Returns True if actor's authority >= tier in the hierarchy.
    Example: an actor with authority HIGH can approve LOW and MEDIUM, but not CRITICAL.
    """
    tier_hierarchy = [AuthorityLevel.LOW, AuthorityLevel.MEDIUM, AuthorityLevel.HIGH, AuthorityLevel.CRITICAL]
    actor_idx = tier_hierarchy.index(actor_authority.authority_level)
    tier_idx = tier_hierarchy.index(tier)
    return actor_idx >= tier_idx
