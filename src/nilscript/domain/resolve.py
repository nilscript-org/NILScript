"""Domain resolution (Wave 4 §14.3) — the two lookups the compiler performs when it lowers a BizSpec/
cycle written against a Domain: alias → capability@major (D2), and capability → backend (D8). Pure
functions over a `Domain`; the compiler calls them and FAILS the compile if either returns None (a
cycle cannot reach a capability its Domain didn't import, nor run a capability with no bound backend)."""

from __future__ import annotations

from nilscript.domain.models import CapabilityImport, Domain


def resolve_alias(domain: Domain, alias: str) -> CapabilityImport | None:
    """The imported capability an alias refers to inside the Domain, or None if the alias is unknown
    (→ the compiler refuses: an unresolved alias is an ungoverned reach outside the Domain's imports)."""
    for imp in domain.imports:
        if imp.alias == alias:
            return imp
    return None


def resolve_backend(domain: Domain, capability: str) -> str | None:
    """The governed backend a capability is bound to in this Domain (D8), or None if unbound. The
    compiler refuses an unbound capability rather than routing implicitly — no newest-declarer-wins."""
    for binding in domain.bindings:
        if binding.capability == capability:
            return binding.backend
    return None
