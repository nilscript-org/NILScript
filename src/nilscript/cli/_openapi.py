"""Build an OpenAPI 3.1 document for the NIL agent-plane endpoints from the bundled schemas.

Pure transform: reads the standard's JSON Schemas and emits the one API surface every
conformant backend (or its translation shim) exposes — the six endpoints, no backend
specifics. OpenAPI 3.1 is JSON-Schema-2020-12 compatible, so the standard's schemas drop in
as components unchanged (minus the `$schema` meta key OpenAPI disallows on a component).
"""

from __future__ import annotations

from typing import Any

from nilscript.cli._spec import CORE_SCHEMAS, SPEC_VERSION, load_core_schema

_BASE = f"/nil/v{SPEC_VERSION}"


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _body(name: str) -> dict[str, Any]:
    return {"required": True, "content": {"application/json": {"schema": _ref(name)}}}


def _resp(name: str, description: str) -> dict[str, Any]:
    return {"description": description, "content": {"application/json": {"schema": _ref(name)}}}


def build_openapi() -> dict[str, Any]:
    """Return the OpenAPI 3.1 document for the six NIL endpoints, as a plain dict."""
    components: dict[str, Any] = {}
    for filename, name in CORE_SCHEMAS.items():
        schema = load_core_schema(filename)
        schema.pop("$schema", None)  # OpenAPI components must not carry the JSON-Schema meta key
        components[name] = schema

    paths: dict[str, Any] = {
        f"{_BASE}/propose": {
            "post": {
                "operationId": "propose",
                "summary": "PROPOSE — validate/dry-run a verb. No side effects.",
                "requestBody": _body("ProposeBody"),
                "responses": {"200": _resp("Envelope", "Envelope(PROPOSAL) — proposal or refusal")},
            }
        },
        f"{_BASE}/commit": {
            "post": {
                "operationId": "commit",
                "summary": "COMMIT — execute a previewed proposal. Idempotent on idempotency_key.",
                "requestBody": _body("CommitBody"),
                "responses": {
                    "200": _resp("Envelope", "Envelope(STATUS) — or a PROPOSAL refusal if expired/suspended")
                },
            }
        },
        f"{_BASE}/query": {
            "post": {
                "operationId": "query",
                "summary": "QUERY — read business truth fresh. No side effects.",
                "requestBody": _body("QueryBody"),
                "responses": {"200": _resp("QueryAnswer", "Bare { data } — not an envelope")},
            }
        },
        f"{_BASE}/status/{{proposal_id}}": {
            "get": {
                "operationId": "status",
                "summary": "STATUS — current state of a proposal.",
                "parameters": [
                    {"name": "proposal_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {"200": _resp("Envelope", "Envelope(STATUS)")},
            }
        },
        f"{_BASE}/rollback": {
            "post": {
                "operationId": "rollback",
                "summary": "ROLLBACK — request a governed reversal. Answered by a PROPOSAL (compensation preview); no side effects.",
                "requestBody": _body("RollbackBody"),
                "responses": {
                    "200": _resp("Envelope", "Envelope(PROPOSAL) — the compensation preview, or an IRREVERSIBLE refusal")
                },
            }
        },
        "/webhooks/nil-events": {
            "post": {
                "operationId": "event",
                "summary": "EVENT — backend → gateway push after execution. HMAC-signed.",
                "requestBody": _body("EventBody"),
                "responses": {"200": {"description": "Accepted"}},
            }
        },
    }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "NIL Agent-Plane API",
            "version": SPEC_VERSION,
            "description": (
                "The six endpoints every NIL-conformant backend (or its translation shim) "
                "exposes. Generated from the nilscript standard schemas; contains no backend "
                "specifics."
            ),
        },
        "paths": paths,
        "components": {"schemas": components},
    }
