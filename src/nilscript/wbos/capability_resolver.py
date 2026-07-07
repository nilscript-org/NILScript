"""Wave 5 Capability Resolver — Server-side resolution (Kernel-owned, Hermes-opaque).

The CapabilityResolver is a server-only component. It takes a business Intent and resolves
it to a set of concrete Capabilities and Verbs. Hermes never sees the resolver or its
internal state; it only sees clarification requests when ambiguities arise.

Reference: docs/WAVE-5-MIGRATION.md §Resolver Layer
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nilscript.capability.models import Capability
from nilscript.wbos.intent import (
    CreateBusinessCycleIntent,
    ExecuteCycleIntent,
    Intent,
    IntentKind,
)


@dataclass
class ResolvedCapability:
    """A capability matched to an intent, ready for governance and execution."""

    capability_id: str
    capability: Capability
    skill_name: str  # which skill on the capability to invoke
    verb_id: str  # the resolved verb (domain.action)
    parameters: dict[str, Any]  # arguments to pass to the verb


@dataclass
class ResolutionResult:
    """Outcome of capability resolution."""

    intent: Intent
    capabilities: list[ResolvedCapability]
    ambiguities: list[str] = None  # if any, Kernel emits ClarifyRequest

    def __post_init__(self) -> None:
        if self.ambiguities is None:
            self.ambiguities = []

    def is_unambiguous(self) -> bool:
        """True if resolution is complete and unambiguous."""
        return len(self.ambiguities) == 0 and len(self.capabilities) > 0


class CapabilityResolver:
    """Server-side resolver: Intent → Capabilities (Kernel-owned, Hermes-opaque).

    This component:
    1. Takes a business Intent from Hermes
    2. Resolves it to concrete Capabilities using a registry (server-side only)
    3. Returns either resolved capabilities or a list of ambiguities for Kernel to clarify
    4. Hermes never sees the registry, capability ids, or verb names

    All methods are stubs in Wave 5; implementation follows in Phase 3.
    """

    def __init__(self, capability_registry: dict[str, Capability] | None = None):
        """Initialize the resolver with an optional capability registry.

        Args:
            capability_registry: Map of capability_id → Capability (server-side only).
                                 In production, this loads from the control plane registry.
        """
        self.registry = capability_registry or {}

    def resolve_for_intent(self, intent: Intent) -> ResolutionResult:
        """Resolve an Intent to concrete Capabilities.

        This is the main entry point. It:
        1. Routes by intent kind
        2. Calls the type-specific resolver
        3. Returns resolved capabilities or ambiguities

        Args:
            intent: A business Intent from Hermes

        Returns:
            ResolutionResult with either .capabilities (success) or .ambiguities (clarify needed)
        """
        # Route by intent kind
        if intent.kind == IntentKind.CREATE_BUSINESS_CYCLE:
            return self._resolve_create_business_cycle(intent)
        elif intent.kind == IntentKind.EXECUTE_CYCLE:
            return self._resolve_execute_cycle(intent)
        elif intent.kind == IntentKind.REPLY_TO_THREAD:
            return self._resolve_reply_to_thread(intent)
        elif intent.kind == IntentKind.QUERY_THREAD:
            return self._resolve_query_thread(intent)
        elif intent.kind == IntentKind.EXPLAIN_DECISION:
            return self._resolve_explain_decision(intent)
        elif intent.kind == IntentKind.SUMMARIZE_THREAD:
            return self._resolve_summarize_thread(intent)
        else:
            # Unknown kind (should not happen if Intent schema is enforced)
            return ResolutionResult(
                intent=intent,
                capabilities=[],
                ambiguities=[f"Unknown intent kind: {intent.kind}"],
            )

    def _resolve_create_business_cycle(
        self, intent: CreateBusinessCycleIntent
    ) -> ResolutionResult:
        """Resolve CreateBusinessCycleIntent to capabilities.

        The Specification Engine extracts systems (email, odoo, etc.) from the intent
        description and fills intent.parameters["systems"]. The resolver then finds
        capabilities that implement those systems.

        Example flow:
        1. Specification Engine analyzes: "Create an approval process for orders over $10k"
        2. Extracts systems: [email, odoo, finance]
        3. Resolver finds capabilities: [SendEmail, InvoiceCreation, ApprovalGate]
        4. Returns resolved capabilities for the Cycle Builder

        TODO: Implementation in Phase 3 (Capability Encapsulation)
        - Query registry for each system
        - Find matching capabilities
        - Validate governance tier
        - Return ResolutionResult
        """
        # Stub: return empty (no capabilities resolved yet)
        return ResolutionResult(
            intent=intent,
            capabilities=[],
            ambiguities=["CreateBusinessCycleIntent resolution stub — Phase 3"],
        )

    def _resolve_execute_cycle(self, intent: ExecuteCycleIntent) -> ResolutionResult:
        """Resolve ExecuteCycleIntent to capabilities.

        The cycle_id is known; we look up its implementation and return the
        entry-point capabilities (the first step of the cycle).

        TODO: Implementation in Phase 3
        - Look up cycle_id in registry
        - Find entry capability
        - Return resolved capability
        """
        # Stub: return empty
        return ResolutionResult(
            intent=intent,
            capabilities=[],
            ambiguities=["ExecuteCycleIntent resolution stub — Phase 3"],
        )

    def _resolve_reply_to_thread(self, intent: Any) -> ResolutionResult:
        """Resolve ReplyToThreadIntent to capabilities.

        Find the communication capability (comms.send_message, comms.send_email, etc.)
        based on the thread's channel (email, WhatsApp, internal, etc.).

        TODO: Implementation in Phase 3
        - Query thread metadata to find channel
        - Find matching communication capability
        - Return resolved capability
        """
        return ResolutionResult(
            intent=intent,
            capabilities=[],
            ambiguities=["ReplyToThreadIntent resolution stub — Phase 3"],
        )

    def _resolve_query_thread(self, intent: Any) -> ResolutionResult:
        """Resolve QueryThreadIntent to capabilities.

        This is a read-only query; the resolver may not need to return capabilities
        if the kernel can handle this internally. If it does need a capability,
        find the thread query capability.

        TODO: Implementation in Phase 3
        - Determine query type
        - Find appropriate read-only capability if needed
        - Return resolved capability or internal handling
        """
        return ResolutionResult(
            intent=intent,
            capabilities=[],
            ambiguities=["QueryThreadIntent resolution stub — Phase 3"],
        )

    def _resolve_explain_decision(self, intent: Any) -> ResolutionResult:
        """Resolve ExplainDecisionIntent to capabilities.

        This is introspection; likely kernel-internal. If a capability is needed,
        find the audit/trail capability.

        TODO: Implementation in Phase 3
        - Look up decision history
        - Format explanation
        - Return result (may be internal or capability-based)
        """
        return ResolutionResult(
            intent=intent,
            capabilities=[],
            ambiguities=["ExplainDecisionIntent resolution stub — Phase 3"],
        )

    def _resolve_summarize_thread(self, intent: Any) -> ResolutionResult:
        """Resolve SummarizeThreadIntent to capabilities.

        This is introspection; likely kernel-internal. If a capability is needed,
        find the thread summarization capability.

        TODO: Implementation in Phase 3
        - Look up thread history
        - Format summary
        - Return result (may be internal or capability-based)
        """
        return ResolutionResult(
            intent=intent,
            capabilities=[],
            ambiguities=["SummarizeThreadIntent resolution stub — Phase 3"],
        )

    def find_capabilities_for_systems(self, systems: list[str]) -> list[Capability]:
        """Find capabilities for a list of system names (e.g., ["email", "odoo"]).

        This is a helper for _resolve_create_business_cycle. Given a list of system
        names extracted by the Specification Engine, return matching capabilities.

        TODO: Implementation in Phase 3
        - Query registry for each system
        - Match by domain and capabilities
        - Return matching capabilities
        """
        # Stub: return empty
        return []

    def suggest_for_ambiguity(
        self, question: str, workspace_id: str
    ) -> list[tuple[str, str]]:
        """Suggest clarification options for an ambiguous intent.

        If the Specification Engine or Capability Resolver encounters an ambiguity
        (e.g., "Which supplier?" or "Which Ahmed?"), this helper generates a list of
        options to send back to Hermes via a ClarifyRequest.

        Args:
            question: The ambiguity question (e.g., "Which Ahmed should approve?")
            workspace_id: Tenant context for finding options

        Returns:
            List of (option_id, option_label) tuples

        TODO: Implementation in Phase 3
        - Query context for entity matches
        - Filter by workspace
        - Return options
        """
        # Stub: return empty
        return []
