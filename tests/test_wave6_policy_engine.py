"""Wave 6 Tests: Policy Engine, Authority Layers, Hermes Governance, Permission Cards.

Test cases cover:
1. Policy Engine verdicts (Allow/Deny/NeedsApproval)
2. Authority level hierarchy and tier enforcement
3. Hermes' God Rules (proposal-only constraints)
4. Permission Cards (creation, approval flow, expiry)
5. Authority layer combinations (roles, capability scopes, time-scoped grants, delegation)
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from nilscript.authority import (
    AuthorityLevel,
    ActorAuthority,
    RoleBundle,
    CapabilityScopeGrant,
    ThreadRelationshipGrant,
    TimeScopedGrant,
    DelegationGrant,
    can_approve,
    PolicyEngine,
    Verdict,
    VerdictKind,
    HermesActor,
    PermissionCard,
    create_permission_card_if_needed,
)
from nilscript.authority.permission_card import (
    permission_cards_for_actor,
    permission_cards_pending_actor,
)


# ── Policy Engine ────────────────────────────────────────────────────────────────────────────────────


class TestPolicyEngine:
    """Policy Engine verdict logic."""

    def test_policy_engine_allow_by_default(self):
        """Phase 1: Policy Engine allows by default (no require_permission wired yet)."""
        engine = PolicyEngine()
        verdict = engine.can("user1", "write", "cycle:123")
        assert verdict.kind == VerdictKind.ALLOW
        assert verdict.reason == ""

    def test_policy_engine_can_returns_verdict(self):
        """Policy Engine returns Verdict objects, not exceptions."""
        engine = PolicyEngine()
        verdict = engine.can("user1", "approve", "proposal:xyz", {"tier": "HIGH"})
        assert isinstance(verdict, Verdict)
        assert verdict.kind in [VerdictKind.ALLOW, VerdictKind.DENY, VerdictKind.NEEDS_APPROVAL]

    def test_policy_engine_explain(self):
        """Policy Engine provides human-readable explanations."""
        engine = PolicyEngine()
        explanation = engine.explain("user1", "write", "cycle:123")
        assert "user1" in explanation
        assert "write" in explanation
        assert "cycle:123" in explanation
        assert "Decision:" in explanation

    def test_policy_engine_with_require_permission(self):
        """Policy Engine wraps existing require_permission function."""
        def mock_require_permission(actor, permission):
            if actor == "denied":
                raise PermissionError(f"Actor {actor} denied")

        engine = PolicyEngine(require_permission_fn=mock_require_permission)

        # Allowed actor
        verdict = engine.can("allowed", "write", "cycle:123")
        assert verdict.kind == VerdictKind.ALLOW

        # Denied actor
        verdict = engine.can("denied", "write", "cycle:123")
        assert verdict.kind == VerdictKind.DENY
        assert "denied" in verdict.reason


# ── Authority Levels & Hierarchy ─────────────────────────────────────────────────────────────────────


class TestAuthorityLevels:
    """Authority level hierarchy and tier enforcement."""

    def test_authority_level_enum(self):
        """AuthorityLevel has all 4 tiers."""
        assert AuthorityLevel.LOW.value == "LOW"
        assert AuthorityLevel.MEDIUM.value == "MEDIUM"
        assert AuthorityLevel.HIGH.value == "HIGH"
        assert AuthorityLevel.CRITICAL.value == "CRITICAL"

    def test_can_approve_hierarchy(self):
        """can_approve enforces tier hierarchy."""
        actor_low = ActorAuthority(actor_id="low", authority_level=AuthorityLevel.LOW)
        actor_high = ActorAuthority(actor_id="high", authority_level=AuthorityLevel.HIGH)
        actor_critical = ActorAuthority(actor_id="critical", authority_level=AuthorityLevel.CRITICAL)

        # LOW can only approve LOW
        assert can_approve(actor_low, AuthorityLevel.LOW)
        assert not can_approve(actor_low, AuthorityLevel.MEDIUM)
        assert not can_approve(actor_low, AuthorityLevel.HIGH)
        assert not can_approve(actor_low, AuthorityLevel.CRITICAL)

        # HIGH can approve LOW, MEDIUM, HIGH, but not CRITICAL
        assert can_approve(actor_high, AuthorityLevel.LOW)
        assert can_approve(actor_high, AuthorityLevel.MEDIUM)
        assert can_approve(actor_high, AuthorityLevel.HIGH)
        assert not can_approve(actor_high, AuthorityLevel.CRITICAL)

        # CRITICAL can approve everything
        assert can_approve(actor_critical, AuthorityLevel.LOW)
        assert can_approve(actor_critical, AuthorityLevel.MEDIUM)
        assert can_approve(actor_critical, AuthorityLevel.HIGH)
        assert can_approve(actor_critical, AuthorityLevel.CRITICAL)


# ── Authority Layers (L2–L7) ─────────────────────────────────────────────────────────────────────────


class TestAuthorityLayers:
    """Role bundles, capability scopes, thread relationships, time-scoped grants, delegations."""

    def test_actor_authority_has_permission(self):
        """ActorAuthority.has_permission checks role bundle permissions."""
        actor = ActorAuthority(
            actor_id="user1",
            role_bundles=[
                RoleBundle(
                    name="Approver",
                    permissions=["cycle.write", "proposal.approve"],
                )
            ],
        )
        assert actor.has_permission("cycle.write")
        assert actor.has_permission("proposal.approve")
        assert not actor.has_permission("cycle.delete")

    def test_capability_scope_override(self):
        """L4: Capability-scoped grants override default authority."""
        actor = ActorAuthority(
            actor_id="user1",
            authority_level=AuthorityLevel.HIGH,
            capability_scopes=[
                CapabilityScopeGrant(
                    capability="procurement.create_invoice",
                    authority_level=AuthorityLevel.MEDIUM,
                )
            ],
        )
        # Default authority is HIGH
        assert actor.get_authority_for_capability("other_capability") == AuthorityLevel.HIGH
        # But procurement.create_invoice is limited to MEDIUM
        assert actor.get_authority_for_capability("procurement.create_invoice") == AuthorityLevel.MEDIUM

    def test_thread_relationship_grants(self):
        """L5: Thread-relationship grants track actor's role in threads."""
        actor = ActorAuthority(
            actor_id="user1",
            thread_relationships=[
                ThreadRelationshipGrant(
                    thread_id="cycle:123",
                    relationships=["owner"],
                ),
                ThreadRelationshipGrant(
                    thread_id="case:xyz",
                    relationships=["participant", "observer"],
                ),
            ],
        )
        assert actor.is_in_thread("cycle:123")
        assert actor.is_in_thread("case:xyz")
        assert not actor.is_in_thread("cycle:999")

        # Check relationships
        assert actor.get_thread_relationships("cycle:123") == ["owner"]
        assert set(actor.get_thread_relationships("case:xyz")) == {"participant", "observer"}
        assert actor.get_thread_relationships("cycle:999") == []

    def test_time_scoped_grants(self):
        """L6: Time-scoped grants expire at deadline."""
        now = datetime.utcnow()
        actor = ActorAuthority(
            actor_id="user1",
            time_scoped_grants=[
                TimeScopedGrant(
                    action="approve",
                    authority_level=AuthorityLevel.HIGH,
                    valid_until=now + timedelta(hours=1),  # Active
                ),
                TimeScopedGrant(
                    action="execute",
                    authority_level=AuthorityLevel.MEDIUM,
                    valid_until=now - timedelta(hours=1),  # Expired
                ),
            ],
        )
        assert actor.has_active_time_scoped_grant("approve", now)
        assert not actor.has_active_time_scoped_grant("execute", now)

    def test_clean_expired_grants(self):
        """L6/L7: clean_expired_grants removes time-scoped and delegation grants past deadline."""
        now = datetime.utcnow()
        actor = ActorAuthority(
            actor_id="user1",
            time_scoped_grants=[
                TimeScopedGrant(
                    action="approve",
                    valid_until=now + timedelta(hours=1),  # Active
                ),
                TimeScopedGrant(
                    action="execute",
                    valid_until=now - timedelta(hours=1),  # Expired
                ),
            ],
            delegations=[
                DelegationGrant(
                    delegate_id="user2",
                    valid_until=now + timedelta(hours=2),  # Active
                ),
                DelegationGrant(
                    delegate_id="user3",
                    valid_until=now - timedelta(hours=1),  # Expired
                ),
            ],
        )
        assert len(actor.time_scoped_grants) == 2
        assert len(actor.delegations) == 2

        actor.clean_expired_grants(now)

        # Expired grants removed
        assert len(actor.time_scoped_grants) == 1
        assert actor.time_scoped_grants[0].action == "approve"
        assert len(actor.delegations) == 1
        assert actor.delegations[0].delegate_id == "user2"

    def test_delegation_chain(self):
        """L7: Delegation grants represent transitive approval delegation."""
        now = datetime.utcnow()
        actor = ActorAuthority(
            actor_id="user1",
            authority_level=AuthorityLevel.HIGH,
            delegations=[
                DelegationGrant(
                    delegate_id="user2",
                    max_tier=AuthorityLevel.MEDIUM,  # Delegate can't exceed this
                    valid_until=now + timedelta(days=7),
                    capabilities=["procurement.create_invoice", "resource.allocate"],
                    reason="Summer coverage",
                ),
            ],
        )
        assert len(actor.delegations) == 1
        assert actor.delegations[0].max_tier == AuthorityLevel.MEDIUM
        assert "procurement.create_invoice" in actor.delegations[0].capabilities


# ── Hermes Governance ────────────────────────────────────────────────────────────────────────────────


class TestHermesActor:
    """Hermes' God Rules: proposal-only, never execution/approval/state mutation."""

    def test_hermes_actor_id(self):
        """Hermes has a fixed actor ID."""
        assert HermesActor.ACTOR_ID == "hermes"
        assert HermesActor.is_hermes("hermes")
        assert not HermesActor.is_hermes("user1")

    def test_hermes_authority_level(self):
        """Hermes has LOW authority (can only propose LOW-tier actions)."""
        assert HermesActor.AUTHORITY_LEVEL == AuthorityLevel.LOW

    def test_hermes_allowed_actions(self):
        """Hermes can draft cycles, propose, reply to threads, etc."""
        assert "draft_cycle" in HermesActor.ALLOWED_ACTIONS
        assert "propose_parameters" in HermesActor.ALLOWED_ACTIONS
        assert "reply_to_thread" in HermesActor.ALLOWED_ACTIONS
        assert "query_capability" in HermesActor.ALLOWED_ACTIONS

    def test_hermes_forbidden_actions(self):
        """Hermes cannot execute, approve, or modify state."""
        assert "execute_cycle" in HermesActor.FORBIDDEN_ACTIONS
        assert "approve_proposal" in HermesActor.FORBIDDEN_ACTIONS
        assert "call_adapter" in HermesActor.FORBIDDEN_ACTIONS
        assert "modify_cycle_state" in HermesActor.FORBIDDEN_ACTIONS
        assert "grant_permission" in HermesActor.FORBIDDEN_ACTIONS

    def test_hermes_validate_action_allowed(self):
        """Hermes can perform allowed actions without error."""
        # Should not raise
        HermesActor.validate_action("draft_cycle")
        HermesActor.validate_action("reply_to_thread")
        HermesActor.validate_action("propose_parameters")

    def test_hermes_validate_action_forbidden(self):
        """Hermes raises PermissionError for forbidden actions."""
        with pytest.raises(PermissionError, match="God Rule"):
            HermesActor.validate_action("execute_cycle")

        with pytest.raises(PermissionError, match="God Rule"):
            HermesActor.validate_action("approve_proposal")

    def test_hermes_validate_action_unknown(self):
        """Hermes raises PermissionError for unknown actions."""
        with pytest.raises(PermissionError, match="not whitelisted"):
            HermesActor.validate_action("unknown_action")

    def test_hermes_build_authority(self):
        """HermesActor.build_authority() builds a fixed ActorAuthority."""
        authority = HermesActor.build_authority()
        assert authority.actor_id == "hermes"
        assert authority.authority_level == AuthorityLevel.LOW
        assert len(authority.role_bundles) == 1
        assert authority.role_bundles[0].name == "HermesProposer"
        assert len(authority.capability_scopes) == 0
        assert len(authority.delegations) == 0

    def test_hermes_god_rules(self):
        """HermesActor.get_god_rules() documents the constraints."""
        rules = HermesActor.get_god_rules()
        assert rules["actor_id"] == "hermes"
        assert len(rules["god_rules"]) == 5
        assert "proposal-only" in str(rules["god_rules"])
        assert len(rules["allowed_actions"]) > 0
        assert len(rules["forbidden_actions"]) > 0


# ── Permission Cards ─────────────────────────────────────────────────────────────────────────────────


class TestPermissionCards:
    """Permission Cards: creation, approval flow, expiry."""

    def test_permission_card_creation(self):
        """Permission Cards are created with unique IDs and timestamps."""
        now = datetime.utcnow()
        card = PermissionCard(
            action="approve",
            resource="proposal:xyz",
            actor_id="user1",
            tier=AuthorityLevel.HIGH,
            actor_authority_level=AuthorityLevel.MEDIUM,
            approvers=["cfo@acme.com"],
            deadline=now + timedelta(hours=24),
            title="Approve High-Tier Purchase",
        )
        assert card.id != ""
        assert card.status == "pending"
        assert card.approval_count() == 0

    def test_permission_card_add_approval(self):
        """Permission Cards track approvals."""
        now = datetime.utcnow()
        card = PermissionCard(
            action="approve",
            resource="proposal:xyz",
            actor_id="user1",
            tier=AuthorityLevel.HIGH,
            actor_authority_level=AuthorityLevel.MEDIUM,
            approvers=["cfo@acme.com", "ceo@acme.com"],
            deadline=now + timedelta(hours=24),
            title="Approve",
        )
        assert card.approval_count() == 0
        assert not card.is_fully_approved()

        card.add_approval("cfo@acme.com", now)
        assert card.approval_count() == 1
        assert not card.is_fully_approved()
        assert card.status == "pending"  # Not all approvals yet

        card.add_approval("ceo@acme.com", now)
        assert card.approval_count() == 2
        assert card.is_fully_approved()
        assert card.status == "approved"  # Auto-marked approved

    def test_permission_card_reject(self):
        """Permission Cards can be rejected."""
        now = datetime.utcnow()
        card = PermissionCard(
            action="approve",
            resource="proposal:xyz",
            actor_id="user1",
            tier=AuthorityLevel.HIGH,
            actor_authority_level=AuthorityLevel.MEDIUM,
            approvers=["cfo@acme.com"],
            deadline=now + timedelta(hours=24),
            title="Approve",
        )
        assert card.status == "pending"

        card.reject("Budget exceeded")
        assert card.status == "rejected"
        assert card.rejection_reason == "Budget exceeded"

    def test_permission_card_expiry(self):
        """Permission Cards expire when deadline passes."""
        now = datetime.utcnow()
        card = PermissionCard(
            action="approve",
            resource="proposal:xyz",
            actor_id="user1",
            tier=AuthorityLevel.HIGH,
            actor_authority_level=AuthorityLevel.MEDIUM,
            approvers=["cfo@acme.com"],
            deadline=now + timedelta(hours=1),
            title="Approve",
        )
        assert not card.is_expired(now)
        assert card.is_expired(now + timedelta(hours=2))

    def test_permission_card_invalid_approval_transitions(self):
        """Permission Cards prevent invalid approval transitions."""
        now = datetime.utcnow()
        card = PermissionCard(
            action="approve",
            resource="proposal:xyz",
            actor_id="user1",
            tier=AuthorityLevel.HIGH,
            actor_authority_level=AuthorityLevel.MEDIUM,
            approvers=["cfo@acme.com"],
            deadline=now + timedelta(hours=24),
            title="Approve",
        )
        card.reject()
        assert card.status == "rejected"

        # Cannot approve a rejected card
        with pytest.raises(ValueError, match="Cannot approve"):
            card.add_approval("cfo@acme.com", now)

        # Cannot approve twice by same person (need multiple approvers to test this)
        card2 = PermissionCard(
            action="approve",
            resource="proposal:xyz",
            actor_id="user1",
            tier=AuthorityLevel.HIGH,
            actor_authority_level=AuthorityLevel.MEDIUM,
            approvers=["cfo@acme.com", "ceo@acme.com"],  # Multiple approvers
            deadline=now + timedelta(hours=24),
            title="Approve",
        )
        card2.add_approval("cfo@acme.com", now)
        # Try to add same approval twice
        with pytest.raises(ValueError, match="already approved"):
            card2.add_approval("cfo@acme.com", now)

    def test_create_permission_card_if_needed(self):
        """create_permission_card_if_needed creates cards only for NeedsApproval verdicts."""
        # Allow verdict → no card
        verdict_allow = Verdict(kind=VerdictKind.ALLOW)
        card = create_permission_card_if_needed(
            verdict_allow,
            "approve",
            "proposal:xyz",
            "user1",
            AuthorityLevel.MEDIUM,
        )
        assert card is None

        # Deny verdict → no card
        verdict_deny = Verdict(kind=VerdictKind.DENY, reason="Insufficient authority")
        card = create_permission_card_if_needed(
            verdict_deny,
            "approve",
            "proposal:xyz",
            "user1",
            AuthorityLevel.MEDIUM,
        )
        assert card is None

        # NeedsApproval verdict → card created
        verdict_needs = Verdict(
            kind=VerdictKind.NEEDS_APPROVAL,
            approvers=["cfo@acme.com"],
        )
        card = create_permission_card_if_needed(
            verdict_needs,
            "approve",
            "proposal:xyz",
            "user1",
            AuthorityLevel.MEDIUM,
            title="Approve High-Tier Purchase",
        )
        assert card is not None
        assert card.status == "pending"
        assert card.actor_id == "user1"
        assert "cfo@acme.com" in card.approvers

    def test_permission_cards_for_actor(self):
        """permission_cards_for_actor filters relevant cards for an approver."""
        now = datetime.utcnow()
        card1 = PermissionCard(
            action="approve",
            resource="proposal:1",
            actor_id="user1",
            tier=AuthorityLevel.HIGH,
            actor_authority_level=AuthorityLevel.MEDIUM,
            approvers=["cfo@acme.com", "ceo@acme.com"],
            deadline=now + timedelta(hours=24),
            title="Approve 1",
        )
        card2 = PermissionCard(
            action="approve",
            resource="proposal:2",
            actor_id="user2",
            tier=AuthorityLevel.MEDIUM,
            actor_authority_level=AuthorityLevel.LOW,
            approvers=["finance@acme.com"],
            deadline=now + timedelta(hours=24),
            title="Approve 2",
        )
        card3 = PermissionCard(
            action="approve",
            resource="proposal:3",
            actor_id="user3",
            tier=AuthorityLevel.LOW,
            actor_authority_level=AuthorityLevel.LOW,
            approvers=["cfo@acme.com"],
            deadline=now - timedelta(hours=1),  # Expired
            title="Approve 3",
        )
        cards = [card1, card2, card3]

        # CFO should see card1 (pending, in approvers, not expired) and card3 (expired, doesn't show)
        relevant = permission_cards_for_actor(cards, "cfo@acme.com")
        assert len(relevant) == 1
        assert relevant[0].resource == "proposal:1"

        # Finance should see card2
        relevant = permission_cards_for_actor(cards, "finance@acme.com")
        assert len(relevant) == 1
        assert relevant[0].resource == "proposal:2"

    def test_permission_cards_pending_actor(self):
        """permission_cards_pending_actor filters cards waiting for actor's approval."""
        now = datetime.utcnow()
        card1 = PermissionCard(
            action="approve",
            resource="proposal:1",
            actor_id="user1",
            tier=AuthorityLevel.HIGH,
            actor_authority_level=AuthorityLevel.MEDIUM,
            approvers=["cfo@acme.com"],
            deadline=now + timedelta(hours=24),
            title="Card for user1",
        )
        card2 = PermissionCard(
            action="approve",
            resource="proposal:2",
            actor_id="user2",
            tier=AuthorityLevel.MEDIUM,
            actor_authority_level=AuthorityLevel.LOW,
            approvers=["cfo@acme.com"],
            deadline=now + timedelta(hours=24),
            title="Card for user2",
        )
        card3 = PermissionCard(
            action="approve",
            resource="proposal:3",
            actor_id="user1",
            tier=AuthorityLevel.LOW,
            actor_authority_level=AuthorityLevel.LOW,
            approvers=["cfo@acme.com"],
            deadline=now - timedelta(hours=1),  # Expired
            title="Expired card",
        )
        cards = [card1, card2, card3]

        # user1 has 1 pending card (card3 is expired)
        pending = permission_cards_pending_actor(cards, "user1")
        assert len(pending) == 1
        assert pending[0].resource == "proposal:1"

        # user2 has 1 pending card
        pending = permission_cards_pending_actor(cards, "user2")
        assert len(pending) == 1
        assert pending[0].resource == "proposal:2"


# ── Integration: Policy + Authority + Permission Cards ──────────────────────────────────────────────


class TestWave6Integration:
    """Integration tests combining policy, authority, and permission cards."""

    def test_hermes_proposal_flow(self):
        """Hermes proposes a cycle, policy engine validates, permission card created if needed."""
        engine = PolicyEngine()
        hermes_authority = HermesActor.build_authority()

        # Hermes drafts a cycle (allowed)
        HermesActor.validate_action("draft_cycle")  # Should not raise

        # Hermes tries to execute (forbidden)
        with pytest.raises(PermissionError, match="God Rule"):
            HermesActor.validate_action("execute_cycle")

        # Policy engine checks: Hermes can propose
        verdict = engine.can("hermes", "draft_cycle", "cycle:123")
        assert verdict.kind == VerdictKind.ALLOW

        # User with MEDIUM authority tries to approve CRITICAL tier
        # (In full policy, this would return NeedsApproval with escalation required)
        user_authority = ActorAuthority(
            actor_id="user1",
            authority_level=AuthorityLevel.MEDIUM,
        )
        verdict = engine.can("user1", "approve", "proposal:xyz", {"tier": "CRITICAL"})
        # Phase 1 allows everything, but this demonstrates the pattern
        assert verdict.kind == VerdictKind.ALLOW  # Because no require_permission is wired

    def test_permission_card_workflow(self):
        """Complete permission card workflow: create, approve, mark approved."""
        now = datetime.utcnow()

        # User requests approval
        verdict = Verdict(
            kind=VerdictKind.NEEDS_APPROVAL,
            approvers=["cfo@acme.com", "ceo@acme.com"],
        )

        card = create_permission_card_if_needed(
            verdict,
            "approve",
            "proposal:xyz",
            "user1",
            AuthorityLevel.MEDIUM,
            tier=AuthorityLevel.CRITICAL,
            title="Approve CRITICAL Purchase Order",
            preview={"vendor": "Acme Corp", "amount": "$100k"},
        )

        assert card is not None
        assert card.status == "pending"
        assert card.approval_count() == 0

        # CFO approves
        card.add_approval("cfo@acme.com", now)
        assert card.approval_count() == 1
        assert card.status == "pending"  # Still waiting for CEO

        # CEO approves
        card.add_approval("ceo@acme.com", now)
        assert card.approval_count() == 2
        assert card.is_fully_approved()
        assert card.status == "approved"  # Fully approved

        # Now the action can execute with the approved card as evidence
        assert card.resource == "proposal:xyz"
        assert "vendor" in card.preview
