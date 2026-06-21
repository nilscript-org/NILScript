"""Boot the PocketBase NIL shim with bearer auth enabled, for testing the
authenticated wiring against the kernel's conformance harness.

Usage: NIL_BEARER=secret123 python run_auth_shim.py  (defaults to 'secret123')
"""

from __future__ import annotations

import os

from pocketbase_nil_adapter.edge import CapturingEmitter, HttpEventEmitter, create_app
from pocketbase_nil_adapter.system import FakeSystem

BEARER = os.environ.get("NIL_BEARER", "secret123")
NIL_EVENTS_WEBHOOK = os.environ.get("NIL_EVENTS_WEBHOOK", "")
NIL_EVENTS_SECRET = os.environ.get("NIL_EVENTS_SECRET", "")
NIL_EVENTS_SOURCE = os.environ.get("NIL_EVENTS_SOURCE", "playground")


def _emitter():
    """Reflect every commit to the control plane when a webhook is configured; else in-memory only."""
    if NIL_EVENTS_WEBHOOK:
        return HttpEventEmitter(NIL_EVENTS_WEBHOOK, NIL_EVENTS_SECRET, source=NIL_EVENTS_SOURCE)
    return CapturingEmitter()


def build_auth_app():
    return create_app(FakeSystem(), _emitter(), bearer=BEARER)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(build_auth_app(), host="127.0.0.1", port=8099)
