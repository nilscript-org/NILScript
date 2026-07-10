# Wave 6: Authority & Policy — Architecture & Implementation Guide

**Status:** Foundation Phase (Tasks 1–5 complete)

**Objective:** Design and stub the Policy Engine facade and authority layers (L3–L7). This is the foundation for Wave 6; full implementation follows later.

---

## Overview

Wave 6 introduces centralized, explainable access control through:

1. **Policy Engine** — Non-breaking wrapper returning Verdict (Allow/Deny/NeedsApproval)
2. **Authority Hierarchy** — L3–L7 layered governance model
3. **Hermes Governance** — Hard constraints on Hermes' actions (proposals only)
4. **Permission Cards** — Governance gates bridging policy to human approval

---

## Architecture

### Policy Engine (§1)

The Policy Engine is the single source of truth for access control decisions.

```python
from nilscript.authority import PolicyEngine, Verdict

engine = PolicyEngine()
verdict = engine.can(actor_id, action, resource, context={})

if verdict.kind == "Allow":
    # Execute immediately
elif verdict.kind == "Deny":
    # Reject with reason
elif verdict.kind == "NeedsApproval":
    # Create Permission Card, wait for approvers
```

**Phase 1 (now):** Non-breaking wrapper over existing `_require_permission`.  
**Phase 2 (future):** Full policy evaluation using L3–L7 authority layers, time-scoped grants, delegation chains.

### Authority Hierarchy: L3–L7

```
┌─ L3: Authority Level (max tier this actor can approve)
│  ├─ LOW → MEDIUM → HIGH → CRITICAL
│
├─ L2: Role Bundle (named collection of permissions)
│  └─ FinanceApprover, ProcurementManager, etc.
│
├─ L4: Capability-Scoped Grants (fine-grained by capability)
│  └─ "procurement.create_invoice" → HIGH tier (even if actor's default is CRITICAL)
│
├─ L5: Thread-Relationship Grants (scoped to specific cycles/cases)
│  └─ thread:123 → [owner, participant] → permissions apply only in thread:123
│
├─ L6: Time-Scoped Grants (temporary, deadline-bound)
│  └─ Emergency access expires at 2026-08-31
│
└─ L7: Delegation Chains (transitive approval delegation)
   └─ Actor A delegates to Actor B (with max_tier constraint + expiry)
```

### ActorAuthority Model

Each actor's authority is described by a single `ActorAuthority` object bundling all layers:

```python
from nilscript.authority import ActorAuthority, AuthorityLevel, RoleBundle

actor = ActorAuthority(
    actor_id="user@acme.com",
    authority_level=AuthorityLevel.HIGH,  # L3: max tier
    
    role_bundles=[  # L2
        RoleBundle(
            name="FinanceApprover",
            permissions=["cycle.write", "proposal.approve"],
            authority_level=AuthorityLevel.HIGH,
        )
    ],
    
    capability_scopes=[  # L4
        CapabilityScopeGrant(
            capability="procurement.create_invoice",
            authority_level=AuthorityLevel.MEDIUM,  # Override: max MEDIUM for this capability
        )
    ],
    
    thread_relationships=[  # L5
        ThreadRelationshipGrant(
            thread_id="cycle:acme-q3-2026",
            relationships=["owner", "approver"],
        )
    ],
    
    time_scoped_grants=[  # L6
        TimeScopedGrant(
            action="approve",
            authority_level=AuthorityLevel.CRITICAL,
            valid_until=datetime(2026, 8, 31),
            reason="Summer cover for CFO",
        )
    ],
    
    delegations=[  # L7
        DelegationGrant(
            delegate_id="user2@acme.com",
            max_tier=AuthorityLevel.MEDIUM,  # Delegate max MEDIUM (never exceeds L3)
            valid_until=datetime(2026, 8, 31),
            capabilities=["procurement.*"],  # Optional: limit to specific capabilities
            reason="Delegation during vacation",
        )
    ],
)
```

---

## Hermes Governance: God Rules

Hermes (the AI orchestrator) is constrained by unchecked God Rules:

```python
from nilscript.authority import HermesActor

# Hermes' fixed identity
HermesActor.ACTOR_ID  # "hermes"
HermesActor.AUTHORITY_LEVEL  # AuthorityLevel.LOW (can only propose LOW-tier)

# Whitelist: what Hermes CAN do
HermesActor.ALLOWED_ACTIONS = {
    "draft_cycle",  # Generate cycle blueprint
    "propose_parameters",  # Fill in parameters
    "reply_to_thread",  # Send message
    "suggest_clarification",  # Ask for clarification
    "query_capability",  # Read-only capability lookup
    # ... more
}

# Blacklist: what Hermes ABSOLUTELY CANNOT do
HermesActor.FORBIDDEN_ACTIONS = {
    "execute_cycle",  # Never
    "approve_proposal",  # Never
    "modify_cycle_state",  # Never
    "call_adapter",  # Never
    "grant_permission",  # Never
    # ... more
}

# Validate before every Hermes action
try:
    HermesActor.validate_action("draft_cycle")  # OK
    HermesActor.validate_action("execute_cycle")  # Raises PermissionError
except PermissionError:
    # God Rule violation — block immediately
```

### God Rules Rationale

Hermes is a coordinator, not a decision-maker:
- **Proposal-only:** Hermes drafts cycles and proposes parameters, but humans decide whether to execute
- **Never executes:** Adapter calls are too risky for an AI to perform unilaterally
- **Never approves:** Approval authority requires human judgment and accountability
- **Never modifies state:** Changes to cycles or threads must be traceable to human action
- **Cannot manage authority:** Granting/revoking permissions is a human-only operation

These rules are **unchecked** — no admin can grant Hermes an exception to these rules.

---

## Permission Cards: Governance Gates

When a policy decision requires approval, a Permission Card is created:

```python
from nilscript.authority import PermissionCard, create_permission_card_if_needed

# Policy engine returns NeedsApproval
verdict = engine.can(user_id, "approve", "proposal:xyz", {"tier": "CRITICAL"})

if verdict.kind == "NeedsApproval":
    card = create_permission_card_if_needed(
        verdict,
        action="approve",
        resource="proposal:xyz",
        actor_id=user_id,
        actor_authority_level=ActorAuthority.authority_level,
        tier=AuthorityLevel.CRITICAL,
        title="Approve CRITICAL Purchase Order",
        description="Vendor: Acme Corp, Amount: $100k",
        preview={"vendor": "Acme Corp", "amount": "$100k", "terms": "60 days"},
        deadline_hours=24,  # Must approve within 24 hours
    )
    
    # Card is now rendered in the thread as a governance gate
    # Approvers see it, approve it, and card status transitions to "approved"
    
    # Workflow:
    # 1. User initiates → Card created (pending)
    # 2. Approver 1 approves → Card still pending (waiting for more)
    # 3. Approver 2 approves → Card marked approved
    # 4. System can now execute the action with card.id as evidence
```

### Permission Card Lifecycle

```
Created (pending) ─→ Partial Approvals ─→ Fully Approved ─→ Execution
                           ↓
                        Rejected
                           ↓
                        Expired (deadline passed)
```

**Card Properties:**
- `id` — Unique identifier
- `action` — What action is being requested
- `resource` — What resource
- `tier` — Governance tier (LOW/MEDIUM/HIGH/CRITICAL)
- `approvers` — Who needs to approve (list of actor IDs or roles)
- `approvals` — Who approved (dict: approver_id → timestamp)
- `deadline` — When approval expires
- `status` — pending | approved | rejected | expired
- `title` — UI label
- `description` — UI explanation
- `preview` — UI data (cost estimate, cycle parameters, etc.)

---

## Usage Patterns

### Pattern 1: Simple Action Check

```python
engine = PolicyEngine()
verdict = engine.can("user1", "write", "cycle:123")

if verdict.kind == "Allow":
    # Execute the cycle
    execute_cycle("cycle:123")
else:
    # Return error with explanation
    return {"error": verdict.reason}
```

### Pattern 2: Hermes Proposal

```python
# Hermes drafts a cycle
HermesActor.validate_action("draft_cycle")  # Raises if not allowed

cycle = draft_cycle(...)  # Generate cycle blueprint
# Return to user for approval

# Hermes tries to execute (forbidden by God Rule)
HermesActor.validate_action("execute_cycle")  # Raises PermissionError
# → Cannot execute → human must execute
```

### Pattern 3: Authority Override via Capability Scope

```python
# User can approve HIGH tier, but only MEDIUM for procurement
actor = ActorAuthority(
    actor_id="finance@acme.com",
    authority_level=AuthorityLevel.HIGH,  # Can approve HIGH normally
    capability_scopes=[
        CapabilityScopeGrant(
            capability="procurement.create_invoice",
            authority_level=AuthorityLevel.MEDIUM,  # Override: max MEDIUM
        )
    ],
)

# Check authority for general approval (HIGH)
can_approve(actor, AuthorityLevel.HIGH)  # True

# Check authority for procurement (MEDIUM)
actor.get_authority_for_capability("procurement.create_invoice")  # AuthorityLevel.MEDIUM
can_approve_for_capability(actor, AuthorityLevel.HIGH, "procurement.create_invoice")  # False
```

### Pattern 4: Temporary Escalation (Time-Scoped Grant)

```python
# Emergency: give user CRITICAL approval for 24 hours
actor.time_scoped_grants.append(
    TimeScopedGrant(
        action="approve",
        authority_level=AuthorityLevel.CRITICAL,
        valid_until=datetime.utcnow() + timedelta(hours=24),
        reason="Emergency escalation — CFO on leave",
    )
)

# After 24 hours, grant expires automatically
actor.clean_expired_grants()  # Removes expired grants
```

### Pattern 5: Delegation During Vacation

```python
# CFO delegates to Finance Manager while on vacation
actor.delegations.append(
    DelegationGrant(
        delegate_id="finance_mgr@acme.com",
        max_tier=AuthorityLevel.MEDIUM,  # Delegate can't exceed MEDIUM
        valid_until=datetime(2026, 8, 31),  # Back from vacation
        capabilities=["procurement.*", "resource.*"],
        reason="Vacation cover",
    )
)

# Finance Manager can now act on delegated permissions
# But cannot exceed MEDIUM tier
```

---

## Migration Path: From String RBAC to Policy Engine

**Current State (String RBAC):**
```python
def _require_permission(actor_id: str, permission: str):
    """Simple string-based permission check."""
    if permission not in get_permissions(actor_id):
        raise PermissionError(f"Actor {actor_id} lacks permission {permission}")
```

**Phase 1 (now):** Policy Engine wraps `_require_permission`
```python
engine = PolicyEngine(require_permission_fn=_require_permission)
verdict = engine.can("user1", "write", "cycle:123")
# No behavior change, but Verdict objects enable Phase 2
```

**Phase 2 (future):** Full policy evaluation
```python
engine = PolicyEngine()
verdict = engine.can(
    "user1", "approve", "proposal:xyz",
    context={"tier": "CRITICAL", "workspace": "acme"}
)
# Consults L3–L7 authority layers:
# 1. Does actor have CRITICAL authority? (L3)
# 2. Is there a capability-scoped override? (L4)
# 3. Are they in this thread with relevant relationship? (L5)
# 4. Do they have an active time-scoped grant? (L6)
# 5. Are they delegated authority for this? (L7)
# Returns: Allow | Deny(reason) | NeedsApproval(approvers)
```

---

## API Reference

### PolicyEngine

```python
class PolicyEngine:
    def can(self, actor: str, action: str, resource: str, context: dict = {}) -> Verdict:
        """Can this actor perform this action on this resource?"""
        
    def explain(self, actor: str, action: str, resource: str, context: dict = {}) -> str:
        """Human-readable explanation of the policy decision."""
```

### ActorAuthority

```python
class ActorAuthority(BaseModel):
    actor_id: str
    authority_level: AuthorityLevel
    role_bundles: list[RoleBundle]
    capability_scopes: list[CapabilityScopeGrant]
    thread_relationships: list[ThreadRelationshipGrant]
    time_scoped_grants: list[TimeScopedGrant]
    delegations: list[DelegationGrant]
    
    def has_permission(self, action: str) -> bool:
        """Check if actor has permission (from role bundles)."""
        
    def get_authority_for_capability(self, capability: str) -> AuthorityLevel:
        """Get max authority for specific capability (L4 override)."""
        
    def is_in_thread(self, thread_id: str) -> bool:
        """Check if actor is in thread (L5)."""
        
    def get_thread_relationships(self, thread_id: str) -> list[str]:
        """Get actor's roles in thread (e.g., [owner, participant])."""
        
    def has_active_time_scoped_grant(self, action: str, now: datetime = None) -> bool:
        """Check if active temporary grant exists (L6)."""
        
    def clean_expired_grants(self, now: datetime = None) -> None:
        """Remove expired time-scoped and delegation grants."""
```

### HermesActor

```python
class HermesActor:
    ACTOR_ID = "hermes"
    AUTHORITY_LEVEL = AuthorityLevel.LOW
    ALLOWED_ACTIONS: set  # Whitelist
    FORBIDDEN_ACTIONS: set  # Blacklist
    
    @classmethod
    def validate_action(action: str) -> None:
        """Raises PermissionError if action violates God Rules."""
        
    @classmethod
    def build_authority() -> ActorAuthority:
        """Build Hermes' fixed authority model."""
        
    @classmethod
    def get_god_rules() -> dict:
        """Return structured description of God Rules."""
```

### PermissionCard

```python
class PermissionCard(BaseModel):
    id: str
    action: str
    resource: str
    actor_id: str
    tier: AuthorityLevel
    approvers: list[str]
    approvals: dict[str, datetime]  # approver_id -> timestamp
    deadline: datetime
    status: Literal["pending", "approved", "rejected", "expired"]
    title: str
    description: str
    preview: dict[str, Any]
    
    def approval_count(self) -> int:
    def is_fully_approved(self) -> bool:
    def is_expired(self, now: datetime = None) -> bool:
    def add_approval(self, approver_id: str, now: datetime = None) -> None:
    def reject(self, reason: str = "", now: datetime = None) -> None:
    def mark_expired(self) -> None:
```

---

## Testing

All Wave 6 components are tested in `tests/test_wave6_policy_engine.py`:

```bash
pytest tests/test_wave6_policy_engine.py -v
```

**Test coverage:**
- ✅ Policy Engine verdicts (Allow/Deny/NeedsApproval)
- ✅ Authority hierarchy and tier enforcement
- ✅ Hermes God Rules validation
- ✅ Permission Card lifecycle (create, approve, reject, expire)
- ✅ Authority layers (roles, capability scopes, thread relationships, time-scoped grants, delegation)
- ✅ Integration: Hermes proposal flow + permission card workflow

---

## Next Steps (Wave 6 Phase 2+)

1. **Wire Policy Engine to Controlplane:** Integrate with controlplane's request handling
2. **Implement Permission Card UI:** Thread-based governance gate rendering
3. **Full Policy Evaluation:** Consult L3–L7 layers, return NeedsApproval when appropriate
4. **Audit Trail:** Log all policy decisions and approvals
5. **Escalation Paths:** Define authority pyramids (who escalates to whom)
6. **Analytics:** Dashboard showing approval times, bottlenecks, delegation patterns

---

## Design Decisions

### Why Non-Breaking Wrapper?

The Policy Engine is initially a thin wrapper over `_require_permission` to:
- Avoid breaking existing code
- Enable gradual migration from string RBAC → structured authority
- Return Verdict objects (better than exceptions for control flow)
- Build foundation for full L3–L7 evaluation (Phase 2)

### Why Hermes God Rules Are Unchecked?

Hermes' constraints are hard-coded and cannot be overridden because:
- Hermes is a coordinator, not a decision-maker
- Unilateral execution/approval by AI is unacceptable
- These rules are architectural invariants, not policy tweaks
- They must survive any policy configuration change

### Why L3–L7 Instead of Flat RBAC?

Layered authority enables:
- **Nuance:** Fine-grained control by capability, thread, time
- **Temporary escalation:** Emergency access without permanent role changes
- **Delegation:** Natural approval chains without duplicating authority
- **Audit:** Clear explanation of *why* a decision was made
- **Least privilege:** Each layer is a constraint, not a promotion

---

## References

- `src/nilscript/authority/` — Implementation
- `tests/test_wave6_policy_engine.py` — Test suite
- NBEM Constitution (docs/NBEM-CONSTITUTION.md) — Broader governance model
