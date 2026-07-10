"""Healthcare Vertical (Wave 4 Architecture Proof § Second Vertical Initiative).

Demonstrates that the Kernel and shared Comms layer scale across verticals
WITHOUT modification. Healthcare is a complete vertical-specific implementation:
  - Shared: Kernel (execution, compilation, correlation, authority)
  - Shared: Comms (email, WhatsApp, SMS, channels)
  - Vertical-specific: Capabilities, Cycles, Policies, Authority Rules

Key components:
  1. Domain (healthcare/domain.py): Imports + backend bindings
  2. Capabilities (healthcare/capabilities.py): 5 core healthcare capabilities
  3. Cycles (healthcare/cycles.py): 3 key business processes
  4. Policies (healthcare/policies.py): HIPAA + clinical access control

No Kernel changes needed — vertical uses 100% shared infrastructure.
"""

from __future__ import annotations

from nilscript.verticals.healthcare.capabilities import (
    insurance_verify_coverage,
    lab_order_test,
    patient_access_records,
    patient_schedule_appointment,
    pharmacy_fill_prescription,
)
from nilscript.verticals.healthcare.cycles import (
    lab_order_cycle,
    patient_intake_cycle,
    prescription_cycle,
)
from nilscript.verticals.healthcare.domain import create_healthcare_domain
from nilscript.verticals.healthcare.policies import (
    HealthcarePolicy,
    PolicyContext,
)

__all__ = [
    # Domain
    "create_healthcare_domain",
    # Capabilities (5 core)
    "patient_schedule_appointment",
    "lab_order_test",
    "pharmacy_fill_prescription",
    "patient_access_records",
    "insurance_verify_coverage",
    # Cycles (3 key processes)
    "patient_intake_cycle",
    "lab_order_cycle",
    "prescription_cycle",
    # Policies & Authority
    "HealthcarePolicy",
    "PolicyContext",
]
