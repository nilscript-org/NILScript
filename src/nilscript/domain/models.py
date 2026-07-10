"""The Domain AST v0.1 (Wave 4 §14.3 / Encaps D2·D8).

A Domain is DATA, never code — the same discipline as `capability/models.py` and `cycle/models.py`:
frozen pydantic, `extra="forbid"`, every authoring surface (`.domain.nil`, the hub editor) a projection
of this one object. A Domain does two governed things:

  1. IMPORTS capabilities by ALIAS at a pinned MAJOR (D2) — a reference into the global registry, never
     a copy. `import Communication@2 as comms`. This is the permission boundary: a Cycle in this Domain
     can only reach the capabilities the Domain imported.
  2. BINDS a backend per capability (D8) — the explicit, governed multi-ERP routing decision. No implicit
     "newest declarer wins" (the current os-server RoutingNilClient behaviour). `bind Crm to odoo`. The
     Permission Card shows the real target system.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from nilscript.capability.models import CAPABILITY_ID_PATTERN, IDENT_PATTERN
from nilscript.kernel.models import DslModel


class CapabilityImport(DslModel):
    """A Domain imports a Capability by alias at a PINNED major (Risk 8: `latest` is unrepresentable —
    `major` is an int, so there is no 'newest' to drift). Import ≠ copy: the canonical capability stays
    in the registry; the Domain holds a reference + a local name."""

    capability: str = Field(pattern=CAPABILITY_ID_PATTERN)  # the registry id, e.g. "Communication"
    major: int = Field(ge=0)  # pinned major version — `import Communication@2`
    alias: str = Field(pattern=IDENT_PATTERN)  # local name used inside the Domain's cycles, e.g. "comms"


class BackendBinding(DslModel):
    """D8: the governed backend a Capability resolves to WITHIN this Domain (Procurement.Crm → odoo,
    Finance.Crm → sap). Explicit and Card-visible — never the implicit newest-declarer-wins routing."""

    capability: str = Field(pattern=CAPABILITY_ID_PATTERN)
    backend: str = Field(pattern=IDENT_PATTERN)  # adapter/system name, e.g. "odoo" | "sap"


class Domain(DslModel):
    nil: Literal["domain/0.1"]
    domain_id: str = Field(pattern=IDENT_PATTERN)  # "Procurement"
    workspace: str = Field(min_length=1)
    imports: tuple[CapabilityImport, ...] = ()
    bindings: tuple[BackendBinding, ...] = ()

    @model_validator(mode="after")
    def _imports_and_bindings_are_well_formed(self) -> Domain:
        """A Domain's imports name each alias once, and every binding targets an imported capability with
        at most one backend — an ambiguous alias or an unbound/double-bound capability is unrepresentable
        (the whole point of D2/D8: no silent shadowing, no silent routing)."""
        aliases = [i.alias for i in self.imports]
        dupe_aliases = sorted({a for a in aliases if aliases.count(a) > 1})
        if dupe_aliases:
            raise ValueError(f"duplicate import aliases: {dupe_aliases}")

        imported = {i.capability for i in self.imports}
        imported_dupes = sorted({i.capability for i in self.imports if
                                 [x.capability for x in self.imports].count(i.capability) > 1})
        if imported_dupes:
            raise ValueError(f"capability imported more than once: {imported_dupes}")

        bound = [b.capability for b in self.bindings]
        unbound = sorted({c for c in bound if c not in imported})
        if unbound:
            raise ValueError(f"binding for a non-imported capability: {unbound}")
        double_bound = sorted({c for c in bound if bound.count(c) > 1})
        if double_bound:
            raise ValueError(f"capability bound to more than one backend: {double_bound}")
        return self
