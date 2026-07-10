"""Healthcare Vertical Capabilities (Wave 4 § Second Vertical Initiative).

Five core healthcare capabilities demonstrating vertical-agnostic Kernel:
  1. patient.schedule_appointment — MEDIUM risk, provider-initiated
  2. lab.order_test — HIGH risk, requires provider approval
  3. pharmacy.fill_prescription — MEDIUM risk, patient opt-in
  4. patient.access_records — CRITICAL, HIPAA audit trail required
  5. insurance.verify_coverage — MEDIUM risk, real-time eligibility

Each capability is DATA (frozen pydantic model), declares:
  - Inputs/outputs (patient_id, MRN, appointment_time, etc.)
  - Risk tier (MEDIUM/HIGH/CRITICAL)
  - Governance strategy (approval gates, SoD)
  - Binding (epic_fhir, quest_diagnostics, etc.)
  - Skills (semantic operations: schedule, order, fill, verify)
"""

from __future__ import annotations

from nilscript.capability.models import (
    Capability,
    CapabilityField,
    Exposure,
    FieldType,
    GovernanceEnvelope,
    Skill,
    Sod,
)


def patient_schedule_appointment() -> Capability:
    """Schedule an appointment for a patient with a provider.

    Risk: MEDIUM (scheduling affects availability, HIPAA applies)
    Approval: Provider confirms patient eligibility
    Binding: epic_fhir (Epic EHR system)
    """
    return Capability(
        nil="capability/0.1",
        capability_id="patient-schedule-appointment",
        workspace="healthcare",
        version="1.0.0",
        domain="Healthcare",
        owner_role="Provider",
        intent={
            "en": "Schedule a patient appointment with a healthcare provider",
            "ar": "جدولة موعد المريض مع مقدم الرعاية الصحية",
        },
        aliases=("book appointment", "schedule visit", "set appointment time"),
        examples=(
            "Schedule John Doe for cardiology on 2026-08-01 at 10:00",
            "Book follow-up appointment after lab results",
        ),
        inputs=(
            CapabilityField(
                name="patient_id",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
            CapabilityField(
                name="provider_id",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
            CapabilityField(
                name="appointment_time",
                type=FieldType(kind="scalar", of="DateTime"),
                required=True,
            ),
            CapabilityField(
                name="appointment_type",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
            CapabilityField(
                name="reason",
                type=FieldType(kind="scalar", of="String"),
                required=False,
            ),
        ),
        outputs=(
            CapabilityField(
                name="appointment_id",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
            CapabilityField(
                name="confirmation_token",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
        ),
        risk="MEDIUM",
        strategy="standard_approval",
        requires=("PatientVerified", "ProviderActive"),
        enables=("PatientReceiveAppointmentReminder",),
        exposure=Exposure(ai=False, roles=("Provider", "Nurse", "Scheduler")),
        skills=(
            Skill(
                name="schedule",
                intent={
                    "en": "Schedule an appointment slot",
                    "ar": "جدولة فتحة موعد",
                },
                inputs=(
                    CapabilityField(
                        name="patient_id",
                        type=FieldType(kind="scalar", of="String"),
                        required=True,
                    ),
                    CapabilityField(
                        name="slot_time",
                        type=FieldType(kind="scalar", of="DateTime"),
                        required=True,
                    ),
                ),
                outputs=(
                    CapabilityField(
                        name="appointment_id",
                        type=FieldType(kind="scalar", of="String"),
                        required=True,
                    ),
                ),
                resolves_to=("patient.schedule_appointment",),
                envelope=GovernanceEnvelope(
                    tier="MEDIUM",
                    reversibility="COMPENSABLE",
                    effects=("patient.schedule_appointment",),
                ),
            ),
        ),
        implemented_by={"default": "PatientIntake"},
    )


def lab_order_test() -> Capability:
    """Order a laboratory test for a patient.

    Risk: HIGH (clinical decision, requires provider order, HIPAA critical)
    Approval: Labs must verify provider credentials and authorization
    Binding: quest_diagnostics (Quest Diagnostics lab system)
    """
    return Capability(
        nil="capability/0.1",
        capability_id="lab-order-test",
        workspace="healthcare",
        version="1.0.0",
        domain="Healthcare",
        owner_role="Provider",
        intent={
            "en": "Order a laboratory test for a patient",
            "ar": "طلب اختبار معملي للمريض",
        },
        aliases=("request lab test", "order blood work", "order imaging"),
        examples=(
            "Order complete blood count (CBC) for patient",
            "Request lipid panel as part of routine checkup",
            "Order X-ray imaging for chest pain evaluation",
        ),
        inputs=(
            CapabilityField(
                name="patient_id",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
            CapabilityField(
                name="provider_id",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
            CapabilityField(
                name="test_type",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
            CapabilityField(
                name="clinical_indication",
                type=FieldType(kind="scalar", of="String"),
                required=False,
            ),
        ),
        outputs=(
            CapabilityField(
                name="lab_order_id",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
            CapabilityField(
                name="sample_kit_tracking",
                type=FieldType(kind="scalar", of="String"),
                required=False,
            ),
        ),
        risk="HIGH",
        strategy="provider_approval",
        requires=("PatientVerified", "ProviderLicensed"),
        creates=("LabOrder",),
        enables=("LabCollectSample", "LabProcessResults"),
        exposure=Exposure(ai=False, roles=("Provider", "ProviderAdmin")),
        sod=Sod(preparer_not_approver=True),
        skills=(
            Skill(
                name="order",
                intent={
                    "en": "Place a lab order",
                    "ar": "تقديم طلب معملي",
                },
                inputs=(
                    CapabilityField(
                        name="patient_id",
                        type=FieldType(kind="scalar", of="String"),
                        required=True,
                    ),
                    CapabilityField(
                        name="test_type",
                        type=FieldType(kind="scalar", of="String"),
                        required=True,
                    ),
                ),
                outputs=(
                    CapabilityField(
                        name="lab_order_id",
                        type=FieldType(kind="scalar", of="String"),
                        required=True,
                    ),
                ),
                resolves_to=("lab.order_test",),
                envelope=GovernanceEnvelope(
                    tier="HIGH",
                    reversibility="IRREVERSIBLE",
                    effects=("lab.order_test",),
                ),
            ),
        ),
        implemented_by={"default": "LabOrder"},
    )


def pharmacy_fill_prescription() -> Capability:
    """Fill a prescription at a pharmacy.

    Risk: MEDIUM (patient opt-in, pharmacy fulfillment)
    Approval: Patient must opt-in after prescription verified
    Binding: pharmacy_24 (Pharmacy fulfillment system)
    """
    return Capability(
        nil="capability/0.1",
        capability_id="pharmacy-fill-prescription",
        workspace="healthcare",
        version="1.0.0",
        domain="Healthcare",
        owner_role="Pharmacist",
        intent={
            "en": "Fill a patient prescription at a pharmacy",
            "ar": "ملء وصفة المريض في الصيدلية",
        },
        aliases=("dispense medication", "fulfill prescription", "prepare medication"),
        examples=(
            "Fill antibiotic prescription for patient infection treatment",
            "Dispense chronic maintenance medication",
        ),
        inputs=(
            CapabilityField(
                name="prescription_id",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
            CapabilityField(
                name="patient_id",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
            CapabilityField(
                name="pharmacy_id",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
        ),
        outputs=(
            CapabilityField(
                name="fulfillment_id",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
            CapabilityField(
                name="tracking_code",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
            CapabilityField(
                name="pickup_ready_time",
                type=FieldType(kind="scalar", of="DateTime"),
                required=False,
            ),
        ),
        risk="MEDIUM",
        strategy="patient_opt_in",
        requires=("PrescriptionValid", "PatientVerified"),
        enables=("PharmacyTrackDelivery", "PatientPickupConfirmation"),
        exposure=Exposure(ai=False, roles=("Pharmacist", "PharmacyTechnician")),
        skills=(
            Skill(
                name="fill",
                intent={
                    "en": "Fill prescription",
                    "ar": "ملء الوصفة",
                },
                inputs=(
                    CapabilityField(
                        name="prescription_id",
                        type=FieldType(kind="scalar", of="String"),
                        required=True,
                    ),
                ),
                outputs=(
                    CapabilityField(
                        name="fulfillment_id",
                        type=FieldType(kind="scalar", of="String"),
                        required=True,
                    ),
                ),
                resolves_to=("pharmacy.fill_prescription",),
                envelope=GovernanceEnvelope(
                    tier="MEDIUM",
                    reversibility="COMPENSABLE",
                    effects=("pharmacy.fill_prescription",),
                ),
            ),
        ),
        implemented_by={"default": "Prescription"},
    )


def patient_access_records() -> Capability:
    """Patient accesses their own medical records (HIPAA right-to-access).

    Risk: CRITICAL (PHI exposure, HIPAA audit trail required)
    Approval: None (patient right), but all access logged
    Binding: epic_fhir (Epic EHR patient portal)
    """
    return Capability(
        nil="capability/0.1",
        capability_id="patient-access-records",
        workspace="healthcare",
        version="1.0.0",
        domain="Healthcare",
        owner_role="Patient",
        intent={
            "en": "Patient accesses their own medical records",
            "ar": "وصول المريض إلى سجلاته الطبية",
        },
        aliases=("view medical history", "access patient portal", "download records"),
        examples=(
            "Patient views recent appointments and results",
            "Download lab report for insurance submission",
        ),
        inputs=(
            CapabilityField(
                name="patient_id",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
            CapabilityField(
                name="record_type",
                type=FieldType(kind="scalar", of="String"),
                required=False,
            ),
        ),
        outputs=(
            CapabilityField(
                name="records",
                type=FieldType(kind="list", of="MedicalRecord"),
                required=True,
            ),
            CapabilityField(
                name="audit_id",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
        ),
        risk="CRITICAL",
        strategy="hipaa_audit",
        requires=("PatientVerified", "PatientConsented"),
        exposure=Exposure(ai=False, roles=("Patient",)),
        metrics={"sla": "P0D"},  # Real-time access required
        skills=(
            Skill(
                name="access",
                intent={
                    "en": "Access patient records",
                    "ar": "الوصول إلى سجلات المريض",
                },
                inputs=(
                    CapabilityField(
                        name="patient_id",
                        type=FieldType(kind="scalar", of="String"),
                        required=True,
                    ),
                ),
                outputs=(
                    CapabilityField(
                        name="records",
                        type=FieldType(kind="list", of="MedicalRecord"),
                        required=True,
                    ),
                ),
                resolves_to=("patient.access_records",),
                envelope=GovernanceEnvelope(
                    tier="CRITICAL",
                    reversibility="IRREVERSIBLE",
                    effects=("patient.access_records", "audit.log_access"),
                ),
            ),
        ),
        implemented_by={"default": "PatientRecordAccess"},
    )


def insurance_verify_coverage() -> Capability:
    """Verify patient insurance coverage and eligibility in real-time.

    Risk: MEDIUM (financial data, requires real-time accuracy)
    Approval: None (automated real-time check)
    Binding: insurance_api (Insurance payer verification service)
    """
    return Capability(
        nil="capability/0.1",
        capability_id="insurance-verify-coverage",
        workspace="healthcare",
        version="1.0.0",
        domain="Healthcare",
        owner_role="BillingAdministrator",
        intent={
            "en": "Verify patient insurance coverage and eligibility",
            "ar": "التحقق من تغطية التأمين وأهلية المريض",
        },
        aliases=("check eligibility", "verify insurance", "validate coverage"),
        examples=(
            "Verify insurance coverage before scheduling appointment",
            "Check patient deductible and copay for visit",
            "Confirm authorization requirements for procedure",
        ),
        inputs=(
            CapabilityField(
                name="patient_id",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
            CapabilityField(
                name="insurance_member_id",
                type=FieldType(kind="scalar", of="String"),
                required=True,
            ),
            CapabilityField(
                name="service_code",
                type=FieldType(kind="scalar", of="String"),
                required=False,
            ),
        ),
        outputs=(
            CapabilityField(
                name="eligible",
                type=FieldType(kind="scalar", of="Boolean"),
                required=True,
            ),
            CapabilityField(
                name="coverage_details",
                type=FieldType(kind="entity", of="CoverageInfo"),
                required=True,
            ),
            CapabilityField(
                name="verification_timestamp",
                type=FieldType(kind="scalar", of="DateTime"),
                required=True,
            ),
        ),
        risk="MEDIUM",
        strategy="real_time_verification",
        requires=("PatientVerified",),
        exposure=Exposure(ai=False, roles=("BillingStaff", "SchedulingStaff")),
        metrics={"sla": "PT5S"},  # 5 second SLA for real-time
        skills=(
            Skill(
                name="verify",
                intent={
                    "en": "Verify insurance coverage",
                    "ar": "التحقق من التأمين",
                },
                inputs=(
                    CapabilityField(
                        name="patient_id",
                        type=FieldType(kind="scalar", of="String"),
                        required=True,
                    ),
                    CapabilityField(
                        name="insurance_member_id",
                        type=FieldType(kind="scalar", of="String"),
                        required=True,
                    ),
                ),
                outputs=(
                    CapabilityField(
                        name="eligible",
                        type=FieldType(kind="scalar", of="Boolean"),
                        required=True,
                    ),
                ),
                resolves_to=("insurance.verify_coverage",),
                envelope=GovernanceEnvelope(
                    tier="MEDIUM",
                    reversibility="REVERSIBLE",
                    effects=("insurance.verify_coverage",),
                ),
            ),
        ),
        implemented_by={"default": "InsuranceVerification"},
    )
