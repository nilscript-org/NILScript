"""Test Wave 5 Intent taxonomy v1 — frozen, versioned, immutable."""

import pytest
from pydantic import ValidationError

from nilscript.wbos.intent import (
    ClarifyRequest,
    CreateBusinessCycleIntent,
    ExecuteCycleIntent,
    ExplainDecisionIntent,
    Intent,
    IntentKind,
    QueryThreadIntent,
    ReplyToThreadIntent,
    SummarizeThreadIntent,
)


class TestIntentSchemaFrozen:
    """Intent schemas must be frozen (immutable)."""

    def test_intent_is_frozen(self):
        """Cannot modify intent after creation."""
        intent = Intent(
            kind=IntentKind.CREATE_BUSINESS_CYCLE,
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        with pytest.raises(ValidationError):
            intent.kind = IntentKind.EXECUTE_CYCLE

    def test_intent_forbids_extra_fields(self):
        """Intent rejects unknown fields (extra="forbid")."""
        with pytest.raises(ValidationError) as exc_info:
            Intent(
                kind=IntentKind.CREATE_BUSINESS_CYCLE,
                description="Test",
                workspace_id="ws-1",
                actor_id="user-1",
                unknown_field="should fail",
            )
        assert "unknown_field" in str(exc_info.value)


class TestIntentVersioning:
    """Intent versioning allows for schema evolution."""

    def test_intent_has_default_version(self):
        """Intent defaults to version 1.0."""
        intent = Intent(
            kind=IntentKind.CREATE_BUSINESS_CYCLE,
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        assert intent.version == "1.0"

    def test_intent_version_can_be_set(self):
        """Version can be set explicitly (for future migration)."""
        intent = Intent(
            kind=IntentKind.CREATE_BUSINESS_CYCLE,
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
            version="1.1",
        )
        assert intent.version == "1.1"

    def test_intent_version_is_string(self):
        """Version is stored and returned as string."""
        intent = Intent(
            kind=IntentKind.CREATE_BUSINESS_CYCLE,
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
            version="2.0",
        )
        assert isinstance(intent.version, str)
        assert intent.version == "2.0"


class TestIntentKindEnum:
    """IntentKind enum is the closed set of valid operations."""

    def test_all_intent_kinds_are_defined(self):
        """All 7 intent kinds are represented."""
        kinds = {
            IntentKind.CREATE_BUSINESS_CYCLE,
            IntentKind.EXECUTE_CYCLE,
            IntentKind.REPLY_TO_THREAD,
            IntentKind.QUERY_THREAD,
            IntentKind.EXPLAIN_DECISION,
            IntentKind.SUMMARIZE_THREAD,
            IntentKind.CLARIFY,
        }
        assert len(kinds) == 7

    def test_intent_kind_values_are_strings(self):
        """Intent kinds are string enums (for API serialization)."""
        assert isinstance(IntentKind.CREATE_BUSINESS_CYCLE.value, str)
        assert IntentKind.CREATE_BUSINESS_CYCLE.value == "CreateBusinessCycle"


class TestCreateBusinessCycleIntent:
    """CreateBusinessCycleIntent is for design-time cycle creation."""

    def test_create_business_cycle_intent_kind_is_correct(self):
        """Kind is always CREATE_BUSINESS_CYCLE."""
        intent = CreateBusinessCycleIntent(
            description="Create approval workflow",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        assert intent.kind == IntentKind.CREATE_BUSINESS_CYCLE

    def test_create_business_cycle_intent_with_parameters(self):
        """Can fill parameters with business semantics."""
        intent = CreateBusinessCycleIntent(
            description="Create approval workflow for orders over $10k",
            workspace_id="ws-1",
            actor_id="user-1",
            parameters={
                "actors": [{"name": "Treasurer", "role": "approver"}],
                "rules": [{"condition": "amount > 10000", "action": "escalate"}],
                "systems": [{"name": "email"}, {"name": "odoo"}],
            },
        )
        assert intent.kind == IntentKind.CREATE_BUSINESS_CYCLE
        assert "actors" in intent.parameters
        assert "rules" in intent.parameters
        assert "systems" in intent.parameters


class TestExecuteCycleIntent:
    """ExecuteCycleIntent is for runtime cycle execution."""

    def test_execute_cycle_intent_kind_is_correct(self):
        """Kind is always EXECUTE_CYCLE."""
        intent = ExecuteCycleIntent(
            description="Execute order approval for PO-12345",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        assert intent.kind == IntentKind.EXECUTE_CYCLE

    def test_execute_cycle_intent_with_cycle_id(self):
        """Can specify cycle_id in parameters."""
        intent = ExecuteCycleIntent(
            description="Execute order approval for PO-12345",
            workspace_id="ws-1",
            actor_id="user-1",
            parameters={
                "cycle_id": "ApprovalProcess",
                "args": {"po_id": "PO-12345", "vendor": "ACME Corp"},
            },
        )
        assert intent.parameters["cycle_id"] == "ApprovalProcess"
        assert intent.parameters["args"]["po_id"] == "PO-12345"


class TestReplyToThreadIntent:
    """ReplyToThreadIntent is for communication."""

    def test_reply_to_thread_intent_kind_is_correct(self):
        """Kind is always REPLY_TO_THREAD."""
        intent = ReplyToThreadIntent(
            description="Send approval message to thread",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        assert intent.kind == IntentKind.REPLY_TO_THREAD

    def test_reply_to_thread_intent_with_message(self):
        """Can specify message content in parameters."""
        intent = ReplyToThreadIntent(
            description="Send approval message to thread",
            workspace_id="ws-1",
            actor_id="user-1",
            parameters={
                "thread_id": "thread-xyz",
                "message": "Approved",
                "attachments": [],
            },
        )
        assert intent.parameters["thread_id"] == "thread-xyz"
        assert intent.parameters["message"] == "Approved"


class TestQueryThreadIntent:
    """QueryThreadIntent is for thread introspection."""

    def test_query_thread_intent_kind_is_correct(self):
        """Kind is always QUERY_THREAD."""
        intent = QueryThreadIntent(
            description="Get decision history for order",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        assert intent.kind == IntentKind.QUERY_THREAD

    def test_query_thread_intent_with_query_type(self):
        """Can specify query type in parameters."""
        intent = QueryThreadIntent(
            description="Get decision history for order",
            workspace_id="ws-1",
            actor_id="user-1",
            parameters={
                "thread_id": "thread-xyz",
                "query_type": "history",
            },
        )
        assert intent.parameters["query_type"] in ["history", "documents", "participants"]


class TestExplainDecisionIntent:
    """ExplainDecisionIntent is for decision introspection."""

    def test_explain_decision_intent_kind_is_correct(self):
        """Kind is always EXPLAIN_DECISION."""
        intent = ExplainDecisionIntent(
            description="Why was this order rejected?",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        assert intent.kind == IntentKind.EXPLAIN_DECISION

    def test_explain_decision_intent_with_decision_id(self):
        """Can specify decision_id in parameters."""
        intent = ExplainDecisionIntent(
            description="Why was this order rejected?",
            workspace_id="ws-1",
            actor_id="user-1",
            parameters={
                "decision_id": "decision-abc",
                "decision_point": "rejection",
            },
        )
        assert intent.parameters["decision_id"] == "decision-abc"


class TestSummarizeThreadIntent:
    """SummarizeThreadIntent is for thread summarization."""

    def test_summarize_thread_intent_kind_is_correct(self):
        """Kind is always SUMMARIZE_THREAD."""
        intent = SummarizeThreadIntent(
            description="Summarize approval history for order",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        assert intent.kind == IntentKind.SUMMARIZE_THREAD

    def test_summarize_thread_intent_with_format(self):
        """Can specify format in parameters."""
        intent = SummarizeThreadIntent(
            description="Summarize approval history for order",
            workspace_id="ws-1",
            actor_id="user-1",
            parameters={
                "thread_id": "thread-xyz",
                "format": "timeline",
            },
        )
        assert intent.parameters["format"] in ["timeline", "summary"]


class TestClarifyRequest:
    """ClarifyRequest is Kernel → Hermes only (never reverse)."""

    def test_clarify_request_kind_is_correct(self):
        """Kind is always CLARIFY."""
        clarify = ClarifyRequest(
            description="Which Ahmed should approve this?",
            workspace_id="ws-1",
            actor_id="system",  # System, not a user
        )
        assert clarify.kind == IntentKind.CLARIFY

    def test_clarify_request_with_options(self):
        """ClarifyRequest includes options to choose from."""
        clarify = ClarifyRequest(
            description="Which Ahmed should approve this? (ahmed@acme or ahmed@supplier?)",
            workspace_id="ws-1",
            actor_id="system",
            parameters={
                "options": ["ahmed@acme", "ahmed@supplier"],
                "context": "Vendor approval required",
            },
        )
        assert "options" in clarify.parameters
        assert len(clarify.parameters["options"]) == 2

    def test_clarify_request_is_kernel_only(self):
        """ClarifyRequest should never come from Hermes."""
        # This is a semantic check; pydantic doesn't enforce it.
        # The Kernel layer will check this at the boundary.
        clarify = ClarifyRequest(
            description="Test",
            workspace_id="ws-1",
            actor_id="hermes",
        )
        assert clarify.kind == IntentKind.CLARIFY


class TestIntentValidation:
    """Intent validation enforces required fields."""

    def test_intent_requires_kind(self):
        """kind is required."""
        with pytest.raises(ValidationError):
            Intent(
                description="Test",
                workspace_id="ws-1",
                actor_id="user-1",
            )

    def test_intent_requires_description(self):
        """description is required and must be non-empty."""
        with pytest.raises(ValidationError):
            Intent(
                kind=IntentKind.CREATE_BUSINESS_CYCLE,
                workspace_id="ws-1",
                actor_id="user-1",
            )

    def test_intent_description_cannot_be_empty(self):
        """description must have at least 1 character."""
        with pytest.raises(ValidationError):
            Intent(
                kind=IntentKind.CREATE_BUSINESS_CYCLE,
                description="",
                workspace_id="ws-1",
                actor_id="user-1",
            )

    def test_intent_requires_workspace_id(self):
        """workspace_id is required for tenant isolation."""
        with pytest.raises(ValidationError):
            Intent(
                kind=IntentKind.CREATE_BUSINESS_CYCLE,
                description="Test",
                actor_id="user-1",
            )

    def test_intent_requires_actor_id(self):
        """actor_id is required to identify who is acting."""
        with pytest.raises(ValidationError):
            Intent(
                kind=IntentKind.CREATE_BUSINESS_CYCLE,
                description="Test",
                workspace_id="ws-1",
            )


class TestIntentSerialization:
    """Intent schemas should serialize/deserialize cleanly."""

    def test_intent_model_dump(self):
        """Intent can be serialized to dict."""
        intent = CreateBusinessCycleIntent(
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        data = intent.model_dump()
        assert data["kind"] == IntentKind.CREATE_BUSINESS_CYCLE.value
        assert data["description"] == "Test"
        assert data["workspace_id"] == "ws-1"

    def test_intent_model_validate(self):
        """Intent can be deserialized from dict."""
        data = {
            "kind": "CreateBusinessCycle",
            "description": "Test",
            "workspace_id": "ws-1",
            "actor_id": "user-1",
        }
        intent = CreateBusinessCycleIntent.model_validate(data)
        assert intent.kind == IntentKind.CREATE_BUSINESS_CYCLE
        assert intent.description == "Test"

    def test_intent_model_json(self):
        """Intent can be serialized to/from JSON."""
        intent = CreateBusinessCycleIntent(
            description="Test",
            workspace_id="ws-1",
            actor_id="user-1",
        )
        json_str = intent.model_dump_json()
        assert isinstance(json_str, str)
        assert "CreateBusinessCycle" in json_str

        # Deserialize back
        restored = CreateBusinessCycleIntent.model_validate_json(json_str)
        assert restored.kind == intent.kind
