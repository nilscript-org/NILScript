"""store.active_adapters — the multi-active query behind verb→adapter routing.

A workspace can have several adapters active at once (e.g. Odoo for crm.* + a comms adapter for
comms.*). `active_adapters` returns every active one (newest-first) so the runner can build a
verb→backend route map; `active_adapter` still returns the single newest for the legacy fast path.
"""

from __future__ import annotations

from nilscript.controlplane.store import EventStore


def _store(tmp_path) -> EventStore:
    return EventStore(str(tmp_path / "cp.db"))


def test_active_adapters_returns_every_active_backend(tmp_path) -> None:
    store = _store(tmp_path)
    store.register_adapter("ws_acme", "odoo", url="http://odoo:8101", bearer="b1", system="odoo")
    store.register_adapter("ws_acme", "comms", url="http://comms:8103", bearer="b2", system="comms")
    store.set_adapter_active("ws_acme", "odoo", True)
    store.set_adapter_active("ws_acme", "comms", True)

    ids = {a["adapter_id"] for a in store.active_adapters("ws_acme")}
    assert ids == {"odoo", "comms"}  # BOTH active — multi-backend routing is possible


def test_inactive_adapter_is_excluded(tmp_path) -> None:
    store = _store(tmp_path)
    store.register_adapter("ws_acme", "odoo", url="http://odoo:8101", bearer="b1", system="odoo")
    store.register_adapter("ws_acme", "comms", url="http://comms:8103", bearer="b2", system="comms")
    store.set_adapter_active("ws_acme", "odoo", True)
    # comms registered but NOT activated → not returned.
    actives = store.active_adapters("ws_acme")
    assert [a["adapter_id"] for a in actives] == ["odoo"]


def test_active_adapters_is_workspace_scoped(tmp_path) -> None:
    store = _store(tmp_path)
    store.register_adapter("ws_a", "odoo", url="http://o", bearer="b", system="odoo")
    store.register_adapter("ws_b", "comms", url="http://c", bearer="b", system="comms")
    store.set_adapter_active("ws_a", "odoo", True)
    store.set_adapter_active("ws_b", "comms", True)
    assert [a["adapter_id"] for a in store.active_adapters("ws_a")] == ["odoo"]
    assert [a["adapter_id"] for a in store.active_adapters("ws_b")] == ["comms"]


def test_empty_when_none_active(tmp_path) -> None:
    store = _store(tmp_path)
    store.register_adapter("ws_acme", "odoo", url="http://odoo:8101", bearer="b1", system="odoo")
    assert store.active_adapters("ws_acme") == []  # registered but not activated
