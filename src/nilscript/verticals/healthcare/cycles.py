"""Healthcare Vertical Cycles (Wave 4 § Second Vertical Initiative).

Three key healthcare business processes demonstrating vertical-agnostic Kernel:
  1. PatientIntake: referral → verify identity → insurance check → intake form → checkin
  2. LabOrder: order → collect sample → process → verify → deliver result
  3. Prescription: prescribe → patient opt-in → pharmacy send → track → confirm

Each cycle is DATA (frozen pydantic Cycle model), declares:
  - Trigger (event-based or manual)
  - Context (entities: Patient, Provider, Lab, Pharmacy)
  - Flow (steps: action, decision, approval, wait_for_event, checkpoint)
  - Governance (policies, roles, outcomes)
  - Binding: implemented_by → capability mapping
"""

from __future__ import annotations

from nilscript.cycle.models import Cycle


def patient_intake_cycle() -> Cycle:
    """PatientIntake Cycle: referral → identity → insurance → intake → checkin.

    Trigger: Event-based (referral received)
    Outcomes: admitted (patient checked in), rejected (insurance denied)
    Governance: MEDIUM tier (scheduling + verification)
    """
    return Cycle.model_validate(
        {
            "nil": "cycle/0.3",
            "cycle_id": "PatientIntake",
            "implements": {
                "capability_id": "patient-schedule-appointment",
                "version": "1.0.0",
            },
            "workspace": "healthcare",
            "metadata": {
                "version": "1.0.0",
                "owner": "Clinical Operations",
                "description": {
                    "en": "Patient intake workflow: referral verification, insurance eligibility, scheduling",
                    "ar": "سير عمل استقبال المريض: التحقق من الإحالة والتأمين والجدولة",
                },
                "tags": ("patient", "intake", "scheduling", "insurance", "clinical"),
            },
            "intent": {
                "en": "Complete patient intake: verify identity, check insurance, schedule appointment",
                "ar": "استكمال استقبال المريض: التحقق من الهوية والتأمين وجدولة الموعد",
            },
            "trigger": {"type": "event", "on_verb": "patient.referral_received"},
            "context": [
                {"name": "patient", "entity_type": "Patient"},
                {"name": "provider", "entity_type": "Provider"},
                {"name": "intake_staff", "entity_type": "User", "role": "IntakeStaff"},
                {"name": "approver", "entity_type": "User", "role": "ClinicalDirector"},
            ],
            "variables": [
                {"name": "patient_id", "expression": "context.patient.id"},
                {"name": "insurance_member_id", "expression": "context.patient.insurance_id"},
                {"name": "requested_date", "expression": "context.payload.appointment_date"},
            ],
            "roles": [
                {"role": "IntakeStaff"},
                {"role": "ClinicalDirector"},
            ],
            "policies": [],
            "resources": (
                "patient.verify_identity",
                "insurance.verify_coverage",
                "patient.schedule_appointment",
                "comms.send_email",
            ),
            "outcomes": [
                {"name": "admitted", "when": "insurance_eligible == true"},
                {"name": "rejected", "when": "insurance_eligible == false"},
                {"name": "pending", "when": "true"},
            ],
            "flow": {
                "entry": "VerifyIdentity",
                "steps": [
                    {
                        "id": "VerifyIdentity",
                        "type": "action",
                        "use": "patient.verify_identity",
                        "with": {
                            "patient_id": "$patient_id",
                            "mrn": "context.payload.mrn",
                        },
                        "output": "identity_result",
                        "next": "CheckInsurance",
                    },
                    {
                        "id": "CheckInsurance",
                        "type": "action",
                        "use": "insurance.verify_coverage",
                        "with": {
                            "patient_id": "$patient_id",
                            "insurance_member_id": "$insurance_member_id",
                        },
                        "output": "coverage_result",
                        "next": "EligibilityDecision",
                    },
                    {
                        "id": "EligibilityDecision",
                        "type": "decision",
                        "when": "coverage_result.eligible == true",
                        "on_true": "ScheduleAppointment",
                        "on_false": "NotifyInsuranceDenial",
                    },
                    {
                        "id": "ScheduleAppointment",
                        "type": "action",
                        "use": "patient.schedule_appointment",
                        "with": {
                            "patient_id": "$patient_id",
                            "provider_id": "context.provider.id",
                            "appointment_time": "$requested_date",
                            "appointment_type": "initial_consultation",
                        },
                        "output": "appointment",
                        "next": "NotifyPatientConfirmed",
                    },
                    {
                        "id": "NotifyPatientConfirmed",
                        "type": "action",
                        "use": "comms.send_email",
                        "with": {
                            "to": "context.patient.email",
                            "subject": {
                                "en": "Appointment Confirmed",
                                "ar": "تم تأكيد الموعد",
                            },
                            "body": "Your appointment has been scheduled for $requested_date",
                        },
                        "next": "IntakeComplete",
                    },
                    {
                        "id": "IntakeComplete",
                        "type": "notify",
                        "message": {
                            "en": "Patient intake completed successfully",
                            "ar": "تم استكمال استقبال المريض بنجاح",
                        },
                    },
                    {
                        "id": "NotifyInsuranceDenial",
                        "type": "notify",
                        "message": {
                            "en": "Insurance verification failed - patient not eligible",
                            "ar": "فشل التحقق من التأمين - المريض غير مؤهل",
                        },
                    },
                ],
            },
        }
    )


def lab_order_cycle() -> Cycle:
    """LabOrder Cycle: order → collect → process → verify → deliver result.

    Trigger: Event-based (provider orders lab)
    Governance: HIGH tier (clinical decision + sample handling + HIPAA)
    Wait-for-event: Sample collection, results ready
    Outcomes: completed (results delivered), failed (sample rejected)
    """
    return Cycle.model_validate(
        {
            "nil": "cycle/0.3",
            "cycle_id": "LabOrder",
            "implements": {
                "capability_id": "lab-order-test",
                "version": "1.0.0",
            },
            "workspace": "healthcare",
            "metadata": {
                "version": "1.0.0",
                "owner": "Laboratory Services",
                "description": {
                    "en": "Lab order workflow: sample collection, processing, verification, result delivery",
                    "ar": "سير عمل طلب المعمل: جمع العينة والمعالجة والتحقق والتسليم",
                },
                "tags": ("lab", "diagnostic", "testing", "results", "sample-handling"),
            },
            "intent": {
                "en": "Process lab test order: from provider order to patient result delivery",
                "ar": "معالجة طلب الاختبار: من طلب المزود إلى تسليم النتيجة للمريض",
            },
            "trigger": {"type": "event", "on_verb": "lab.test_order_received"},
            "context": [
                {"name": "patient", "entity_type": "Patient"},
                {"name": "provider", "entity_type": "Provider"},
                {"name": "lab_technician", "entity_type": "User", "role": "LabTechnician"},
                {"name": "lab_supervisor", "entity_type": "User", "role": "LabSupervisor"},
            ],
            "variables": [
                {"name": "lab_order_id", "expression": "context.payload.order_id"},
                {"name": "test_type", "expression": "context.payload.test_type"},
                {"name": "patient_id", "expression": "context.payload.patient_id"},
            ],
            "roles": [
                {"role": "LabTechnician"},
                {"role": "LabSupervisor"},
            ],
            "policies": [],
            "resources": (
                "lab.order_test",
                "lab.update_order_status",
                "patient.send_results",
                "comms.send_email",
            ),
            "outcomes": [
                {"name": "completed", "when": "results_delivered == true"},
                {"name": "failed", "when": "sample_rejected == true"},
                {"name": "processing", "when": "true"},
            ],
            "flow": {
                "entry": "CreateLabOrder",
                "steps": [
                    {
                        "id": "CreateLabOrder",
                        "type": "action",
                        "use": "lab.order_test",
                        "with": {
                            "patient_id": "$patient_id",
                            "test_type": "$test_type",
                            "provider_id": "context.provider.id",
                        },
                        "output": "lab_order",
                        "next": "WaitSampleCollection",
                    },
                    {
                        "id": "WaitSampleCollection",
                        "type": "wait_for_event",
                        "on_event": "lab.sample_collected",
                        "match": {"lab_order_id": "$lab_order_id"},
                        "timeout_seconds": 172800,
                        "on_timeout": "SampleCollectionTimeout",
                        "output": "collection_result",
                        "next": "UpdateOrderStatus",
                    },
                    {
                        "id": "UpdateOrderStatus",
                        "type": "action",
                        "use": "lab.update_order_status",
                        "with": {
                            "lab_order_id": "$lab_order_id",
                            "status": "processing",
                        },
                        "next": "WaitResultsReady",
                    },
                    {
                        "id": "WaitResultsReady",
                        "type": "wait_for_event",
                        "on_event": "lab.results_ready",
                        "match": {"lab_order_id": "$lab_order_id"},
                        "timeout_seconds": 432000,
                        "on_timeout": "ResultsTimeout",
                        "output": "results",
                        "next": "VerifyResults",
                    },
                    {
                        "id": "VerifyResults",
                        "type": "approval",
                        "title": {
                            "en": "Verify Lab Results",
                            "ar": "التحقق من نتائج المعمل",
                        },
                        "description": {
                            "en": "Review and verify lab results before delivery to patient",
                            "ar": "مراجعة والتحقق من النتائج قبل التسليم للمريض",
                        },
                        "approver": "lab_supervisor",
                        "timeout_seconds": 86400,
                        "on_approve": "DeliverResults",
                        "on_reject": "ReturnForRework",
                    },
                    {
                        "id": "DeliverResults",
                        "type": "action",
                        "use": "patient.send_results",
                        "with": {
                            "patient_id": "$patient_id",
                            "lab_order_id": "$lab_order_id",
                            "results": "results",
                        },
                        "next": "NotifyPatientResults",
                    },
                    {
                        "id": "NotifyPatientResults",
                        "type": "action",
                        "use": "comms.send_email",
                        "with": {
                            "to": "context.patient.email",
                            "subject": {
                                "en": "Lab Results Available",
                                "ar": "النتائج جاهزة",
                            },
                            "body": "Your lab test results are now available in your patient portal",
                        },
                        "next": "LabOrderComplete",
                    },
                    {
                        "id": "LabOrderComplete",
                        "type": "notify",
                        "message": {
                            "en": "Lab order completed and results delivered",
                            "ar": "تم إكمال الطلب وتسليم النتائج",
                        },
                    },
                    {
                        "id": "SampleCollectionTimeout",
                        "type": "notify",
                        "message": {
                            "en": "Sample collection timeout - order cancelled",
                            "ar": "انتهاء وقت جمع العينة - تم إلغاء الطلب",
                        },
                    },
                    {
                        "id": "ResultsTimeout",
                        "type": "notify",
                        "message": {
                            "en": "Results processing timeout - contacting lab",
                            "ar": "انتهاء وقت المعالجة - يتم الاتصال بالمعمل",
                        },
                    },
                    {
                        "id": "ReturnForRework",
                        "type": "notify",
                        "message": {
                            "en": "Results rejected - returning for rework",
                            "ar": "تم رفض النتائج - إعادة العمل",
                        },
                    },
                ],
            },
        }
    )


def prescription_cycle() -> Cycle:
    """Prescription Cycle: prescribe → patient opt-in → pharmacy → track → confirm.

    Trigger: Event-based (provider issues prescription)
    Governance: MEDIUM tier (patient consent required)
    Wait-for-event: Patient opt-in, pharmacy ready, delivery confirmation
    Outcomes: fulfilled (delivered), abandoned (patient declined)
    """
    return Cycle.model_validate(
        {
            "nil": "cycle/0.3",
            "cycle_id": "Prescription",
            "implements": {
                "capability_id": "pharmacy-fill-prescription",
                "version": "1.0.0",
            },
            "workspace": "healthcare",
            "metadata": {
                "version": "1.0.0",
                "owner": "Pharmacy Services",
                "description": {
                    "en": "Prescription workflow: patient opt-in, pharmacy fulfillment, delivery tracking",
                    "ar": "سير عمل الوصفة: موافقة المريض والوفاء من الصيدلية والتتبع",
                },
                "tags": (
                    "prescription",
                    "medication",
                    "pharmacy",
                    "patient-consent",
                    "fulfillment",
                ),
            },
            "intent": {
                "en": "Process prescription: patient approval, pharmacy fulfillment, delivery",
                "ar": "معالجة الوصفة: موافقة المريض والوفاء والتسليم",
            },
            "trigger": {"type": "event", "on_verb": "prescription.issued"},
            "context": [
                {"name": "patient", "entity_type": "Patient"},
                {"name": "provider", "entity_type": "Provider"},
                {"name": "pharmacist", "entity_type": "User", "role": "Pharmacist"},
            ],
            "variables": [
                {"name": "prescription_id", "expression": "context.payload.prescription_id"},
                {"name": "patient_id", "expression": "context.payload.patient_id"},
                {"name": "medication", "expression": "context.payload.medication"},
            ],
            "roles": [
                {"role": "Pharmacist"},
            ],
            "policies": [],
            "resources": (
                "pharmacy.fill_prescription",
                "comms.send_email",
                "comms.send_sms",
            ),
            "outcomes": [
                {"name": "fulfilled", "when": "delivery_confirmed == true"},
                {"name": "abandoned", "when": "patient_declined == true"},
                {"name": "pending", "when": "true"},
            ],
            "flow": {
                "entry": "NotifyPatientPrescription",
                "steps": [
                    {
                        "id": "NotifyPatientPrescription",
                        "type": "action",
                        "use": "comms.send_email",
                        "with": {
                            "to": "context.patient.email",
                            "subject": {"en": "New Prescription", "ar": "وصفة جديدة"},
                            "body": "A new prescription is ready: $medication. Please approve to proceed with fulfillment.",
                        },
                        "next": "WaitPatientOptIn",
                    },
                    {
                        "id": "WaitPatientOptIn",
                        "type": "wait_for_event",
                        "on_event": "prescription.patient_opt_in",
                        "match": {"prescription_id": "$prescription_id"},
                        "timeout_seconds": 604800,
                        "on_timeout": "PatientOptInTimeout",
                        "output": "patient_decision",
                        "next": "FillPrescription",
                    },
                    {
                        "id": "FillPrescription",
                        "type": "action",
                        "use": "pharmacy.fill_prescription",
                        "with": {
                            "prescription_id": "$prescription_id",
                            "patient_id": "$patient_id",
                        },
                        "output": "fulfillment",
                        "next": "NotifyPatientReady",
                    },
                    {
                        "id": "NotifyPatientReady",
                        "type": "action",
                        "use": "comms.send_sms",
                        "with": {
                            "to": "context.patient.phone",
                            "message": "Your prescription is ready for pickup at the pharmacy",
                        },
                        "next": "WaitPickupConfirmation",
                    },
                    {
                        "id": "WaitPickupConfirmation",
                        "type": "wait_for_event",
                        "on_event": "prescription.picked_up",
                        "match": {"prescription_id": "$prescription_id"},
                        "timeout_seconds": 2592000,
                        "on_timeout": "PickupTimeout",
                        "output": "pickup_confirmation",
                        "next": "PrescriptionFulfilled",
                    },
                    {
                        "id": "PrescriptionFulfilled",
                        "type": "notify",
                        "message": {
                            "en": "Prescription fulfilled and picked up",
                            "ar": "تم تعبئة الوصفة والتقاطها",
                        },
                    },
                    {
                        "id": "PatientOptInTimeout",
                        "type": "notify",
                        "message": {
                            "en": "Patient opt-in timeout - prescription cancelled",
                            "ar": "انتهاء وقت موافقة المريض - تم إلغاء الوصفة",
                        },
                    },
                    {
                        "id": "PickupTimeout",
                        "type": "notify",
                        "message": {
                            "en": "Prescription pickup timeout - may need to be re-filled",
                            "ar": "انتهاء وقت الاستلام - قد تحتاج إلى إعادة التعبئة",
                        },
                    },
                ],
            },
        }
    )
