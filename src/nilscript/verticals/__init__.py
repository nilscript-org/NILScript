"""Verticals Package (Wave 4 Architecture § Second Vertical Initiative).

Demonstrates Kernel's vertical-agnostic architecture. Each vertical uses:
  - 100% shared Kernel (execution, compilation, correlation, authority)
  - 100% shared Comms layer (email, WhatsApp, SMS, channels)
  - Vertical-specific: Capabilities, Cycles, Policies, Authority Rules

Available verticals:
  - healthcare: Patient management, lab orders, prescriptions, insurance verification
  - [future] finance: Invoicing, payments, reconciliation
  - [future] supply_chain: Procurement, inventory, fulfillment
  - [future] sales: CRM, leads, quotations, opportunities

Each vertical is independent and demonstrates the Kernel scales across domains.
"""

from __future__ import annotations

__all__ = []
