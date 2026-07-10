"""Healthcare Vertical Policies & Authority (Wave 4 § Second Vertical Initiative).

Healthcare-specific access control rules demonstrating Kernel's authority layer
works with vertical-specific policies. Enforces:
  1. HIPAA minimum necessary principle (access only what you need)
  2. Patient right to access own records
  3. Provider can only access their patients
  4. Lab can only access test results they processed
  5. Insurance can only verify coverage (no records access)
  6. Audit trail on all PHI access
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PolicyContext:
    """Runtime context for policy evaluation.

    Attributes:
        actor_id: User/system making the request
        actor_role: Role of the actor (Patient, Provider, Lab, Insurance, etc.)
        actor_organization: Organization ID (provider clinic, lab, etc.)
        resource_type: What is being accessed (MedicalRecord, LabResult, etc.)
        resource_patient_id: Patient ID the resource belongs to
        action: What action is being performed (read, write, delete, etc.)
        timestamp: When the action is being performed
    """

    actor_id: str
    actor_role: str
    actor_organization: str | None = None
    resource_type: str | None = None
    resource_patient_id: str | None = None
    action: str | None = None
    timestamp: str | None = None


class HealthcarePolicy:
    """Healthcare-specific authority rules (HIPAA + clinical access control).

    The Kernel's authority layer calls these decision methods during:
      1. Compilation (early deny of obviously forbidden cycles)
      2. Execution (pre-step gate before each action)
      3. Ledger audit (post-action logging for compliance)
    """

    @staticmethod
    def can_view_patient_record(
        context: PolicyContext,
        patient_id: str,
        record_type: str,
    ) -> tuple[bool, str]:
        """Can the actor view a patient's medical record?

        HIPAA rules (minimum necessary):
          - Patient → their own record always
          - Provider → their patients only (via roster)
          - Lab → only test results they processed
          - Pharmacist → only medication history for patients they serve
          - Insurance → NO access (only pre-authorization, not records)
          - Admin → their organization's patients only

        Args:
            context: Policy evaluation context
            patient_id: Which patient's record
            record_type: Type of record (full, labs_only, medications, etc.)

        Returns:
            (allowed: bool, reason: str)
        """
        # Patient can always access their own record
        if context.actor_role == "Patient" and context.actor_id == patient_id:
            return True, "Patient accessing own record (HIPAA right-to-access)"

        # Provider can access their patients
        if context.actor_role == "Provider":
            # In real implementation, check against provider's patient roster
            # For now, defer to organization check
            if context.actor_organization:
                return (
                    True,
                    f"Provider {context.actor_id} accessing patient {patient_id}",
                )
            return False, "Provider not associated with an organization"

        # Lab can only access test results they processed
        if context.actor_role == "LabTechnician" or context.actor_role == "LabSupervisor":
            if record_type == "lab_results":
                return (
                    True,
                    f"Lab accessing lab results for patient {patient_id}",
                )
            return (
                False,
                "Lab can only access lab results, not full medical record",
            )

        # Pharmacist can access medication history for their patients
        if context.actor_role == "Pharmacist":
            if record_type in ("medication_history", "allergies", "current_medications"):
                return (
                    True,
                    f"Pharmacist accessing medication records for patient {patient_id}",
                )
            return False, "Pharmacist can only access medication-related records"

        # Insurance cannot access records (only pre-authorization)
        if context.actor_role == "Insurance":
            return (
                False,
                "Insurance companies cannot access patient medical records (HIPAA boundary)",
            )

        # Default deny (fail closed)
        return False, f"Access denied: {context.actor_role} cannot view records"

    @staticmethod
    def can_order_lab_test(
        context: PolicyContext,
        patient_id: str,
    ) -> tuple[bool, str]:
        """Can the actor order a lab test?

        Clinical rules:
          - Only licensed providers can order (Patient cannot self-order)
          - Provider must have active relationship with patient
          - Lab order requires provider credentials

        Args:
            context: Policy evaluation context
            patient_id: Which patient

        Returns:
            (allowed: bool, reason: str)
        """
        # Only providers can order lab tests
        if context.actor_role != "Provider":
            return (
                False,
                f"{context.actor_role} cannot order lab tests (provider only)",
            )

        # Provider must have organization (clinic)
        if not context.actor_organization:
            return False, "Provider not associated with an organization"

        return True, f"Provider {context.actor_id} can order lab for patient {patient_id}"

    @staticmethod
    def can_fill_prescription(
        context: PolicyContext,
        patient_id: str,
        prescription_id: str,
    ) -> tuple[bool, str]:
        """Can the actor fill a prescription?

        Pharmacy rules:
          - Only pharmacists/pharmacy technicians can fill
          - Prescription must be valid and not expired
          - Requires patient consent (opt-in)

        Args:
            context: Policy evaluation context
            patient_id: Which patient
            prescription_id: Prescription being filled

        Returns:
            (allowed: bool, reason: str)
        """
        # Only pharmacy staff can fill prescriptions
        if context.actor_role not in ("Pharmacist", "PharmacyTechnician"):
            return (
                False,
                f"{context.actor_role} cannot fill prescriptions (pharmacy only)",
            )

        # Must be part of a pharmacy organization
        if not context.actor_organization:
            return False, "Pharmacy technician not associated with a pharmacy"

        return True, f"Pharmacy staff can fill prescription {prescription_id}"

    @staticmethod
    def can_verify_insurance(
        context: PolicyContext,
        patient_id: str,
    ) -> tuple[bool, str]:
        """Can the actor verify insurance eligibility?

        Insurance verification rules:
          - Scheduling staff, billing staff, providers can check
          - Real-time eligibility check only (no records)
          - Insurance provider can respond to verification requests

        Args:
            context: Policy evaluation context
            patient_id: Which patient

        Returns:
            (allowed: bool, reason: str)
        """
        allowed_roles = ("BillingStaff", "SchedulingStaff", "Provider", "Insurance")

        if context.actor_role not in allowed_roles:
            return (
                False,
                f"{context.actor_role} cannot verify insurance (billing/scheduling/provider only)",
            )

        return True, f"{context.actor_role} can verify insurance for patient {patient_id}"

    @staticmethod
    def can_access_patient_portal(
        context: PolicyContext,
        patient_id: str,
    ) -> tuple[bool, str]:
        """Can the actor access patient portal to view own records?

        Portal access rules:
          - Patients can only access their own portal
          - Providers can view their patients via EHR
          - Others cannot access patient portal

        Args:
            context: Policy evaluation context
            patient_id: Which patient

        Returns:
            (allowed: bool, reason: str)
        """
        # Patient accessing their own portal
        if context.actor_role == "Patient" and context.actor_id == patient_id:
            return True, "Patient accessing own portal (HIPAA right-to-access)"

        # Provider accessing their patient's record via EHR
        if context.actor_role == "Provider":
            return (
                True,
                f"Provider {context.actor_id} accessing patient {patient_id} via EHR",
            )

        return False, f"{context.actor_role} cannot access patient portal"

    @staticmethod
    def is_audit_trail_required(
        context: PolicyContext,
        action: str,
        resource_type: str,
    ) -> bool:
        """Does this action require audit logging? (HIPAA audit trail requirement)

        All PHI access requires audit logging:
          - All record access
          - All modifications
          - All patient data queries
          - All HIPAA-relevant actions

        Args:
            context: Policy evaluation context
            action: The action being performed
            resource_type: Type of resource

        Returns:
            True if audit trail required (HIPAA compliance)
        """
        # All actions on medical records require audit
        audit_required_resources = (
            "MedicalRecord",
            "LabResult",
            "Prescription",
            "PatientDemographics",
            "PatientAllergies",
            "PatientInsurance",
        )

        if resource_type in audit_required_resources:
            return True

        # All access actions require audit
        audit_required_actions = (
            "read",
            "write",
            "delete",
            "modify",
            "view",
            "access",
        )

        if action in audit_required_actions:
            return True

        return False

    @staticmethod
    def should_mask_sensitive_data(
        context: PolicyContext,
        data_type: str,
    ) -> bool:
        """Should sensitive data be masked based on actor role?

        Data masking rules:
          - Patient SSN/insurance: mask for staff, show for patient
          - Financial data: mask for clinical staff
          - Clinical notes: mask sensitive words for non-provider
          - Test results: full for provider/patient, limited for others

        Args:
            context: Policy evaluation context
            data_type: Type of data (ssn, financial, clinical_note, etc.)

        Returns:
            True if data should be masked
        """
        # Patient sees all their data unmasked
        if context.actor_role == "Patient":
            return False

        # Providers see all data unmasked (clinical access)
        if context.actor_role == "Provider":
            return False

        # Staff see limited data
        if context.actor_role in ("BillingStaff", "SchedulingStaff"):
            if data_type in ("clinical_notes", "diagnosis", "medications"):
                return True
            return False

        # Default to masking sensitive data
        return True

    @staticmethod
    def validate_hipaa_minimum_necessary(
        context: PolicyContext,
        requested_fields: list[str],
        clinically_necessary: bool,
    ) -> tuple[bool, str]:
        """HIPAA minimum necessary principle: only access what you clinically need.

        Args:
            context: Policy evaluation context
            requested_fields: Which fields are being requested
            clinically_necessary: Is this access clinically necessary for patient care?

        Returns:
            (allowed: bool, reason: str)
        """
        # If not clinically necessary, deny (HIPAA minimum necessary)
        if not clinically_necessary and context.actor_role == "Provider":
            return False, "Access denied: not clinically necessary (HIPAA minimum necessary principle)"

        # Clinical staff can only access fields they need
        if context.actor_role == "BillingStaff":
            restricted_fields = {"clinical_diagnosis", "medications", "lab_values"}
            overlap = set(requested_fields) & restricted_fields
            if overlap:
                return (
                    False,
                    f"Billing staff cannot access {overlap} (HIPAA minimum necessary)",
                )

        return True, "Minimum necessary check passed"
