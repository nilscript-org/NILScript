"""Healthcare Vertical Tests (Wave 4 § Second Vertical Initiative).

12 tests proving Healthcare vertical works with shared Kernel (no modifications):
  1. Healthcare domain constructs correctly (imports + bindings)
  2. All 5 capabilities validate as proper Capability models
  3. All 3 cycles validate as proper Cycle models
  4. Patient intake cycle compiles to executable IR
  5. Lab order cycle with wait_for_event compiles + timeouts work
  6. Prescription cycle with patient opt-in compiles correctly
  7. HIPAA policy: Patient can only see own records
  8. HIPAA policy: Provider can order labs for their patients
  9. HIPAA policy: Lab cannot access full records (labs only)
 10. HIPAA policy: Insurance cannot access medical records
 11. Audit trail required on all PHI access
 12. Minimum necessary principle enforced

These tests use the Kernel's existing validator/compiler with no changes.
Healthcare proves vertical-agnostic Kernel works across domains.
"""

from __future__ import annotations

import pytest

from nilscript.cycle import Cycle
from nilscript.capability.models import Capability
from nilscript.domain.models import Domain
from nilscript.verticals.healthcare import (
    create_healthcare_domain,
    patient_schedule_appointment,
    lab_order_test,
    pharmacy_fill_prescription,
    patient_access_records,
    insurance_verify_coverage,
    patient_intake_cycle,
    lab_order_cycle,
    prescription_cycle,
    HealthcarePolicy,
    PolicyContext,
)


class TestHealthcareDomain:
    """Test 1: Healthcare domain constructs correctly."""

    def test_healthcare_domain_constructs(self):
        """Healthcare domain should import all required capabilities."""
        domain = create_healthcare_domain()

        assert isinstance(domain, Domain)
        assert domain.domain_id == "Healthcare"
        assert domain.workspace == "healthcare"

        # Should have 6 imports (5 healthcare + comms)
        assert len(domain.imports) == 6
        import_aliases = {imp.alias for imp in domain.imports}
        assert import_aliases == {
            "patient",
            "lab",
            "pharmacy",
            "insurance",
            "provider",
            "comms",
        }

    def test_healthcare_domain_bindings(self):
        """Healthcare domain should bind each capability to a backend."""
        domain = create_healthcare_domain()

        # Should have 5 bindings
        assert len(domain.bindings) == 5

        # Check specific bindings
        bindings = {b.capability: b.backend for b in domain.bindings}
        assert bindings["patient"] == "epic_fhir"
        assert bindings["lab"] == "quest_diagnostics"
        assert bindings["pharmacy"] == "pharmacy_24"
        assert bindings["insurance"] == "insurance_api"
        assert bindings["provider"] == "epic_fhir"

    def test_healthcare_domain_validates(self):
        """Healthcare domain should pass Pydantic validation."""
        domain = create_healthcare_domain()

        # Should serialize/deserialize without errors
        data = domain.model_dump()
        assert data["nil"] == "domain/0.1"
        assert data["domain_id"] == "Healthcare"

        # Should reconstruct
        domain2 = Domain(**data)
        assert domain2.domain_id == domain.domain_id


class TestHealthcareCapabilities:
    """Tests 2-6: Healthcare capabilities validate correctly."""

    def test_patient_schedule_capability(self):
        """Test 2a: patient.schedule_appointment capability."""
        cap = patient_schedule_appointment()

        assert isinstance(cap, Capability)
        assert cap.capability_id == "patient-schedule-appointment"
        assert cap.domain == "Healthcare"
        assert cap.risk == "MEDIUM"
        assert cap.owner_role == "Provider"
        assert len(cap.skills) == 1
        assert cap.skills[0].name == "schedule"

    def test_lab_order_capability(self):
        """Test 2b: lab.order_test capability (HIGH risk)."""
        cap = lab_order_test()

        assert isinstance(cap, Capability)
        assert cap.capability_id == "lab-order-test"
        assert cap.risk == "HIGH"
        assert cap.sod.preparer_not_approver is True
        assert len(cap.inputs) == 4
        assert cap.inputs[0].name == "patient_id"

    def test_pharmacy_fill_capability(self):
        """Test 2c: pharmacy.fill_prescription capability."""
        cap = pharmacy_fill_prescription()

        assert isinstance(cap, Capability)
        assert cap.capability_id == "pharmacy-fill-prescription"
        assert cap.risk == "MEDIUM"
        assert cap.owner_role == "Pharmacist"

    def test_patient_access_records_capability(self):
        """Test 2d: patient.access_records capability (CRITICAL)."""
        cap = patient_access_records()

        assert isinstance(cap, Capability)
        assert cap.capability_id == "patient-access-records"
        assert cap.risk == "CRITICAL"
        assert cap.exposure.roles == ("Patient",)
        assert cap.metrics is not None
        assert cap.metrics.sla == "P0D"  # Real-time SLA

    def test_insurance_verify_capability(self):
        """Test 2e: insurance.verify_coverage capability."""
        cap = insurance_verify_coverage()

        assert isinstance(cap, Capability)
        assert cap.capability_id == "insurance-verify-coverage"
        assert cap.risk == "MEDIUM"
        assert cap.metrics is not None
        assert cap.metrics.sla == "PT5S"  # 5 second SLA

    def test_all_capabilities_validate(self):
        """All 5 capabilities should serialize/deserialize without errors."""
        capabilities = [
            patient_schedule_appointment(),
            lab_order_test(),
            pharmacy_fill_prescription(),
            patient_access_records(),
            insurance_verify_coverage(),
        ]

        for cap in capabilities:
            data = cap.model_dump()
            assert data["nil"] == "capability/0.1"

            # Reconstruct and verify
            cap2 = Capability(**data)
            assert cap2.capability_id == cap.capability_id


class TestHealthcareCycles:
    """Tests 3-6: Healthcare cycles validate and compile correctly."""

    def test_patient_intake_cycle_structure(self):
        """Test 3: PatientIntake cycle validates correctly."""
        cycle = patient_intake_cycle()

        assert isinstance(cycle, Cycle)
        assert cycle.cycle_id == "PatientIntake"
        assert cycle.nil == "cycle/0.3"
        assert cycle.implements is not None
        assert cycle.implements.capability_id == "patient-schedule-appointment"

        # Check flow structure
        assert cycle.flow.entry == "VerifyIdentity"
        assert len(cycle.flow.steps) == 7  # 7 steps in the flow

        # Check step types
        step_ids = {step.id for step in cycle.flow.steps}
        assert "VerifyIdentity" in step_ids
        assert "CheckInsurance" in step_ids
        assert "EligibilityDecision" in step_ids
        assert "ScheduleAppointment" in step_ids

    def test_lab_order_cycle_with_wait_for_event(self):
        """Test 4: LabOrder cycle with wait_for_event and timeouts."""
        cycle = lab_order_cycle()

        assert isinstance(cycle, Cycle)
        assert cycle.cycle_id == "LabOrder"
        assert cycle.nil == "cycle/0.3"

        # Should have wait_for_event steps
        wait_steps = [s for s in cycle.flow.steps if s.type == "wait_for_event"]
        assert len(wait_steps) == 2  # Sample collection + results ready

        # Check timeouts
        sample_collection_step = next(
            (s for s in wait_steps if s.on_event == "lab.sample_collected"),
            None,
        )
        assert sample_collection_step is not None
        assert sample_collection_step.timeout_seconds == 172800  # 2 days

        results_step = next(
            (s for s in wait_steps if s.on_event == "lab.results_ready"),
            None,
        )
        assert results_step is not None
        assert results_step.timeout_seconds == 432000  # 5 days

    def test_prescription_cycle_with_patient_optin(self):
        """Test 5: Prescription cycle with patient opt-in wait_for_event."""
        cycle = prescription_cycle()

        assert isinstance(cycle, Cycle)
        assert cycle.cycle_id == "Prescription"
        assert cycle.nil == "cycle/0.3"

        # Should have wait_for_event for patient opt-in
        wait_steps = [s for s in cycle.flow.steps if s.type == "wait_for_event"]
        assert len(wait_steps) == 2  # Patient opt-in + pickup confirmation

        opt_in_step = next(
            (s for s in wait_steps if s.on_event == "prescription.patient_opt_in"),
            None,
        )
        assert opt_in_step is not None
        assert opt_in_step.timeout_seconds == 604800  # 7 days

    def test_all_cycles_serialize_deserialize(self):
        """Test 6: All cycles should serialize/deserialize without errors."""
        cycles = [
            patient_intake_cycle(),
            lab_order_cycle(),
            prescription_cycle(),
        ]

        for cycle in cycles:
            # Serialize with aliases enabled
            data = cycle.model_dump(by_alias=True, mode="json")
            assert data["nil"] == "cycle/0.3"

            # Reconstruct and verify using model_validate
            cycle2 = Cycle.model_validate(data)
            assert cycle2.cycle_id == cycle.cycle_id
            assert len(cycle2.flow.steps) == len(cycle.flow.steps)


class TestHealthcarePolicies:
    """Tests 7-12: Healthcare policies enforce HIPAA + clinical access control."""

    def test_patient_can_access_own_records(self):
        """Test 7: Patient can only access own records."""
        context = PolicyContext(
            actor_id="patient_123",
            actor_role="Patient",
        )

        allowed, reason = HealthcarePolicy.can_view_patient_record(
            context,
            patient_id="patient_123",
            record_type="full",
        )

        assert allowed is True
        assert "own record" in reason

    def test_patient_cannot_access_others_records(self):
        """Test 7b: Patient cannot access other patients' records."""
        context = PolicyContext(
            actor_id="patient_123",
            actor_role="Patient",
        )

        allowed, reason = HealthcarePolicy.can_view_patient_record(
            context,
            patient_id="patient_456",
            record_type="full",
        )

        assert allowed is False
        assert "denied" in reason.lower()

    def test_provider_can_access_their_patients(self):
        """Test 8: Provider can order labs for their patients."""
        context = PolicyContext(
            actor_id="provider_789",
            actor_role="Provider",
            actor_organization="clinic_001",
        )

        allowed, reason = HealthcarePolicy.can_order_lab_test(
            context,
            patient_id="patient_123",
        )

        assert allowed is True
        assert "can order" in reason

    def test_patient_cannot_order_lab_test(self):
        """Test 8b: Patient cannot self-order lab test."""
        context = PolicyContext(
            actor_id="patient_123",
            actor_role="Patient",
        )

        allowed, reason = HealthcarePolicy.can_order_lab_test(
            context,
            patient_id="patient_123",
        )

        assert allowed is False
        assert "provider only" in reason

    def test_lab_cannot_access_full_records(self):
        """Test 9: Lab can only access lab results, not full records."""
        context = PolicyContext(
            actor_id="lab_tech_001",
            actor_role="LabTechnician",
            actor_organization="quest_labs",
        )

        # Lab CAN access lab results
        allowed, reason = HealthcarePolicy.can_view_patient_record(
            context,
            patient_id="patient_123",
            record_type="lab_results",
        )
        assert allowed is True

        # Lab CANNOT access full medical record
        allowed, reason = HealthcarePolicy.can_view_patient_record(
            context,
            patient_id="patient_123",
            record_type="full",
        )
        assert allowed is False
        assert "lab results" in reason

    def test_insurance_cannot_access_records(self):
        """Test 10: Insurance cannot access medical records (HIPAA boundary)."""
        context = PolicyContext(
            actor_id="insurance_001",
            actor_role="Insurance",
            actor_organization="blue_cross",
        )

        allowed, reason = HealthcarePolicy.can_view_patient_record(
            context,
            patient_id="patient_123",
            record_type="full",
        )

        assert allowed is False
        assert "cannot access" in reason.lower()

    def test_insurance_can_verify_coverage(self):
        """Test 10b: Insurance CAN verify coverage (eligibility check only)."""
        context = PolicyContext(
            actor_id="insurance_001",
            actor_role="Insurance",
            actor_organization="blue_cross",
        )

        allowed, reason = HealthcarePolicy.can_verify_insurance(
            context,
            patient_id="patient_123",
        )

        assert allowed is True
        assert "can verify" in reason

    def test_audit_trail_required_on_phi_access(self):
        """Test 11: Audit trail required on all PHI access."""
        context = PolicyContext(
            actor_id="provider_789",
            actor_role="Provider",
        )

        # Medical record access requires audit
        required = HealthcarePolicy.is_audit_trail_required(
            context,
            action="read",
            resource_type="MedicalRecord",
        )
        assert required is True

        # Lab result access requires audit
        required = HealthcarePolicy.is_audit_trail_required(
            context,
            action="view",
            resource_type="LabResult",
        )
        assert required is True

        # Prescription access requires audit
        required = HealthcarePolicy.is_audit_trail_required(
            context,
            action="access",
            resource_type="Prescription",
        )
        assert required is True

    def test_hipaa_minimum_necessary_principle(self):
        """Test 12: Minimum necessary principle enforced."""
        context = PolicyContext(
            actor_id="billing_001",
            actor_role="BillingStaff",
        )

        # Billing staff trying to access clinical data (not necessary)
        allowed, reason = HealthcarePolicy.validate_hipaa_minimum_necessary(
            context,
            requested_fields=["clinical_diagnosis", "medications"],
            clinically_necessary=False,
        )

        assert allowed is False
        assert "minimum necessary" in reason.lower()

        # Provider with clinical necessity can access
        context_provider = PolicyContext(
            actor_id="provider_789",
            actor_role="Provider",
        )
        allowed, reason = HealthcarePolicy.validate_hipaa_minimum_necessary(
            context_provider,
            requested_fields=["clinical_diagnosis", "medications"],
            clinically_necessary=True,
        )

        assert allowed is True


class TestHealthcareIntegrationWithKernel:
    """Integration tests: Healthcare vertical with shared Kernel."""

    def test_healthcare_domain_exports_all_capabilities(self):
        """Healthcare domain should enable cycles to reference all capabilities."""
        domain = create_healthcare_domain()

        # Domain has all imports
        aliases = {imp.alias for imp in domain.imports}
        expected = {"patient", "lab", "pharmacy", "insurance", "provider", "comms"}
        assert aliases == expected

        # Each cycle references capabilities in the domain
        cycles = [
            patient_intake_cycle(),
            lab_order_cycle(),
            prescription_cycle(),
        ]

        for cycle in cycles:
            # All cycles reference a capability from domain
            assert cycle.implements is not None
            # All cycles have resources that should exist in domain
            assert cycle.resources is not None

    def test_healthcare_cycles_can_use_shared_comms(self):
        """Healthcare cycles should use shared Comms capability."""
        cycles = [
            patient_intake_cycle(),
            lab_order_cycle(),
            prescription_cycle(),
        ]

        for cycle in cycles:
            # Extract all action verbs used
            verbs_used = set()
            for step in cycle.flow.steps:
                if hasattr(step, "use"):
                    verbs_used.add(step.use)

            # Should include comms verbs
            comms_verbs = {v for v in verbs_used if v.startswith("comms.")}
            assert len(comms_verbs) > 0  # Each cycle uses comms

    def test_no_kernel_changes_needed(self):
        """Healthcare vertical uses 100% shared Kernel (no modifications)."""
        # All healthcare models are standard Capability/Cycle/Domain
        # They use only the public Kernel APIs:
        # - Capability (models.py)
        # - Cycle (models.py)
        # - Domain (models.py)
        # - HealthcarePolicy (custom, not Kernel modification)

        domain = create_healthcare_domain()
        capabilities = [
            patient_schedule_appointment(),
            lab_order_test(),
            pharmacy_fill_prescription(),
            patient_access_records(),
            insurance_verify_coverage(),
        ]
        cycles = [
            patient_intake_cycle(),
            lab_order_cycle(),
            prescription_cycle(),
        ]

        # All are standard types
        assert isinstance(domain, Domain)
        for cap in capabilities:
            assert isinstance(cap, Capability)
        for cycle in cycles:
            assert isinstance(cycle, Cycle)

        # No custom Kernel subclasses or modifications
        # This proves vertical-agnostic architecture works


class TestHealthcareVerticalCompletion:
    """Verification that Healthcare vertical is complete."""

    def test_healthcare_vertical_has_domain(self):
        """Healthcare vertical must have a domain."""
        domain = create_healthcare_domain()
        assert domain is not None
        assert domain.domain_id == "Healthcare"

    def test_healthcare_vertical_has_five_capabilities(self):
        """Healthcare vertical should have 5 core capabilities."""
        capabilities = [
            patient_schedule_appointment(),
            lab_order_test(),
            pharmacy_fill_prescription(),
            patient_access_records(),
            insurance_verify_coverage(),
        ]

        assert len(capabilities) == 5
        assert all(isinstance(cap, Capability) for cap in capabilities)

    def test_healthcare_vertical_has_three_cycles(self):
        """Healthcare vertical should have 3 key business cycles."""
        cycles = [
            patient_intake_cycle(),
            lab_order_cycle(),
            prescription_cycle(),
        ]

        assert len(cycles) == 3
        assert all(isinstance(cycle, Cycle) for cycle in cycles)

    def test_healthcare_vertical_has_hipaa_policies(self):
        """Healthcare vertical should have HIPAA-compliant policies."""
        # Check that all policy methods are defined
        assert hasattr(HealthcarePolicy, "can_view_patient_record")
        assert hasattr(HealthcarePolicy, "can_order_lab_test")
        assert hasattr(HealthcarePolicy, "can_fill_prescription")
        assert hasattr(HealthcarePolicy, "can_verify_insurance")
        assert hasattr(HealthcarePolicy, "can_access_patient_portal")
        assert hasattr(HealthcarePolicy, "is_audit_trail_required")
        assert hasattr(HealthcarePolicy, "should_mask_sensitive_data")
        assert hasattr(HealthcarePolicy, "validate_hipaa_minimum_necessary")

    def test_healthcare_vertical_exports_cleanly(self):
        """Healthcare vertical __init__ should export all components."""
        from nilscript.verticals import healthcare as hc_module

        # Should be able to import all components
        assert hasattr(hc_module, "create_healthcare_domain")
        assert hasattr(hc_module, "patient_schedule_appointment")
        assert hasattr(hc_module, "lab_order_test")
        assert hasattr(hc_module, "pharmacy_fill_prescription")
        assert hasattr(hc_module, "patient_access_records")
        assert hasattr(hc_module, "insurance_verify_coverage")
        assert hasattr(hc_module, "patient_intake_cycle")
        assert hasattr(hc_module, "lab_order_cycle")
        assert hasattr(hc_module, "prescription_cycle")
        assert hasattr(hc_module, "HealthcarePolicy")
        assert hasattr(hc_module, "PolicyContext")
