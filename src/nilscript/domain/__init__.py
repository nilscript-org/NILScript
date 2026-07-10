"""The Domain layer (Wave 4 §14.3) — a curated business area that IMPORTS capabilities by alias and
BINDS their backends. The DI + permission boundary (Encaps D2) and the governed multi-ERP routing
decision (D8). A Cycle declares its Domain (`cycle X in Procurement`) and every capability reference
resolves THROUGH the Domain's imports — a cycle cannot reach a capability its Domain didn't import.
"""

from __future__ import annotations

from nilscript.domain.models import BackendBinding, CapabilityImport, Domain
from nilscript.domain.resolve import resolve_alias, resolve_backend

__all__ = [
    "Domain",
    "CapabilityImport",
    "BackendBinding",
    "resolve_alias",
    "resolve_backend",
]
