"""Wave 8.5 Compiler Enhancement routes — compile, validate, publish cycles with full audit trail.

These routes are integrated into the main FastAPI app via mount_wave8_5_routes(app, store, provider).
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nilscript.compiler import GeneratedDsl, CompilationRecord, CompilationStore, generate_dsl
from nilscript.controlplane.cycle_manager import CycleManager
from nilscript.cycle import Cycle
from nilscript.kernel.context import ValidationContext


def _registry_authed(auth_header: str | None, expected_token: str = "") -> bool:
    """Check authorization header (Bearer token)."""
    if not auth_header:
        return False
    if not auth_header.startswith("Bearer "):
        return False
    token = auth_header[7:]
    # For now, any bearer token is accepted. In production, validate against a real token store.
    return bool(token)


async def _read_body(request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Read and parse JSON request body."""
    try:
        body = await request.json()
        return body, None
    except Exception as e:
        return None, JSONResponse(
            {"error": f"Invalid JSON: {e}"}, status_code=400
        )


def _diag_list(result: Any) -> list[dict[str, Any]]:
    """Convert diagnostics to list for JSON response."""
    if hasattr(result, "diagnostics"):
        return [d.model_dump() if hasattr(d, "model_dump") else d for d in result.diagnostics]
    return []


def mount_wave8_5_routes(
    app: FastAPI,
    store: Any,  # EventStore
    provider: Callable[[str], Any],  # async workspace → adapter skeleton
    cycle_manager: CycleManager | None = None,
) -> None:
    """Mount Wave 8.5 Compiler Enhancement routes to the FastAPI app.

    Args:
        app: FastAPI application
        store: EventStore instance
        provider: Async function to get adapter skeleton for workspace
        cycle_manager: Optional CycleManager instance (created if None)
    """
    if cycle_manager is None:
        cycle_manager = CycleManager(store)

    compilation_store = CompilationStore(store._conn)

    @app.post("/api/cycle/compile")
    async def api_cycle_compile(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Compile a cycle AST: V1–V6 + V7 + validation pipeline. Returns GeneratedDsl with text + diagnostics.

        Request body: {
            workspace: str,
            cycle: { Cycle AST object },
            compiled_by?: str (defaults to "system")
        }

        Response: {
            ok: bool,
            cycle_id: str,
            text: str,               # canonical .nil DSL
            content_hash: str,
            diagnostics: [Diagnostic],
            gates: [str],            # approval gate step IDs
            dialect: str             # cycle/0.2 or cycle/0.3
        }
        """
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        body, err = await _read_body(request)
        if err is not None:
            return err

        workspace = (body or {}).get("workspace", "") or ""
        cycle_data = (body or {}).get("cycle")
        compiled_by = (body or {}).get("compiled_by", "system") or "system"

        if not workspace or not cycle_data:
            return JSONResponse(
                {"error": "workspace and cycle are required"}, status_code=400
            )

        try:
            cycle = Cycle.model_validate(cycle_data)
            skeleton = await provider(workspace)
            if skeleton is None:
                return JSONResponse(
                    {"error": "no reachable adapter for workspace"},
                    status_code=503,
                )

            # Build validation context from skeleton
            from nilscript.kernel.context import ValidationContext
            ctx = ValidationContext(
                skills={},  # TODO: extract from skeleton
                read_verbs=frozenset(),
                workspaces={workspace: frozenset()},
            )

            # Generate DSL
            dsl = generate_dsl(cycle, ctx)

            # Record compilation in audit trail
            record = CompilationRecord.from_validation_result(
                workspace=workspace,
                cycle_id=cycle.cycle_id,
                content_hash=dsl.content_hash,
                result=dsl.compile_result.diagnostics,
                compiled_by=compiled_by,
                spec_version=dsl.dialect,
                ontology_version="1.0.0",  # TODO: get from context
            )
            compilation_store.record(record)

            return {
                "ok": dsl.ok,
                "cycle_id": cycle.cycle_id,
                "text": dsl.text,
                "content_hash": dsl.content_hash,
                "diagnostics": _diag_list(dsl.compile_result.diagnostics),
                "gates": list(dsl.gates),
                "dialect": dsl.dialect,
            }
        except Exception as e:
            return JSONResponse(
                {"error": f"Compilation failed: {type(e).__name__}: {e}"},
                status_code=400,
            )

    @app.get("/api/cycle/compilation-status/{job_id}")
    async def api_cycle_compilation_status(
        job_id: str, authorization: str | None = Header(default=None)
    ) -> Any:
        """Poll compilation status. (Placeholder for background job implementation.)

        Returns:
        {
            job_id: str,
            status: str,      # pending|success|error
            cycle_id?: str,
            error?: str,
            diagnostics?: [Diagnostic]
        }
        """
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        # TODO: implement background job queue (Celery / Temporal)
        # For now, return a stub that shows compilation succeeded
        return {
            "job_id": job_id,
            "status": "success",
            "cycle_id": "placeholder",
            "diagnostics": [],
        }

    @app.get("/api/cycle/compilation-history")
    async def api_cycle_compilation_history(
        workspace: str = "", cycle_id: str = "", limit: int = 50, authorization: str | None = Header(default=None)
    ) -> Any:
        """Retrieve compilation audit trail for a cycle.

        Query params:
            workspace: str (required)
            cycle_id: str (required)
            limit: int (default 50)

        Returns:
        {
            ok: bool,
            history: [
                {
                    content_hash: str,
                    compiled_by: str,
                    spec_version: str,
                    ontology_version: str,
                    status: str,
                    cache_hit: bool,
                    created_at: str
                }
            ]
        }
        """
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        if not workspace or not cycle_id:
            return JSONResponse(
                {"error": "workspace and cycle_id are required"}, status_code=400
            )

        try:
            records = compilation_store.get_history(workspace, cycle_id, limit=limit)
            return {
                "ok": True,
                "history": [
                    {
                        "content_hash": r.content_hash,
                        "compiled_by": r.compiled_by,
                        "spec_version": r.spec_version,
                        "ontology_version": r.ontology_version,
                        "status": r.status,
                        "cache_hit": r.cache_hit,
                        "created_at": r.created_at,
                    }
                    for r in records
                ],
            }
        except Exception as e:
            return JSONResponse(
                {"error": f"Failed to retrieve history: {e}"},
                status_code=500,
            )

    @app.post("/api/cycle/publish")
    async def api_cycle_publish(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Publish a cycle: compile → validate → store in cycles table.

        Request body: {
            workspace: str,
            cycle: { Cycle AST object },
            published_by?: str
        }

        Response: {
            ok: bool,
            cycle_id: str,
            status: str,
            content_hash: str,
            message?: str,
            error?: str
        }
        """
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        body, err = await _read_body(request)
        if err is not None:
            return err

        workspace = (body or {}).get("workspace", "") or ""
        cycle_data = (body or {}).get("cycle")
        published_by = (body or {}).get("published_by", "system") or "system"

        if not workspace or not cycle_data:
            return JSONResponse(
                {"error": "workspace and cycle are required"}, status_code=400
            )

        try:
            cycle = Cycle.model_validate(cycle_data)

            # Use CycleManager to compile and publish
            result = cycle_manager.publish_cycle(
                workspace=workspace,
                cycle_id=cycle.cycle_id,
                cycle=cycle,
            )

            if result.get("status") == "compile_error":
                return JSONResponse(
                    {
                        "ok": False,
                        "cycle_id": cycle.cycle_id,
                        "status": "error",
                        "error": result.get("compile_error"),
                    },
                    status_code=400,
                )

            return {
                "ok": True,
                "cycle_id": cycle.cycle_id,
                "status": result.get("status", "published"),
                "content_hash": result.get("content_hash"),
                "message": f"Cycle {cycle.cycle_id} published",
            }
        except Exception as e:
            return JSONResponse(
                {"error": f"Publish failed: {type(e).__name__}: {e}"},
                status_code=500,
            )
