"""Healthcare Vertical Domain (Wave 4 Architecture Proof § Second Vertical Initiative).

The Healthcare Domain demonstrates that the Kernel and shared Comms layer
scale across verticals WITHOUT modification. Uses 100% shared Kernel + Comms,
with vertical-specific:
  - Capabilities: patient.schedule_appointment, lab.order_test, etc.
  - Cycles: PatientIntake, LabOrder, Prescription
  - Policies: HIPAA access control, MRN identity, provider roster
  - Adapters: FHIR/Epic, Quest Labs, Pharmacy, Insurance APIs

Binding strategy (D8):
  - patient.schedule_appointment → epic_fhir (read-write)
  - lab.order_test → quest_diagnostics (order management)
  - pharmacy.fill_prescription → pharmacy_24 (fulfillment)
  - insurance.verify_coverage → insurance_api (eligibility)
"""

from __future__ import annotations

from nilscript.domain.models import BackendBinding, CapabilityImport, Domain


def create_healthcare_domain() -> Domain:
    """Factory for Healthcare domain definition.

    Imports healthcare-specific capabilities and binds backends per capability.
    This demonstrates:
      1. Vertical isolation: healthcare domain has no access to finance/sales capabilities
      2. Backend routing (D8): explicit per-capability system binding
      3. Permission boundary (D2): cycles in this domain see only these imports
    """
    return Domain(
        nil="domain/0.1",
        domain_id="Healthcare",
        workspace="healthcare",
        imports=(
            # Patient Management
            CapabilityImport(
                capability="patient",
                major=1,
                alias="patient",
            ),
            # Lab Services
            CapabilityImport(
                capability="lab",
                major=1,
                alias="lab",
            ),
            # Pharmacy Operations
            CapabilityImport(
                capability="pharmacy",
                major=1,
                alias="pharmacy",
            ),
            # Insurance & Payer Integration
            CapabilityImport(
                capability="insurance",
                major=1,
                alias="insurance",
            ),
            # Provider Management
            CapabilityImport(
                capability="provider",
                major=1,
                alias="provider",
            ),
            # Comms (shared): email, WhatsApp, SMS
            CapabilityImport(
                capability="Communication",
                major=2,
                alias="comms",
            ),
        ),
        bindings=(
            # Epic EHR for patient scheduling + records
            BackendBinding(
                capability="patient",
                backend="epic_fhir",
            ),
            # Quest Labs for lab ordering
            BackendBinding(
                capability="lab",
                backend="quest_diagnostics",
            ),
            # Pharmacy fulfillment
            BackendBinding(
                capability="pharmacy",
                backend="pharmacy_24",
            ),
            # Insurance eligibility verification
            BackendBinding(
                capability="insurance",
                backend="insurance_api",
            ),
            # Provider directory
            BackendBinding(
                capability="provider",
                backend="epic_fhir",
            ),
        ),
    )
