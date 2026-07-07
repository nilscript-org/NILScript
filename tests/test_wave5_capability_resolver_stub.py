"""Test Wave 5 Capability Resolver stub — server-side resolution (Kernel-owned)."""

import pytest

from nilscript.wbos.capability_resolver import (
    CapabilityResolver,
    ResolvedCapability,
    ResolutionResult,
)
from nilscript.wbos.intent import (
    CreateBusinessCycleIntent,
    ExecuteCycleIntent,
    QueryThreadIntent,
    ReplyToThreadIntent,
)


class TestCapabilityResolverInitialization:
    """CapabilityResolver initializes with optional registry."""

    def test_resolver_initializes_without_registry(self):
        """Can create resolver without capability registry."""
        resolver = CapabilityResolver()
        assert resolver.registry == {}

    def test_resolver_initializes_with_registry(self):
        """Can create resolver with a capability registry."""
        registry = {"cap-1": "capability-object"}
        resolver = CapabilityResolver(capability_registry=registry)
        assert resolver.registry == registry


class TestResolutionResultStructure:
    """ResolutionResult encapsulates resolution outcome."""

    def test_resolution_result_creation(self):
        """Can create a resolution result."""
        intent = CreateBusinessCycleIntent(
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = ResolutionResult(intent=intent, capabilities=[])
        assert result.intent == intent
        assert result.capabilities == []
        assert result.ambiguities == []

    def test_resolution_result_with_ambiguities(self):
        """Can track ambiguities in resolution."""
        intent = CreateBusinessCycleIntent(
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = ResolutionResult(
            intent=intent,
            capabilities=[],
            ambiguities=["Which supplier?", "Which approval tier?"],
        )
        assert len(result.ambiguities) == 2

    def test_resolution_result_is_unambiguous_when_capabilities_resolved(self):
        """is_unambiguous() returns true when no ambiguities and capabilities found."""
        intent = CreateBusinessCycleIntent(
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        resolved_cap = ResolvedCapability(
            capability_id="cap-1",
            capability=None,  # Stub
            skill_name="send",
            verb_id="comms.send_email",
            parameters={},
        )
        result = ResolutionResult(
            intent=intent,
            capabilities=[resolved_cap],
            ambiguities=[],
        )
        assert result.is_unambiguous()

    def test_resolution_result_is_ambiguous_when_ambiguities_exist(self):
        """is_unambiguous() returns false when ambiguities exist."""
        intent = CreateBusinessCycleIntent(
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = ResolutionResult(
            intent=intent,
            capabilities=[],
            ambiguities=["Ambiguity found"],
        )
        assert not result.is_unambiguous()


class TestCapabilityResolverRouting:
    """CapabilityResolver routes by intent kind."""

    def test_resolver_handles_create_business_cycle_intent(self):
        """resolve_for_intent routes CreateBusinessCycleIntent correctly."""
        resolver = CapabilityResolver()
        intent = CreateBusinessCycleIntent(
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = resolver.resolve_for_intent(intent)
        assert result.intent == intent
        assert isinstance(result, ResolutionResult)
        # Stub should return empty capabilities
        assert len(result.capabilities) == 0

    def test_resolver_handles_execute_cycle_intent(self):
        """resolve_for_intent routes ExecuteCycleIntent correctly."""
        resolver = CapabilityResolver()
        intent = ExecuteCycleIntent(
            description="Execute cycle",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = resolver.resolve_for_intent(intent)
        assert result.intent == intent
        assert isinstance(result, ResolutionResult)

    def test_resolver_handles_reply_to_thread_intent(self):
        """resolve_for_intent routes ReplyToThreadIntent correctly."""
        resolver = CapabilityResolver()
        intent = ReplyToThreadIntent(
            description="Send message",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = resolver.resolve_for_intent(intent)
        assert result.intent == intent
        assert isinstance(result, ResolutionResult)

    def test_resolver_handles_query_thread_intent(self):
        """resolve_for_intent routes QueryThreadIntent correctly."""
        resolver = CapabilityResolver()
        intent = QueryThreadIntent(
            description="Query thread",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = resolver.resolve_for_intent(intent)
        assert result.intent == intent
        assert isinstance(result, ResolutionResult)


class TestCapabilityResolverStubs:
    """Resolver methods are stubs returning Phase 3 messages."""

    def test_create_business_cycle_resolver_is_stub(self):
        """_resolve_create_business_cycle returns stub message."""
        resolver = CapabilityResolver()
        intent = CreateBusinessCycleIntent(
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = resolver._resolve_create_business_cycle(intent)
        assert not result.is_unambiguous()
        assert "Phase 3" in str(result.ambiguities)

    def test_execute_cycle_resolver_is_stub(self):
        """_resolve_execute_cycle returns stub message."""
        resolver = CapabilityResolver()
        intent = ExecuteCycleIntent(
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = resolver._resolve_execute_cycle(intent)
        assert not result.is_unambiguous()
        assert "Phase 3" in str(result.ambiguities)

    def test_reply_to_thread_resolver_is_stub(self):
        """_resolve_reply_to_thread returns stub message."""
        resolver = CapabilityResolver()
        intent = ReplyToThreadIntent(
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = resolver._resolve_reply_to_thread(intent)
        assert not result.is_unambiguous()
        assert "Phase 3" in str(result.ambiguities)

    def test_query_thread_resolver_is_stub(self):
        """_resolve_query_thread returns stub message."""
        resolver = CapabilityResolver()
        intent = QueryThreadIntent(
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        result = resolver._resolve_query_thread(intent)
        assert not result.is_unambiguous()
        assert "Phase 3" in str(result.ambiguities)


class TestCapabilityResolverHelpers:
    """Resolver helper methods are stubs."""

    def test_find_capabilities_for_systems_is_stub(self):
        """find_capabilities_for_systems returns empty list (stub)."""
        resolver = CapabilityResolver()
        systems = ["email", "odoo"]
        capabilities = resolver.find_capabilities_for_systems(systems)
        assert capabilities == []

    def test_suggest_for_ambiguity_is_stub(self):
        """suggest_for_ambiguity returns empty list (stub)."""
        resolver = CapabilityResolver()
        options = resolver.suggest_for_ambiguity("Which supplier?", "ws-1")
        assert options == []


class TestResolvedCapabilityStructure:
    """ResolvedCapability holds a matched capability."""

    def test_resolved_capability_creation(self):
        """Can create a ResolvedCapability."""
        cap = ResolvedCapability(
            capability_id="SendEmail",
            capability=None,  # Stub
            skill_name="send",
            verb_id="comms.send_email",
            parameters={"to": "user@example.com", "subject": "Test"},
        )
        assert cap.capability_id == "SendEmail"
        assert cap.skill_name == "send"
        assert cap.verb_id == "comms.send_email"
        assert cap.parameters["to"] == "user@example.com"


class TestCapabilityResolverIntegration:
    """CapabilityResolver integrates with Intent schema."""

    def test_resolver_accepts_frozen_intents(self):
        """Resolver works with frozen Intent objects."""
        resolver = CapabilityResolver()
        intent = CreateBusinessCycleIntent(
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        # Ensure intent is frozen
        with pytest.raises(Exception):
            intent.kind = None  # Should fail because frozen

        # Resolver should still work
        result = resolver.resolve_for_intent(intent)
        assert result.intent == intent
