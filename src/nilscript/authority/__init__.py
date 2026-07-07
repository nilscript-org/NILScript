"""Wave 6: Authority & Policy — governance layers, explainable access control, and permission cards.

The Authority module provides:
- L3–L7 Authority Hierarchy: Role bundles, capability scopes, thread relationships, time-scoped grants, delegation chains
- Policy Engine: Centralized, non-breaking wrapper over `_require_permission` returning Verdict (Allow/Deny/NeedsApproval)
- Hermes Governance: Constraints on Hermes' actions (proposals only, never execution)
- Permission Cards: Governance gates bridging policy decisions to human approval
"""

from __future__ import annotations

from nilscript.authority.layers import (
    AuthorityLevel,
    ActorAuthority,
    RoleBundle,
    CapabilityScopeGrant,
    ThreadRelationshipGrant,
    TimeScopedGrant,
    DelegationGrant,
    can_approve,
)
from nilscript.authority.policy import (
    PolicyEngine,
    Verdict,
    VerdictKind,
)
from nilscript.authority.hermes_actor import HermesActor
from nilscript.authority.permission_card import (
    PermissionCard,
    create_permission_card_if_needed,
)

__all__ = [
    "AuthorityLevel",
    "ActorAuthority",
    "RoleBundle",
    "CapabilityScopeGrant",
    "ThreadRelationshipGrant",
    "TimeScopedGrant",
    "DelegationGrant",
    "can_approve",
    "PolicyEngine",
    "Verdict",
    "VerdictKind",
    "HermesActor",
    "PermissionCard",
    "create_permission_card_if_needed",
]
