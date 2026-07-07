"""Business Discovery Models — the Intent Specification layer (L1.5 between Hermes and BizSpec).

This is the schema that a Business Discovery Session extracts from conversational exchange. It is
a DATA model only: structured entities, fully JSON-serializable, no logic. The Semantic Compiler
consumes this to produce a BizSpec (L2), which then lowers to Cycle (L3).

Frozen: extra="forbid" — an unknown field is unrepresentable and rejected at validation time.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from nilscript.kernel.models import DslModel


class Actor(DslModel):
    """A participant in a business process (human, role, system).

    name: Human-readable identifier (e.g. "Sales Manager", "Invoice Approver")
    role: Functional role in the domain (e.g. "approver", "requester", "processor")
    responsibilities: Ordered list of actions this actor performs
    interactions: Which other actors or systems this actor interacts with
    """

    name: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=100)
    responsibilities: tuple[str, ...] = Field(min_length=1, max_length=20)
    interactions: tuple[str, ...] = ()  # names of other actors


class ExternalSystem(DslModel):
    """A third-party system or backend that the cycle integrates with.

    name: System identifier (e.g. "Odoo", "Salesforce", "Email")
    purpose: Why this system is in the flow (e.g. "order fulfillment", "customer data")
    interfaces: How the system is accessed (e.g. "REST API", "SMTP", "Webhook")
    integration_points: Specific operations or data exchanges (e.g. ["create_order", "fetch_customer"])
    """

    name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=500)
    interfaces: tuple[str, ...] = Field(min_length=1, max_length=10)
    integration_points: tuple[str, ...] = Field(min_length=1, max_length=30)


class Document(DslModel):
    """A persistent artifact in the business process (invoice, quote, email, etc.).

    name: Document type (e.g. "Invoice", "Purchase Order", "Email")
    format: Structure or encoding (e.g. "PDF", "JSON", "plain text", "HTML email")
    storage_location: Where the document is stored or transmitted (e.g. "Odoo", "Email", "S3")
    usage: Why this document matters (e.g. "approval artifact", "audit trail", "notification")
    """

    name: str = Field(min_length=1, max_length=200)
    format: str = Field(min_length=1, max_length=100)
    storage_location: str = Field(min_length=1, max_length=200)
    usage: str = Field(min_length=1, max_length=300)


class BusinessEvent(DslModel):
    """A significant state transition or milestone in the process.

    trigger: What initiates this event (e.g. "invoice submitted", "payment received")
    participants: Which actors/systems are involved
    outcome: What changes as a result (e.g. "approval gate opens", "notification sent")
    frequency: How often (e.g. "per transaction", "daily", "on demand")
    """

    trigger: str = Field(min_length=1, max_length=300)
    participants: tuple[str, ...] = Field(min_length=1, max_length=20)
    outcome: str = Field(min_length=1, max_length=300)
    frequency: str = Field(min_length=1, max_length=100)


class BusinessRule(DslModel):
    """A constraint, gate, or decision logic that governs the process.

    condition: The predicate (e.g. "amount > 10000", "status is pending")
    action: What happens if the condition is true (e.g. "escalate to manager", "block and notify")
    consequence: Business impact (e.g. "delayed approval", "audit required")
    tier: Governance tier (LOW|MEDIUM|HIGH|CRITICAL) — affects approval routing
    """

    condition: str = Field(min_length=1, max_length=300)
    action: str = Field(min_length=1, max_length=300)
    consequence: str = Field(min_length=1, max_length=300)
    tier: Annotated[str, Field(pattern=r"^(LOW|MEDIUM|HIGH|CRITICAL)$")] = "MEDIUM"


class BusinessSpecification(DslModel):
    """The complete extracted specification from a discovery session.

    This is the output of BusinessDiscoverySession.extract_structured_specification().
    It is a pure data model: no logic, no runtime state. Fully JSON-serializable via Pydantic.
    The Wave 4 Semantic Compiler consumes this and produces a BizSpec (L2).
    """

    domain_name: str = Field(
        min_length=1, max_length=200, description="e.g. 'Procurement', 'Invoicing'"
    )
    intent: str = Field(min_length=1, max_length=1000, description="One-sentence business goal")
    actors: tuple[Actor, ...] = Field(min_length=1, max_length=50)
    systems: tuple[ExternalSystem, ...] = Field(min_length=0, max_length=50)
    documents: tuple[Document, ...] = Field(min_length=0, max_length=100)
    events: tuple[BusinessEvent, ...] = Field(min_length=1, max_length=100)
    rules: tuple[BusinessRule, ...] = Field(min_length=0, max_length=200)

    @model_validator(mode="after")
    def validate_references(self) -> BusinessSpecification:
        """Ensure all actor/system names referenced in rules/events are defined."""
        actor_names = {a.name for a in self.actors}
        system_names = {s.name for s in self.systems}
        all_names = actor_names | system_names

        for event in self.events:
            for participant in event.participants:
                if participant not in all_names:
                    raise ValueError(
                        f"BusinessEvent references undefined participant '{participant}'. "
                        f"Defined: {all_names}"
                    )

        return self
