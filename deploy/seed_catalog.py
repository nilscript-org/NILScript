"""Seed a workspace's governed capability catalog — thin CLI over nilscript.baseline.

The catalog itself (strategies, capabilities, implementing cycles) lives in
`nilscript.baseline.catalog` — the versioned SSOT every workspace materializes from.
This wrapper keeps the operator contract:

Run against a live control-plane DB:   python deploy/seed_catalog.py /data/controlplane.db [workspace]
Run with no arg to self-validate against an in-memory store.

Workspace defaults to ws_acme (the owner workspace) for backward compatibility.
"""

from __future__ import annotations

import sys


def main() -> None:
    from nilscript.baseline import BASELINE_VERSION, apply_baseline
    from nilscript.controlplane.store import EventStore

    path = sys.argv[1] if len(sys.argv) > 1 else ":memory:"
    ws = sys.argv[2] if len(sys.argv) > 2 else "ws_acme"
    store = EventStore(path)
    if store.get_workspace(ws) is None:
        store.create_workspace(workspace=ws)  # adopt legacy ids into the workspaces table
    result = apply_baseline(store, ws)
    print(f"BASELINE  {BASELINE_VERSION} -> {ws}")
    print(f"PUBLISHED ({len(result['published'])}):", ", ".join(result["published"]))
    print(f"DRAFTED   ({len(result['drafted'])}):", ", ".join(result["drafted"]))

    # Honesty self-check: every published capability must `prepare` cleanly (else downgrade to draft).
    if path == ":memory:":
        from fastapi.testclient import TestClient

        from nilscript.controlplane.app import create_app

        client = TestClient(create_app(store, secret=""))
        samples = {
            "SendMessage": {"to": "a@b.com", "subject": "x", "body": "y"},
            "RequestConfirmation": {"to": "a@b.com", "subject": "x", "body": "y", "order_ref": "PO-1"},
            "ManageContact": {"name": "Acme", "phone": "+966500000000", "email": "a@b.com"},
            "CreateProduct": {"name": "Widget", "price": "10", "sku": "W-1"},
            "IssueInvoice": {"client_id": "1", "currency": "SAR", "description": "x"},
            "RecordPayment": {"invoice_id": "1", "amount": "10", "method": "cash"},
            "RecordPurchaseInvoice": {"supplier_id": "1", "currency": "SAR"},
            "RunProcurementOrder": {"order_ref": "PO-1", "supplier": "Acme", "notes": ""},
        }
        for cid, inputs in samples.items():
            r = client.post("/prepared", json={"workspace": ws, "capability_id": cid,
                                               "prepared_by": "agent", "inputs": inputs})
            print(f"PREPARE {cid}: {r.status_code} {r.text[:120]}")


if __name__ == "__main__":
    main()
