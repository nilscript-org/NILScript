"""Tests for BusinessSpecification models — serialization, validation, edge cases."""

import json

import pytest

from nilscript.hermes.models import (
    Actor,
    BusinessEvent,
    BusinessRule,
    BusinessSpecification,
    Document,
    ExternalSystem,
)


class TestActorModel:
    def test_actor_minimal(self):
        a = Actor(
            name="Manager",
            role="approver",
            responsibilities=("approve invoices",),
        )
        assert a.name == "Manager"
        assert a.role == "approver"
        assert len(a.responsibilities) == 1

    def test_actor_with_interactions(self):
        a = Actor(
            name="Manager",
            role="approver",
            responsibilities=("approve", "notify"),
            interactions=("Finance", "Accounting"),
        )
        assert a.interactions == ("Finance", "Accounting")

    def test_actor_json_serialization(self):
        a = Actor(
            name="Manager",
            role="approver",
            responsibilities=("approve",),
        )
        j = a.model_dump(mode="json")
        assert j["name"] == "Manager"
        parsed = json.loads(json.dumps(j))
        assert parsed["role"] == "approver"

    def test_actor_name_required(self):
        with pytest.raises(ValueError):
            Actor(name="", role="approver", responsibilities=("approve",))

    def test_actor_name_max_length(self):
        with pytest.raises(ValueError):
            Actor(
                name="x" * 201,
                role="approver",
                responsibilities=("approve",),
            )

    def test_actor_responsibilities_required(self):
        with pytest.raises(ValueError):
            Actor(
                name="Manager",
                role="approver",
                responsibilities=(),
            )


class TestExternalSystemModel:
    def test_system_minimal(self):
        s = ExternalSystem(
            name="Odoo",
            purpose="order management",
            interfaces=("REST API",),
            integration_points=("create_order",),
        )
        assert s.name == "Odoo"
        assert "REST API" in s.interfaces

    def test_system_json_round_trip(self):
        s = ExternalSystem(
            name="Salesforce",
            purpose="customer data",
            interfaces=("SOAP", "REST"),
            integration_points=("query_lead", "update_account"),
        )
        j = s.model_dump(mode="json")
        text = json.dumps(j)
        parsed = json.loads(text)
        s2 = ExternalSystem(**parsed)
        assert s2.name == s.name

    def test_system_interfaces_required(self):
        with pytest.raises(ValueError):
            ExternalSystem(
                name="Odoo",
                purpose="test",
                interfaces=(),
                integration_points=("test",),
            )


class TestBusinessRuleModel:
    def test_rule_default_tier(self):
        r = BusinessRule(
            condition="amount > 10000",
            action="escalate",
            consequence="delayed approval",
        )
        assert r.tier == "MEDIUM"

    def test_rule_high_tier(self):
        r = BusinessRule(
            condition="critical",
            action="halt",
            consequence="manual intervention",
            tier="CRITICAL",
        )
        assert r.tier == "CRITICAL"

    def test_rule_invalid_tier(self):
        with pytest.raises(ValueError):
            BusinessRule(
                condition="x",
                action="y",
                consequence="z",
                tier="INVALID",
            )

    def test_rule_all_tiers_valid(self):
        for tier in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            r = BusinessRule(
                condition="test",
                action="test",
                consequence="test",
                tier=tier,
            )
            assert r.tier == tier


class TestBusinessEventModel:
    def test_event_minimal(self):
        e = BusinessEvent(
            trigger="invoice submitted",
            participants=("Finance", "Manager"),
            outcome="approval opens",
            frequency="per transaction",
        )
        assert e.trigger == "invoice submitted"

    def test_event_json_serialization(self):
        e = BusinessEvent(
            trigger="order placed",
            participants=("Sales", "Warehouse"),
            outcome="fulfillment starts",
            frequency="daily",
        )
        j = json.dumps(e.model_dump(mode="json"))
        parsed = json.loads(j)
        assert parsed["trigger"] == "order placed"

    def test_event_participants_required(self):
        with pytest.raises(ValueError):
            BusinessEvent(
                trigger="test",
                participants=(),
                outcome="test",
                frequency="test",
            )


class TestDocumentModel:
    def test_document_minimal(self):
        d = Document(
            name="Invoice",
            format="PDF",
            storage_location="Odoo",
            usage="approval artifact",
        )
        assert d.name == "Invoice"

    def test_document_json_serialization(self):
        d = Document(
            name="Purchase Order",
            format="JSON",
            storage_location="S3",
            usage="audit trail",
        )
        j = d.model_dump(mode="json")
        text = json.dumps(j)
        assert "Purchase Order" in text


class TestBusinessSpecification:
    def test_spec_minimal_valid(self):
        spec = BusinessSpecification(
            domain_name="Procurement",
            intent="Process and approve purchase orders",
            actors=(
                Actor(
                    name="Buyer",
                    role="requester",
                    responsibilities=("submit order",),
                ),
            ),
            systems=(
                ExternalSystem(
                    name="Odoo",
                    purpose="order management",
                    interfaces=("API",),
                    integration_points=("create",),
                ),
            ),
            documents=(),
            events=(
                BusinessEvent(
                    trigger="order submitted",
                    participants=("Buyer", "Odoo"),
                    outcome="approval starts",
                    frequency="daily",
                ),
            ),
            rules=(),
        )
        assert spec.domain_name == "Procurement"
        assert len(spec.actors) == 1

    def test_spec_with_all_fields(self):
        spec = BusinessSpecification(
            domain_name="Invoicing",
            intent="Invoice lifecycle management",
            actors=(
                Actor(
                    name="Manager",
                    role="approver",
                    responsibilities=("review", "approve"),
                ),
                Actor(
                    name="Accountant",
                    role="processor",
                    responsibilities=("record",),
                ),
            ),
            systems=(
                ExternalSystem(
                    name="Odoo",
                    purpose="backend",
                    interfaces=("API",),
                    integration_points=("read", "write"),
                ),
            ),
            documents=(
                Document(
                    name="Invoice",
                    format="PDF",
                    storage_location="Odoo",
                    usage="artifact",
                ),
            ),
            events=(
                BusinessEvent(
                    trigger="invoice created",
                    participants=("Manager", "Odoo"),
                    outcome="approval gate opens",
                    frequency="per transaction",
                ),
            ),
            rules=(
                BusinessRule(
                    condition="amount > 5000",
                    action="escalate",
                    consequence="CFO approval required",
                    tier="HIGH",
                ),
            ),
        )
        assert len(spec.actors) == 2
        assert len(spec.rules) == 1

    def test_spec_json_round_trip(self):
        spec = BusinessSpecification(
            domain_name="Test Domain",
            intent="Test intent",
            actors=(
                Actor(
                    name="Actor1",
                    role="role1",
                    responsibilities=("resp1",),
                ),
            ),
            systems=(
                ExternalSystem(
                    name="System1",
                    purpose="purpose1",
                    interfaces=("iface1",),
                    integration_points=("point1",),
                ),
            ),
            documents=(),
            events=(
                BusinessEvent(
                    trigger="event1",
                    participants=("Actor1",),
                    outcome="outcome1",
                    frequency="freq1",
                ),
            ),
            rules=(),
        )
        j = json.dumps(spec.model_dump(mode="json"))
        parsed = json.loads(j)
        spec2 = BusinessSpecification(**parsed)
        assert spec2.domain_name == spec.domain_name
        assert len(spec2.actors) == len(spec.actors)

    def test_spec_invalid_participant_reference(self):
        with pytest.raises(ValueError, match="undefined participant"):
            BusinessSpecification(
                domain_name="Test",
                intent="Test",
                actors=(
                    Actor(
                        name="Actor1",
                        role="role1",
                        responsibilities=("resp1",),
                    ),
                ),
                systems=(),
                documents=(),
                events=(
                    BusinessEvent(
                        trigger="event1",
                        participants=("UndefinedActor",),
                        outcome="outcome1",
                        frequency="freq1",
                    ),
                ),
                rules=(),
            )

    def test_spec_actor_required(self):
        with pytest.raises(ValueError):
            BusinessSpecification(
                domain_name="Test",
                intent="Test",
                actors=(),
                systems=(
                    ExternalSystem(
                        name="System1",
                        purpose="p",
                        interfaces=("i",),
                        integration_points=("p",),
                    ),
                ),
                events=(
                    BusinessEvent(
                        trigger="e",
                        participants=("System1",),
                        outcome="o",
                        frequency="f",
                    ),
                ),
            )

    def test_spec_event_required(self):
        with pytest.raises(ValueError):
            BusinessSpecification(
                domain_name="Test",
                intent="Test",
                actors=(
                    Actor(
                        name="A",
                        role="r",
                        responsibilities=("resp",),
                    ),
                ),
                systems=(),
                events=(),
            )

    def test_spec_documents_optional(self):
        spec = BusinessSpecification(
            domain_name="Test",
            intent="Test",
            actors=(
                Actor(
                    name="A",
                    role="r",
                    responsibilities=("resp",),
                ),
            ),
            systems=(),
            documents=(),
            events=(
                BusinessEvent(
                    trigger="e",
                    participants=("A",),
                    outcome="o",
                    frequency="f",
                ),
            ),
            rules=(),
        )
        assert len(spec.documents) == 0
        assert len(spec.rules) == 0
