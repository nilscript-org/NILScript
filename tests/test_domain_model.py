"""The Domain layer (Wave 4 §14.3): curated capability imports by alias (D2) + governed backend
bindings (D8). The model makes an ambiguous alias / unbound / double-bound capability unrepresentable,
and the resolver is the exact lookup the compiler performs (fails the compile when either returns None).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nilscript.domain import (
    BackendBinding,
    CapabilityImport,
    Domain,
    resolve_alias,
    resolve_backend,
)


def _domain(imports=(), bindings=(), *, workspace="acme", domain_id="Procurement") -> Domain:
    return Domain(
        nil="domain/0.1", domain_id=domain_id, workspace=workspace,
        imports=tuple(imports), bindings=tuple(bindings),
    )


def _imp(cap, major=2, alias=None) -> CapabilityImport:
    return CapabilityImport(capability=cap, major=major, alias=alias or cap.lower())


def _bind(cap, backend) -> BackendBinding:
    return BackendBinding(capability=cap, backend=backend)


# ── Well-formed ─────────────────────────────────────────────────────────────────────────────────────
def test_domain_with_imports_and_bindings_is_valid() -> None:
    d = _domain(
        imports=[_imp("Communication", 2, "comms"), _imp("Crm", 1, "crm")],
        bindings=[_bind("Crm", "odoo")],
    )
    assert len(d.imports) == 2 and d.bindings[0].backend == "odoo"


def test_pinned_major_is_an_int_so_latest_is_unrepresentable() -> None:
    # There is no way to import `latest` — the type only accepts a concrete major.
    with pytest.raises(ValidationError):
        CapabilityImport(capability="Communication", major="latest", alias="comms")  # type: ignore[arg-type]


# ── D2: alias discipline ──────────────────────────────────────────────────────────────────────────
def test_duplicate_alias_is_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate import aliases"):
        _domain(imports=[_imp("Communication", 2, "x"), _imp("Crm", 1, "x")])


def test_same_capability_imported_twice_is_rejected() -> None:
    with pytest.raises(ValidationError, match="imported more than once"):
        _domain(imports=[_imp("Crm", 1, "crm1"), _imp("Crm", 2, "crm2")])


# ── D8: binding discipline ────────────────────────────────────────────────────────────────────────
def test_binding_for_a_non_imported_capability_is_rejected() -> None:
    with pytest.raises(ValidationError, match="non-imported capability"):
        _domain(imports=[_imp("Crm", 1, "crm")], bindings=[_bind("Inventory", "odoo")])


def test_double_binding_one_capability_two_backends_is_rejected() -> None:
    with pytest.raises(ValidationError, match="more than one backend"):
        _domain(imports=[_imp("Crm", 1, "crm")], bindings=[_bind("Crm", "odoo"), _bind("Crm", "sap")])


# ── Resolution (what the compiler calls) ──────────────────────────────────────────────────────────
def test_resolve_alias_returns_the_pinned_import() -> None:
    d = _domain(imports=[_imp("Communication", 2, "comms")])
    imp = resolve_alias(d, "comms")
    assert imp is not None and imp.capability == "Communication" and imp.major == 2


def test_resolve_unknown_alias_is_none_so_compiler_refuses() -> None:
    assert resolve_alias(_domain(imports=[_imp("Crm", 1, "crm")]), "ghost") is None


def test_resolve_backend_returns_the_governed_target() -> None:
    d = _domain(imports=[_imp("Crm", 1, "crm")], bindings=[_bind("Crm", "odoo")])
    assert resolve_backend(d, "Crm") == "odoo"


def test_resolve_unbound_capability_is_none_no_implicit_routing() -> None:
    # An imported-but-unbound capability resolves to None — the compiler refuses rather than guess a
    # backend (D8: no newest-declarer-wins).
    assert resolve_backend(_domain(imports=[_imp("Crm", 1, "crm")]), "Crm") is None


def test_two_domains_bind_the_same_capability_to_different_backends() -> None:
    # The multi-ERP case D8 exists for: Procurement.Crm → odoo, Finance.Crm → sap. Both explicit.
    proc = _domain(domain_id="Procurement", imports=[_imp("Crm", 1, "crm")], bindings=[_bind("Crm", "odoo")])
    fin = _domain(domain_id="Finance", imports=[_imp("Crm", 1, "crm")], bindings=[_bind("Crm", "sap")])
    assert resolve_backend(proc, "Crm") == "odoo"
    assert resolve_backend(fin, "Crm") == "sap"
