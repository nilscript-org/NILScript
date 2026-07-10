"""Wave 5 (AI Boundary) — Frozen Intent Taxonomy v1.

The Intent is the stable API between Hermes (the AI) and the Kernel (the server).
Hermes never sees Verbs or Capabilities directly; it fills Intent schemas with business
semantics only. The Kernel resolves capabilities server-side (governed, opaque to Hermes).

All Intent schemas are frozen (extra="forbid"), versioned, and immutable. Breaking changes
require a new version (Intent v2.0).

Reference: docs/WAVE-5-MIGRATION.md
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IntentKind(str, Enum):
    """Frozen Intent taxonomy v1 — the only contracts Hermes fills.

    These are business operations, never technical verb names. The Kernel resolves each
    intent kind to concrete capabilities and verbs server-side.
    """

    CREATE_BUSINESS_CYCLE = "CreateBusinessCycle"
    EXECUTE_CYCLE = "ExecuteCycle"
    REPLY_TO_THREAD = "ReplyToThread"
    QUERY_THREAD = "QueryThread"
    EXPLAIN_DECISION = "ExplainDecision"
    SUMMARIZE_THREAD = "SummarizeThread"
    CLARIFY = "Clarify"  # Kernel → Hermes ONLY (never Hermes → Kernel)


class Intent(BaseModel):
    """Base Intent — all intents inherit from this.

    This is the frozen boundary API. Changes to this schema require a new version
    and a migration plan (see docs/WAVE-5-MIGRATION.md).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: IntentKind
    description: str = Field(
        min_length=1,
        description="Natural language input from user or Kernel clarification context",
    )
    workspace_id: str = Field(min_length=1, description="Tenant isolation")
    actor_id: str = Field(min_length=1, description="Who is asking? (user/role id)")
    version: str = Field(default="1.0", description="Intent schema version (for evolution)")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Hermes fills these")


class CreateBusinessCycleIntent(Intent):
    """Hermes fills this to create a new business cycle from NL description.

    Example:
        description: "Create an approval process for orders over $10k"
        parameters: {
            "actors": [{"name": "Treasurer", "role": "approver"}, ...],
            "rules": [{"condition": "amount > 10k", "action": "escalate"}],
            "systems": [{"name": "email"}, {"name": "odoo"}]
        }
    """

    kind: Literal[IntentKind.CREATE_BUSINESS_CYCLE] = IntentKind.CREATE_BUSINESS_CYCLE
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Specification Engine fills: actors, rules, systems",
    )


class ExecuteCycleIntent(Intent):
    """Hermes fills this to execute a known cycle.

    Example:
        description: "Execute order approval for PO-12345"
        parameters: {
            "cycle_id": "ApprovalProcess",
            "args": {"po_id": "PO-12345", "vendor": "ACME Corp"}
        }
    """

    kind: Literal[IntentKind.EXECUTE_CYCLE] = IntentKind.EXECUTE_CYCLE
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Hermes fills: cycle_id, args (runtime parameters)",
    )


class ReplyToThreadIntent(Intent):
    """Hermes fills this to send a reply to a thread.

    Example:
        description: "Send approval message to thread"
        parameters: {
            "thread_id": "thread-xyz",
            "message": "Approved",
            "attachments": [...]
        }
    """

    kind: Literal[IntentKind.REPLY_TO_THREAD] = IntentKind.REPLY_TO_THREAD
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Hermes fills: thread_id, message, attachments",
    )


class QueryThreadIntent(Intent):
    """Hermes fills this to query thread history or documents.

    Example:
        description: "Get the decision history for order ORD-456"
        parameters: {
            "thread_id": "thread-xyz",
            "query_type": "history" | "documents" | "participants"
        }
    """

    kind: Literal[IntentKind.QUERY_THREAD] = IntentKind.QUERY_THREAD
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Hermes fills: thread_id, query_type",
    )


class ExplainDecisionIntent(Intent):
    """Hermes fills this to ask the Kernel to explain a decision.

    Example:
        description: "Why was this order rejected?"
        parameters: {
            "decision_id": "decision-abc",
            "decision_point": "rejection"
        }
    """

    kind: Literal[IntentKind.EXPLAIN_DECISION] = IntentKind.EXPLAIN_DECISION
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Hermes fills: decision_id, decision_point",
    )


class SummarizeThreadIntent(Intent):
    """Hermes fills this to summarize a thread.

    Example:
        description: "Summarize the approval history for this order"
        parameters: {
            "thread_id": "thread-xyz",
            "format": "timeline" | "summary"
        }
    """

    kind: Literal[IntentKind.SUMMARIZE_THREAD] = IntentKind.SUMMARIZE_THREAD
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Hermes fills: thread_id, format",
    )


class ClarifyRequest(Intent):
    """Kernel → Hermes ONLY. The Kernel asks Hermes to clarify an ambiguity.

    Hermes never emits this; only the Kernel does when it cannot resolve an intent
    unambiguously. Hermes responds by filling one of the standard intents with the
    clarified parameters.

    Example:
        description: "Which Ahmed should approve this? (ahmed@acme or ahmed@supplier?)"
        parameters: {
            "options": ["ahmed@acme", "ahmed@supplier"],
            "context": "Vendor approval required"
        }
    """

    kind: Literal[IntentKind.CLARIFY] = IntentKind.CLARIFY
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Kernel fills: options, context, waiting_for_clarification_on",
    )


# Type alias for all possible intents Hermes can emit
HermesIntent = (
    CreateBusinessCycleIntent
    | ExecuteCycleIntent
    | ReplyToThreadIntent
    | QueryThreadIntent
    | ExplainDecisionIntent
    | SummarizeThreadIntent
)

# Type alias for clarification requests the Kernel emits
KernelClarification = ClarifyRequest
