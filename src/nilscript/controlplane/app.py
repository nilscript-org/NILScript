"""Control-plane ASGI app — ingest NIL events (HMAC-verified), query, and a live single-pane UI.

    uvicorn nilscript.controlplane.app:app --host 0.0.0.0 --port 8088

Adapters POST their EVENT envelopes to /events/ingest (HttpEventEmitter → NIL_EVENTS_WEBHOOK), signed
with NIL_EVENTS_SECRET. The UI at / shows every action across all agents in one timeline.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import hmac
import json
import os
import uuid
from typing import Any

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import ValidationError

from nilscript.automation import (
    Runner,
    composed_hash,
    context_from_skeleton,
    dispatch_event,
    draft_automation,
    fire_composed,
    fire_manual,
    parse_composed,
    parse_trigger,
    register,
    resume_due_waits,
    resume_on_decision,
    run_due_schedules,
    validate_composed,
)
from nilscript.automation.compose import StageRunner
from nilscript.capability import (
    Capability,
    capability_content_hash,
    parse_capability_nil,
    validate_implements,
    wrap_cycle,
)
from nilscript.controlplane import prepared as prepared_cards
from nilscript.controlplane import strategy_exec
from nilscript.controlplane.store import EventStore
from nilscript.cycle import (
    Cycle,
    NilSyntaxError,
    completions as lsp_completions,
    cycle_slug,
    diagnostics as lsp_diagnostics,
    draft_cycle,
    governance_report,
    hover as lsp_hover,
    parse_nil,
    print_nil,
    register_cycle,
    semantic_tokens as lsp_semantic_tokens,
    simulate,
    to_markdown,
    to_mermaid,
)
from nilscript.kernel.diagnostics import ValidationResult
from nilscript.kernel.executor import LocalExecutor, looks_committed
from nilscript.kernel.graph import node_map
from nilscript.kernel.references import resolve as resolve_references
from nilscript.strategy import (
    Strategy,
    parse_strategy_nil,
    strategy_content_hash,
    validate_strategy,
)
from nilscript.sdk.client import NilClient
from nilscript.sdk.idempotency import commit_idempotency_key
from nilscript.sdk.connect import handshake
from nilscript.sdk.grants import GrantRef
from nilscript.sdk.routing import RoutingNilClient
from nilscript.sdk.transport import NilTransport


def _plan_scopes(plan: dict[str, Any]) -> frozenset[str]:
    """Grant scopes for a control-plane-fired run: each verb plus its `skill.*` wildcard."""
    scopes: set[str] = set()
    for node in plan.get("pipeline", []) if isinstance(plan, dict) else []:
        verb = node.get("verb") if isinstance(node, dict) else None
        if isinstance(verb, str) and verb:
            scopes.add(verb)
            scopes.add(verb.split(".", 1)[0] + ".*")
    return frozenset(scopes) or frozenset({"*"})


# An async source of a workspace's live adapter skeleton ({verbs, targets, ...}), or None when there
# is no reachable/conformant active adapter. Injectable so the draft gate is testable without a backend.
SkeletonProvider = Callable[[str], Awaitable[dict[str, Any] | None]]
# Skeleton of a SPECIFIC adapter by id (for cross-system composed plans). (workspace, adapter_id) -> skeleton|None.
AdapterSkeletonProvider = Callable[[str, str], Awaitable[dict[str, Any] | None]]


def _parse_when(when: Any) -> _dt.datetime | None:
    """Parse an ISO-8601 timestamp into an aware UTC datetime. A trailing `Z` is accepted; a
    naive timestamp reads as UTC. Unparseable input is None — the caller refuses, never guesses."""
    if not isinstance(when, str) or not when.strip():
        return None
    try:
        parsed = _dt.datetime.fromisoformat(when.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.UTC)
    return parsed.astimezone(_dt.UTC)


def _diag_list(result: ValidationResult) -> list[dict[str, Any]]:
    return [
        {"code": d.code, "severity": d.severity, "message": d.message, "node": d.node}
        for d in result.diagnostics
    ]


def _redact(adapter: dict[str, Any]) -> dict[str, Any]:
    """A registry record safe to hand to the browser: the bearer (which reaches the adapter) is
    masked to a presence flag, never the value."""
    if not adapter:
        return {}
    bearer = adapter.get("bearer")
    return {**adapter, "bearer": "***" if bearer else ""}


def create_app(
    store: EventStore | None = None,
    *,
    secret: str | None = None,
    registry_token: str | None = None,
    skeleton_provider: SkeletonProvider | None = None,
    runner: Runner | None = None,
    adapter_skeleton_provider: AdapterSkeletonProvider | None = None,
    stage_runner: StageRunner | None = None,
) -> FastAPI:
    store = store if store is not None else EventStore()
    secret = secret if secret is not None else os.environ.get("NIL_EVENTS_SECRET", "")
    registry_token = (
        registry_token
        if registry_token is not None
        else os.environ.get("NIL_REGISTRY_TOKEN", "")
    )
    app = FastAPI(title="nilscript control plane", version="0.1.0")

    def _registry_authed(authorization: str | None) -> bool:
        """Guard the registry's sensitive endpoints. Open when no token is configured (local/test);
        otherwise require `Authorization: Bearer <NIL_REGISTRY_TOKEN>`."""
        if not registry_token:
            return True
        return bool(authorization) and hmac.compare_digest(
            authorization, f"Bearer {registry_token}"
        )

    async def _live_skeleton(workspace: str) -> dict[str, Any] | None:
        """Default skeleton source: discover the workspace's active adapter(s) over NIL and UNION their
        verb surfaces — so an agent SEES every governed verb it can route to (crm.* on one backend,
        comms.* on another), not just one adapter's. None when no active adapter answers conformantly."""
        actives = [a for a in store.active_adapters(workspace) if a.get("url")]
        if not actives:
            return None
        verbs: list[str] = []
        verb_details: list[dict[str, Any]] = []
        targets: dict[str, Any] = {}
        systems: list[str] = []
        any_ok = False
        for a in actives:
            transport = NilTransport(base_url=a["url"], bearer_secret=a.get("bearer", "") or "")
            try:
                report = await handshake(transport)
            finally:
                await transport.aclose()
            if not report.get("reachable") or not report.get("conformant"):
                continue
            any_ok = True
            for vb in report.get("verbs", []) or []:
                if vb not in verbs:
                    verbs.append(vb)
            verb_details.extend(report.get("verb_details", []) or [])
            targets.update(report.get("targets", {}) or {})
            if report.get("system"):
                systems.append(str(report["system"]))
        if not any_ok:
            return None
        return {
            "reachable": True,
            "conformant": True,
            "nil": "0.1",
            "system": "+".join(dict.fromkeys(systems)) or "multi",
            "verbs": verbs,
            "verb_details": verb_details,
            "targets": targets,
        }

    provider: SkeletonProvider = skeleton_provider or _live_skeleton

    def _adapter_client(
        active: dict[str, Any], scopes: frozenset[str], grant_id: str
    ) -> tuple[NilClient, NilTransport]:
        """A NilClient + its transport for ONE adapter row. The adapter's bearer is the transport auth;
        the grant carries the workspace + verb scopes."""
        bearer = active.get("bearer", "") or ""
        transport = NilTransport(base_url=active["url"], bearer_secret=bearer)
        grant = GrantRef.from_secret(
            grant_id=grant_id,
            workspace=active.get("workspace", "") or "",
            secret=bearer or "cp",
            scopes=scopes,
        )
        return NilClient(transport=transport, grant=grant), transport

    async def _routed_client(
        ws: str, scopes: frozenset[str], grant_id: str
    ) -> tuple[Any, list[NilTransport]]:
        """Build the client the executor walks a plan against.

        ONE active adapter → a plain NilClient (zero routing overhead — the common path, unchanged).
        SEVERAL active → a RoutingNilClient that sends each verb to the adapter DECLARING it (learnt
        from each adapter's describe), so a single governed run spans backends (crm.* on Odoo,
        comms.* on the comms adapter). Returns (client_or_None, transports_to_close)."""
        actives = [a for a in store.active_adapters(ws) if a.get("url")]
        if not actives:
            return None, []
        if len(actives) == 1:
            client, transport = _adapter_client(actives[0], scopes, grant_id)
            return client, [transport]
        transports: list[NilTransport] = []
        routes: dict[str, NilClient] = {}
        default: NilClient | None = None
        for a in actives:
            client, transport = _adapter_client(a, scopes, grant_id)
            transports.append(transport)
            report = await handshake(transport)
            for verb in report.get("verbs", []) or []:
                routes.setdefault(verb, client)  # first (newest) declarer wins a conflict
            if default is None:
                default = client
        return RoutingNilClient(default=default, routes=routes), transports

    async def _adapter_declaring(ws: str, verb: str) -> dict[str, Any] | None:
        """The active adapter that DECLARES `verb` — the backend that held its proposal, where the
        approved commit must land. Falls back to the workspace default (single-adapter / legacy)."""
        actives = [a for a in store.active_adapters(ws) if a.get("url")]
        if len(actives) <= 1:
            return actives[0] if actives else (store.active_adapter(ws) or store.any_active_adapter())
        for a in actives:
            transport = NilTransport(base_url=a["url"], bearer_secret=a.get("bearer", "") or "")
            try:
                report = await handshake(transport)
            finally:
                await transport.aclose()
            if verb in (report.get("verbs", []) or []):
                return a
        return store.active_adapter(ws) or store.any_active_adapter()

    async def _live_runner(
        plan: dict[str, Any],
        *,
        run_id: str,
        resume: dict[str, Any] | None = None,
        input: dict[str, Any] | None = None,
    ) -> Any:
        """Default runner: walk the pinned plan against the workspace's active adapter(s) via a
        headless LocalExecutor. With several adapters active the verbs are routed per-backend (see
        `_routed_client`). The adapter bearer is the transport auth; the grant scopes are the plan's
        own verbs. `resume` continues a PARKED run from its row-backed context (gates / wait_for_event).
        (Production grant minting is the one knob to revisit when CP-initiated runs need a
        distinct identity from the adapter bearer.)"""
        ws = plan.get("workspace", "") if isinstance(plan, dict) else ""
        client, transports = await _routed_client(ws, _plan_scopes(plan), "control-plane")
        if client is None:
            raise RuntimeError(f"no active adapter for workspace {ws!r}")
        try:
            executor = LocalExecutor(
                client,
                run_id=run_id,
                session_id=run_id,
                locale=plan.get("locale", "ar"),
            )
            return await executor.execute(plan, resume=resume, input=input)
        finally:
            for transport in transports:
                await transport.aclose()

    run_exec: Runner = runner or _live_runner

    async def _live_adapter_skeleton(
        workspace: str, adapter_id: str
    ) -> dict[str, Any] | None:
        """Discover a SPECIFIC registered adapter (by id) over NIL — for composed-plan validation,
        where each stage names its own backend (which may not be the workspace's active one)."""
        match = next(
            (
                a
                for a in store.list_adapters(workspace)
                if a.get("adapter_id") == adapter_id and a.get("url")
            ),
            None,
        )
        if match is None:
            return None
        transport = NilTransport(
            base_url=match["url"], bearer_secret=match.get("bearer", "") or ""
        )
        try:
            report = await handshake(transport)
        finally:
            await transport.aclose()
        return report if report.get("reachable") and report.get("conformant") else None

    adapter_skeletons: AdapterSkeletonProvider = (
        adapter_skeleton_provider or _live_adapter_skeleton
    )

    async def _live_stage_runner(
        adapter: str, plan: dict[str, Any], *, run_id: str, input: dict[str, Any]
    ) -> Any:
        """Run one composed stage against the named adapter (by id) via a headless LocalExecutor."""
        ws = plan.get("workspace", "") if isinstance(plan, dict) else ""
        match = next(
            (
                a
                for a in store.list_adapters(ws)
                if a.get("adapter_id") == adapter and a.get("url")
            ),
            None,
        )
        if match is None:
            raise RuntimeError(f"no registered adapter {adapter!r} in workspace {ws!r}")
        bearer = match.get("bearer", "") or ""
        transport = NilTransport(base_url=match["url"], bearer_secret=bearer)
        grant = GrantRef.from_secret(
            grant_id="control-plane",
            workspace=ws,
            secret=bearer or "cp",
            scopes=_plan_scopes(plan),
        )
        client = NilClient(transport=transport, grant=grant)
        try:
            return await LocalExecutor(
                client,
                run_id=run_id,
                session_id=run_id,
                locale=plan.get("locale", "ar"),
            ).execute(plan, input=input or None)
        finally:
            await transport.aclose()

    stage_exec: StageRunner = stage_runner or _live_stage_runner
    _bg_tasks: set[asyncio.Task[Any]] = (
        set()
    )  # keep fire-and-forget dispatch tasks from being GC'd

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "events": store.count()}

    @app.post("/events/ingest")
    async def ingest(
        request: Request,
        x_nil_signature: str | None = Header(default=None),
        x_nil_sequence: str | None = Header(default=None),
        x_nil_source: str | None = Header(default=None),
    ) -> Any:
        raw = await request.body()
        if secret:
            expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
            if not x_nil_signature or not hmac.compare_digest(
                x_nil_signature, expected
            ):
                return JSONResponse({"error": "bad signature"}, status_code=401)
        try:
            envelope = json.loads(raw)
        except (ValueError, TypeError):
            return JSONResponse({"error": "bad json"}, status_code=400)
        seq = (
            int(x_nil_sequence)
            if (x_nil_sequence and x_nil_sequence.lstrip("-").isdigit())
            else None
        )
        new = store.ingest(envelope, seq, source=x_nil_source or "mcp")
        if new:
            # Fire event-triggered automations off the request path — ingest must stay fast and must
            # not block on (or fail because of) a downstream run. The loop guard in dispatch_event
            # skips events that triggered runs themselves produced.
            task = asyncio.create_task(dispatch_event(store, envelope, runner=run_exec))
            _bg_tasks.add(task)
            task.add_done_callback(_bg_tasks.discard)
        return {"ok": True, "new": new}

    @app.get("/api/events")
    def events(limit: int = 100, workspace: str | None = None) -> dict[str, Any]:
        # SaaS: a workspace query param scopes the timeline to that tenant (the BFF passes the
        # authenticated workspace); omitted = operator/global view.
        return {"events": store.recent(limit, workspace=workspace)}

    @app.get("/api/events/{event_id}")
    def event_detail(event_id: int) -> Any:
        """The full payload journey for one row — intent → resolution → field-level SSOT verdict →
        effect — fetched lazily when the operator expands a row."""
        detail = store.detail(event_id)
        if detail is None:
            return JSONResponse({"error": "no such event"}, status_code=404)
        return detail

    # ── human-approval gate (Phase 2) ────────────────────────────────────────────────────────
    @app.post("/proposals/{proposal_id}/await")
    async def await_approval(proposal_id: str, request: Request) -> dict[str, Any]:
        """Called by the gate when it holds a proposal for owner approval. The gate passes the verb +
        human preview (a held proposal has no ledger event to enrich from) so the Decisions screen
        shows WHAT is being approved."""
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = {}
        return store.await_approval(
            proposal_id,
            verb=body.get("verb"),
            tier=body.get("tier"),
            preview=body.get("preview"),
            workspace=body.get("workspace") or "",
            resolved=body.get("resolved"),
            modifiable=body.get("modifiable"),
            plan_id=body.get("plan_id"),
            seq=int(body.get("seq") or 0),
            depends_on=body.get("depends_on"),
        )

    @app.post("/plans/{plan_id}/steps")
    async def register_planned_step(plan_id: str, request: Request) -> dict[str, Any]:
        """Register a dependent step that is NOT yet proposed to the adapter (its handoff reference
        can't resolve until its prerequisite commits) — governed dependent plans. Carries a synthetic
        proposal_id so the UI can render a blocked card; the executor materializes it on the
        prerequisite's commit."""
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = {}
        return store.register_planned_step(
            body.get("proposal_id"),
            plan_id=plan_id,
            seq=int(body.get("seq") or 0),
            depends_on=body.get("depends_on"),
            verb=body.get("verb") or "",
            args=body.get("args") or {},
            handoff=body.get("handoff") or {},
            preview=body.get("preview"),
            tier=body.get("tier"),
            workspace=body.get("workspace") or "",
        )

    @app.get("/proposals/{proposal_id}/decision")
    def get_decision(proposal_id: str) -> dict[str, Any]:
        """Polled by the gate before it commits a held proposal."""
        return {"proposal_id": proposal_id, "status": store.decision(proposal_id)}

    async def _execute_approved(
        proposal_id: str, edits: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """The owner approved a HELD proposal → the CONTROL PLANE commits it against the active adapter.
        This is the SSOT keystone: approval DRIVES execution (the agent never re-commits), so an approve
        click actually performs the deletion/effect. Reuses the `_live_runner` client pattern; the
        proposal detail (verb) rides on the approval row (threaded at hold-time), so no MCP memory is
        needed — survives MCP restarts. Honest on failure (expired / already committed / unreachable).

        If the owner EDITED the fields on the decision card, `edits` holds the full amended args. We
        re-PROPOSE those against the adapter (a fresh preview + id) and commit THAT — so the commit
        still executes exactly what was previewed. The NIL invariant holds even under a human tweak."""
        appr = store.approval(proposal_id) or {}
        ws = store.proposal_workspace(proposal_id) or ""
        verb = appr.get("verb")
        # Commit on the adapter that DECLARED the verb (the backend that held this proposal), not just
        # the workspace default — with several adapters active, the default may be a sibling that never
        # saw it. Falls back to the default for single-adapter / legacy workspaces.
        active = (
            await _adapter_declaring(ws, verb)
            if (ws and verb)
            else (store.active_adapter(ws) if ws else store.any_active_adapter())
        )
        if not active or not active.get("url"):
            return {"executed": False, "error": "no active adapter to commit against"}
        ws = active.get("workspace", "") or ""
        bearer = active.get("bearer", "") or ""
        transport = NilTransport(base_url=active["url"], bearer_secret=bearer)
        grant = GrantRef.from_secret(
            grant_id="control-plane-approval",
            workspace=ws,
            secret=bearer or "cp",
            scopes=frozenset({verb}) if verb else frozenset(),
        )
        client = NilClient(transport=transport, grant=grant)
        try:
            commit_id = proposal_id
            edited = False
            if edits and verb:
                # amended args → re-propose (fresh dry-run + preview), then commit the NEW proposal.
                reproposed = await client.propose(
                    verb,
                    edits,
                    session_id=f"cp-approve:{proposal_id}",
                    request_timestamp=_dt.datetime.now(_dt.UTC),
                )
                if reproposed.is_refusal or not reproposed.id:
                    return {
                        "executed": False,
                        "error": "edited args rejected at re-propose: "
                        f"{reproposed.code or 'refused'} {reproposed.message or ''}".strip(),
                    }
                commit_id, edited = reproposed.id, True
            key = commit_idempotency_key(f"cp-approve:{commit_id}", commit_id)
            outcome = await client.commit(commit_id, idempotency_key=key)
            dumped = outcome.model_dump(mode="json", exclude_none=True)
            # The committed backend id (result.entity.id) — a dependent step's handoff placeholder
            # ($.step0.id) resolves to this when the ordered executor materializes it.
            committed_id = ((dumped.get("result") or {}).get("entity") or {}).get("id")
            return {
                "executed": True,
                "edited": edited,
                "committed_id": committed_id,
                "outcome": dumped,
            }
        except Exception as exc:  # noqa: BLE001 — adapter unreachable / proposal expired / already done
            return {"executed": False, "error": f"{type(exc).__name__}: {exc}"}
        finally:
            await transport.aclose()

    async def _execute_rollback(appr: dict[str, Any]) -> dict[str, Any]:
        """The owner approved a ROLLBACK PLAN (plan B5) → commit its compensation chain, in the
        plan's (reverse-commit) order, via PROPOSE→COMMIT against the active adapter — the same
        honest compensation path the kernel's saga unwind uses (each step is the write's own
        `compensate_with`). The `rb-{run_id}-{n}` idempotency keys make a crash-window retry
        replay, never double-compensate. Honest on failure: the chain stops at the first refusal
        and reports exactly what WAS compensated."""
        plan = appr.get("resolved") if isinstance(appr.get("resolved"), dict) else {}
        steps = plan.get("steps") or []
        ws = plan.get("workspace") or ""
        active = store.active_adapter(ws) if ws else store.any_active_adapter()
        if not active or not active.get("url"):
            return {"executed": False, "error": "no active adapter to commit against"}
        ws = active.get("workspace", "") or ""
        bearer = active.get("bearer", "") or ""
        verbs = frozenset(s.get("verb") for s in steps if s.get("verb"))
        transport = NilTransport(base_url=active["url"], bearer_secret=bearer)
        grant = GrantRef.from_secret(
            grant_id="control-plane-rollback", workspace=ws, secret=bearer or "cp", scopes=verbs
        )
        client = NilClient(transport=transport, grant=grant)
        compensated: list[dict[str, Any]] = []
        try:
            for step in steps:
                proposal = await client.propose(
                    step["verb"],
                    step.get("args") or {},
                    session_id=f"cp-rollback:{plan.get('run_id')}",
                    request_timestamp=_dt.datetime.now(_dt.UTC),
                )
                if proposal.is_refusal or not proposal.id:
                    return {
                        "executed": False,
                        "compensated": compensated,
                        "error": f"compensation for {step.get('node')} refused: "
                        f"{proposal.code or 'refused'} {proposal.message or ''}".strip(),
                    }
                await client.commit(proposal.id, idempotency_key=step["idempotency_key"])
                compensated.append(
                    {"node": step.get("node"), "verb": step.get("verb"), "proposal": proposal.id}
                )
            return {
                "executed": True,
                "rolled_back_to": plan.get("to_checkpoint"),
                "compensated": compensated,
            }
        except Exception as exc:  # noqa: BLE001 — adapter unreachable mid-chain: honest partial
            return {
                "executed": False,
                "compensated": compensated,
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            await transport.aclose()

    def _resolve_handoff(
        args: dict[str, Any], handoff: dict[str, Any], committed_ids: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve a dependent step's handoff placeholders into its args. A handoff maps an arg field
        to a reference of the form `$.step<i>.<field>` — today the only produced field is the committed
        id (`$.step0.id`), so it resolves to the prerequisite's committed backend id. Mirrors the
        composed-automation `$.input.X` handoff. Unresolvable refs are left as-is (the propose refuses)."""
        resolved = dict(args)
        for arg_field, ref in (handoff or {}).items():
            if not isinstance(ref, str) or not ref.startswith("$.step"):
                continue
            # `$.step0.id` → seq 0, field 'id'. We resolve by the committed id of the referenced step.
            rest = ref[len("$.step"):]
            seq_str, _, _field = rest.partition(".")
            value = committed_ids.get(seq_str)
            if value is not None:
                resolved[arg_field] = value
        return resolved

    async def _materialize_dependents(
        plan_id: str, prerequisite_id: str, prereq_seq: Any, committed_id: Any
    ) -> list[dict[str, Any]]:
        """A prerequisite step committed → find the plan's PLANNED steps that depend on it, resolve
        their handoff placeholders to its committed id, PROPOSE them now against the active adapter, and
        register each HELD as a real plan card (unblocking it). This 'materialize dependent on
        prerequisite commit' is the core of governed dependent plans."""
        materialized: list[dict[str, Any]] = []
        store.record_committed(prerequisite_id, str(committed_id) if committed_id is not None else None)
        planned = store.next_planned_steps(plan_id, prerequisite_id)
        if not planned:
            return materialized
        ws = store.proposal_workspace(prerequisite_id) or ""
        active = store.active_adapter(ws) if ws else store.any_active_adapter()
        if not active or not active.get("url"):
            return materialized
        ws = active.get("workspace", "") or ""
        bearer = active.get("bearer", "") or ""
        # Map the referenced step's seq → committed id, so `$.step<prereq_seq>.id` resolves.
        committed_ids = {str(prereq_seq): committed_id}
        for step in planned:
            verb = step.get("verb") or ""
            args = _resolve_handoff(step.get("args") or {}, step.get("handoff") or {}, committed_ids)
            transport = NilTransport(base_url=active["url"], bearer_secret=bearer)
            grant = GrantRef.from_secret(
                grant_id="control-plane-plan", workspace=ws, secret=bearer or "cp",
                scopes=frozenset({verb}) if verb else frozenset(),
            )
            client = NilClient(transport=transport, grant=grant)
            try:
                proposal = await client.propose(
                    verb, args, session_id=f"cp-plan:{step['proposal_id']}",
                    request_timestamp=_dt.datetime.now(_dt.UTC),
                )
            except Exception as exc:  # noqa: BLE001 — adapter unreachable during materialization
                materialized.append({"seq": step.get("seq"), "error": f"{type(exc).__name__}: {exc}"})
                await transport.aclose()
                continue
            await transport.aclose()
            if proposal.is_refusal or not proposal.id:
                materialized.append({
                    "seq": step.get("seq"),
                    "error": f"materialize refused: {proposal.code or 'refused'} {proposal.message or ''}".strip(),
                })
                continue
            store.promote_planned_step(
                step["proposal_id"], real_proposal_id=proposal.id, verb=proposal.verb,
                tier=proposal.tier.value if proposal.tier is not None else None,
                preview=proposal.preview, workspace=ws, plan_id=plan_id, seq=int(step.get("seq") or 0),
                depends_on=prerequisite_id, resolved=proposal.resolved or {},
                modifiable=list(proposal.modifiable or ()),
            )
            materialized.append({"seq": step.get("seq"), "proposal_id": proposal.id, "verb": proposal.verb})
        return materialized

    @app.post("/proposals/{proposal_id}/decision")
    async def post_decision(proposal_id: str, request: Request) -> Any:
        """Owner approves/rejects from the UI. On APPROVE the control plane immediately executes the
        held proposal against the active adapter (the approval drives the effect)."""
        body = {}
        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = {}
        status = body.get("status")
        if status not in ("approved", "rejected"):
            return JSONResponse(
                {"error": "status must be 'approved' or 'rejected'"}, status_code=400
            )
        # Governed dependent plans: a step's approval order is enforced here. Approving a BLOCKED step
        # (its prerequisite not yet committed) is refused; the owner must approve the prerequisite
        # first. This never touches standalone proposals (plan_id/depends_on are NULL).
        appr = store.approval(proposal_id) or {}
        plan_id = appr.get("plan_id")
        depends_on = appr.get("depends_on")
        if status == "approved" and depends_on:
            prereq = store.approval(depends_on) or {}
            if not (prereq.get("status") == "approved" and prereq.get("committed_id") is not None):
                return JSONResponse(
                    {
                        "ok": False,
                        "proposal_id": proposal_id,
                        "error": "step is BLOCKED: its prerequisite must be approved and committed first",
                        "depends_on": depends_on,
                    },
                    status_code=409,
                )
        ok = store.decide(
            proposal_id,
            status,
            actor=body.get("actor", "owner"),
            reason=body.get("reason", ""),
        )
        result: dict[str, Any] = {
            "ok": ok,
            "proposal_id": proposal_id,
            "status": store.decision(proposal_id),
        }
        if ok and status == "rejected" and plan_id:
            # Rejecting ANY step cancels the whole plan (no orphan): reject its pending holds and
            # cancel its not-yet-proposed planned steps.
            result["plan_cancelled"] = {"plan_id": plan_id, "steps": store.cancel_plan(plan_id)}
        if ok and status == "approved":
            if appr.get("verb") == "run.rollback" and proposal_id.startswith("rb:"):
                # A rollback plan's approval commits its compensation chain (B5) — never the
                # single-proposal path (there is no adapter proposal named `rb:…` to commit).
                execution = await _execute_rollback(appr)
            else:
                edits = body.get("edits") if isinstance(body.get("edits"), dict) else None
                execution = await _execute_approved(proposal_id, edits)
            result["execution"] = execution
            # On a prerequisite's successful commit, materialize the dependents that were waiting on it.
            if plan_id and execution.get("executed"):
                result["materialized"] = await _materialize_dependents(
                    plan_id, proposal_id, appr.get("seq") or 0, execution.get("committed_id")
                )
        # Gates resume runs: the SAME decision that executes the approved proposal resumes every
        # run parked on it (row-backed — survives restarts). Approve continues the run at the
        # parked node's continuation with the commit result bound; reject routes the run to its
        # rejection path (or closes it as rejected with the reason).
        if ok:
            parks = store.parked_for_proposal(proposal_id)
            if parks:
                execution = result.get("execution") or {}
                commit_output = None
                if status == "approved":
                    outcome = execution.get("outcome") or {}
                    commit_output = {
                        "proposal": proposal_id,
                        "state": outcome.get("state") or "executed",
                        "committed_id": execution.get("committed_id"),
                        "result": outcome.get("result"),
                    }
                resumed: list[dict[str, Any]] = []
                for park in parks:
                    if status == "approved" and not execution.get("executed"):
                        # The commit itself failed — resuming would bind a phantom result. Honest:
                        # the run stays parked; the owner sees why and can retry the decision.
                        resumed.append(
                            {
                                "run_id": park["run_id"],
                                "resumed": False,
                                "reason": execution.get("error") or "commit failed",
                            }
                        )
                        continue
                    resumed.append(
                        await resume_on_decision(
                            store,
                            park,
                            runner=run_exec,
                            status=status,
                            commit_output=commit_output,
                            reason=body.get("reason", ""),
                        )
                    )
                result["resumed"] = resumed
        return result

    @app.get("/api/pending")
    def pending(workspace: str | None = None) -> dict[str, Any]:
        # SaaS: scope held proposals to the tenant (joined to its events' workspace); omitted = global.
        return {"pending": store.pending(workspace=workspace)}

    @app.get("/api/adapters")
    def adapters() -> dict[str, Any]:
        return {"adapters": store.adapters()}

    @app.get("/adapters/{workspace}/routing")
    def adapters_routing(
        workspace: str, authorization: str | None = Header(default=None)
    ) -> Any:
        """Active adapters (url + bearer) for a workspace — so a MULTI-ADAPTER client (the MCP) can
        union their verbs and route each verb to its declaring backend, the same way the control-plane
        runner does. Token-gated because it returns bearers."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        actives = [a for a in store.active_adapters(workspace) if a.get("url")]
        return {
            "adapters": [
                {
                    "adapter_id": a["adapter_id"],
                    "url": a["url"],
                    "bearer": a.get("bearer", "") or "",
                    "system": a.get("system", ""),
                }
                for a in actives
            ]
        }

    @app.get("/api/adapter-skeleton")
    async def api_adapter_skeleton(
        workspace: str = "",
        adapter_id: str = "",
        authorization: str | None = Header(default=None),
    ) -> Any:
        """The verbs (and target names) a specific adapter declares — feeds the UI compose form's verb
        dropdowns. Token-gated: it triggers a live handshake using the adapter's bearer."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        skeleton = await adapter_skeletons(workspace, adapter_id)
        if skeleton is None:
            return JSONResponse(
                {"error": "adapter not reachable/conformant"}, status_code=503
            )
        return {
            "verbs": skeleton.get("verbs", []),
            # Declared governance metadata per verb (optional; [] when the adapter doesn't
            # declare). The BFF/UI must prefer these over any name-based guessing.
            "verb_details": skeleton.get("verb_details", []),
            "targets": sorted((skeleton.get("targets") or {}).keys()),
        }

    @app.get("/api/automations")
    def api_automations() -> dict[str, Any]:
        """Dashboard view of every automation (latest version, all workspaces). Public read — no
        secrets in the record; the heavy plan is summarised, not shipped whole."""
        out: list[dict[str, Any]] = []
        for a in store.all_automations():
            plan = a.get("plan") or {}
            if a.get("kind") == "composed":
                stages = plan.get("stages") or []
                summary = {
                    "stages": len(stages),
                    "adapters": sorted(
                        {s.get("adapter") for s in stages if isinstance(s, dict)}
                    ),
                }
            else:
                summary = {"nodes": len(plan.get("pipeline") or [])}
            out.append(
                {
                    "workspace": a["workspace"],
                    "automation_id": a["automation_id"],
                    "version": a["version"],
                    "content_hash": a["content_hash"],
                    "kind": a.get("kind", "single"),
                    "name": a.get("name") or {},
                    "state": a["state"],
                    "trigger": a.get("trigger") or {},
                    "approved_by": a.get("approved_by"),
                    "authored_by": a.get("authored_by"),
                    "created_at": a.get("created_at"),
                    "plan_summary": summary,
                }
            )
        return {"automations": out}

    # ── active-adapter registry (multi-tenant routing) ───────────────────────────────────────
    @app.post("/adapters/register")
    async def register_adapter(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Register/refresh an adapter the MCP can route to (auth-protected — carries a bearer)."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return JSONResponse({"error": "bad json"}, status_code=400)
        ws, aid, url = (
            body.get("workspace", "") or "",
            body.get("adapter_id"),
            body.get("url"),
        )
        if not aid or not url:
            return JSONResponse(
                {"error": "adapter_id and url are required"}, status_code=400
            )
        rec = store.register_adapter(
            ws,
            aid,
            label=body.get("label", "") or "",
            url=url,
            bearer=body.get("bearer", "") or "",
            system=body.get("system", "") or "",
        )
        return {"ok": True, "adapter": _redact(rec)}

    @app.post("/tenants/provision")
    async def provision_tenant(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """One-call onboarding for a company: save its secrets (encrypted) ONCE, then register +
        activate its adapter — a new tenant is stood up in a single privileged call. Auth-protected
        (registry token); never called from the browser (the OS BFF brokers it behind keycloak)."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return JSONResponse({"error": "bad json"}, status_code=400)
        ws = body.get("workspace", "") or ""
        if not ws:
            return JSONResponse({"error": "workspace is required"}, status_code=400)
        steps: dict[str, Any] = {}
        secrets = body.get("secrets") or {}
        if secrets:
            try:
                store.put_secrets(
                    ws, secrets
                )  # adapter creds + llm key, encrypted at rest
                steps["secrets"] = sorted(secrets.keys())
            except RuntimeError as exc:  # vault disabled (no NIL_VAULT_KEY)
                return JSONResponse({"error": str(exc)}, status_code=503)
        adapter = body.get("adapter") or {}
        if adapter.get("adapter_id") and adapter.get("url"):
            store.register_adapter(
                ws,
                adapter["adapter_id"],
                label=adapter.get("label", "") or "",
                url=adapter["url"],
                bearer=adapter.get("bearer", "") or "",
                system=adapter.get("system", "") or "",
            )
            store.activate_adapter(ws, adapter["adapter_id"])
            steps["adapter"] = f"{adapter['adapter_id']} registered+activated"
        return {"ok": True, "workspace": ws, "provisioned": steps}

    @app.get("/tenants/{workspace}/secret/{name}")
    def get_tenant_secret(
        workspace: str, name: str, authorization: str | None = Header(default=None)
    ) -> Any:
        """Server-to-server secret fetch for the platform (e.g. the MCP needs a tenant's LLM key).
        Registry-token-gated; returns the DECRYPTED value to the authenticated platform caller only —
        never reachable from the browser, never logged."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        value = store.get_secret(workspace, name)
        if value is None:
            return JSONResponse({"error": "no such secret"}, status_code=404)
        return {"workspace": workspace, "name": name, "value": value}

    @app.post("/adapters/{workspace}/{adapter_id}/activate")
    def activate_adapter(
        workspace: str,
        adapter_id: str,
        authorization: str | None = Header(default=None),
    ) -> Any:
        """Make this adapter the active backend for the workspace (auth-protected)."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if not store.activate_adapter(workspace, adapter_id):
            return JSONResponse({"error": "no such adapter"}, status_code=404)
        return {"ok": True, "workspace": workspace, "adapter_id": adapter_id}

    @app.post("/adapters/{workspace}/{adapter_id}/enable")
    def enable_adapter(
        workspace: str,
        adapter_id: str,
        authorization: str | None = Header(default=None),
    ) -> Any:
        """Enable an adapter WITHOUT deactivating siblings — several can be active at once (e.g.
        PocketBase + Odoo for a cross-system automation). Operator-gated."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if not store.set_adapter_active(workspace, adapter_id, True):
            return JSONResponse({"error": "no such adapter"}, status_code=404)
        return {
            "ok": True,
            "workspace": workspace,
            "adapter_id": adapter_id,
            "active": True,
        }

    @app.post("/adapters/{workspace}/{adapter_id}/disable")
    def disable_adapter(
        workspace: str,
        adapter_id: str,
        authorization: str | None = Header(default=None),
    ) -> Any:
        """Disable one adapter (leaves siblings untouched). Operator-gated."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if not store.set_adapter_active(workspace, adapter_id, False):
            return JSONResponse({"error": "no such adapter"}, status_code=404)
        return {
            "ok": True,
            "workspace": workspace,
            "adapter_id": adapter_id,
            "active": False,
        }

    @app.get("/adapters")
    def list_adapters(workspace: str = "") -> dict[str, Any]:
        """List a workspace's registered adapters for the UI — bearer REDACTED (public read)."""
        return {"adapters": [_redact(a) for a in store.list_adapters(workspace)]}

    @app.get("/api/registry")
    def registry_view() -> dict[str, Any]:
        """Read-only registry view for the PUBLIC control-plane page: which adapter the MCP routes to
        for the owner workspace, bearer REDACTED. No write controls live in the browser — activation
        is operator-only via `nilscript adapters activate` (token never reaches the client)."""
        ws = os.environ.get("NIL_WORKSPACE", "")
        return {
            "workspace": ws,
            "adapters": [_redact(a) for a in store.list_adapters(ws)],
        }

    @app.get("/adapters/active")
    def get_active_adapter(
        workspace: str = "", authorization: str | None = Header(default=None)
    ) -> Any:
        """The workspace's active adapter WITH bearer — for the MCP to route. Auth-protected."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        active = store.active_adapter(workspace)
        if active is None:
            return JSONResponse({"error": "no active adapter"}, status_code=404)
        return {"adapter": active}

    # ── automation registry (conversation-authored, deterministically lowered, SSOT-stored) ─────
    async def _draft_from_body(body: dict[str, Any]) -> tuple[Any, Any]:
        """Validate a draft request against the workspace's live skeleton. Returns (DraftResult, None)
        or (None, JSONResponse-error). The plan's own `workspace` selects the adapter to validate
        against, so the lowered plan is bounded by the backend that will actually run it."""
        plan = body.get("plan")
        aid, name, trigger = (
            body.get("automation_id"),
            body.get("name"),
            body.get("trigger"),
        )
        if not isinstance(plan, dict) or not aid or name is None or trigger is None:
            return None, JSONResponse(
                {"error": "automation_id, name, plan, trigger are required"},
                status_code=400,
            )
        ws = plan.get("workspace")
        if not ws:
            return None, JSONResponse(
                {"error": "plan.workspace is required"}, status_code=400
            )
        skeleton = await provider(ws)
        if skeleton is None:
            return None, JSONResponse(
                {"error": "no reachable active adapter for this workspace"},
                status_code=503,
            )
        ctx = context_from_skeleton(ws, skeleton)
        try:
            res = draft_automation(
                automation_id=aid,
                name=name,
                raw_plan=plan,
                trigger=trigger,
                ctx=ctx,
                authored_by=body.get("authored_by", "") or "",
                description=body.get("description"),
            )
        except (ValidationError, ValueError) as exc:
            return None, JSONResponse(
                {"error": f"malformed request: {exc}"}, status_code=400
            )
        return res, None

    @app.post("/automations/draft")
    async def automation_draft(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Preview: lower the agent's candidate plan against the live skeleton. No side effect.
        Returns the validator verdict + content-hash, or a structured refusal."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return JSONResponse({"error": "bad json"}, status_code=400)
        res, err = await _draft_from_body(body)
        if err is not None:
            return err
        if not res.ok:
            return {"ok": False, "refusal": _diag_list(res.diagnostics)}
        return {
            "ok": True,
            "content_hash": res.content_hash,
            "definition": res.definition.model_dump(by_alias=True, mode="json"),
        }

    @app.post("/automations/register")
    async def automation_register(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Persist a passing draft to the SSOT as `pending_approval` (never auto-armed). Re-registering
        an identical plan is an idempotent no-op. A failing plan is refused — never stored."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return JSONResponse({"error": "bad json"}, status_code=400)
        res, err = await _draft_from_body(body)
        if err is not None:
            return err
        if not res.ok:
            return JSONResponse(
                {"ok": False, "refusal": _diag_list(res.diagnostics)}, status_code=400
            )
        stored = register(store, res.definition)  # lands in pending_approval
        return {"ok": True, "definition": stored.model_dump(by_alias=True, mode="json")}

    # ── Cycle AST (the visual surface registers THROUGH the kernel) ──────────────────────────
    async def _cycle_draft_from_body(body: dict[str, Any]) -> tuple[Any, Any, Any]:
        """Compile a candidate Cycle AST against the workspace's live skeleton. Returns
        (CycleDraftResult, skeleton, None) or (None, None, JSONResponse-error). Same governance
        path as a plain automation draft — lower → V1–V6 → AST content-hash — so a drawn cycle
        cannot talk past a refusal (a hallucinated verb has nothing to bind to). The skeleton is
        returned so register can run V7 against the same DECLARED verb metadata."""
        cycle = body.get("cycle")
        if not isinstance(cycle, dict):
            return None, None, JSONResponse(
                {"error": "cycle (AST object) is required"}, status_code=400
            )
        ws = cycle.get("workspace")
        if not ws:
            return None, None, JSONResponse(
                {"error": "cycle.workspace is required"}, status_code=400
            )
        skeleton = await provider(ws)
        if skeleton is None:
            return None, None, JSONResponse(
                {"error": "no reachable active adapter for this workspace"}, status_code=503
            )
        ctx = context_from_skeleton(ws, skeleton)
        try:
            res = draft_cycle(raw_cycle=cycle, ctx=ctx)
        except (ValidationError, ValueError) as exc:
            return None, None, JSONResponse(
                {"error": f"malformed cycle: {exc}"}, status_code=400
            )
        return res, skeleton, None

    def _v7_verdict(cycle: Cycle, skeleton: dict[str, Any] | None) -> ValidationResult:
        """A4-V7: when the cycle declares `implements`, resolve the target from the WORKSPACE-
        PINNED capability registry (latest version; a missing target refuses with
        V7_UNKNOWN_CAPABILITY) and run the pure conformance validator with the adapter's
        DECLARED verb metadata (undeclared = HIGH, fail closed)."""
        capability: Capability | None = None
        if cycle.implements is not None:
            rec = store.get_capability(cycle.workspace, cycle.implements.capability_id)
            if rec is not None:
                try:
                    capability = Capability.model_validate(rec.get("body") or {})
                except (ValidationError, ValueError):
                    capability = None  # an unreadable record proves nothing — fail closed
        details: dict[str, dict[str, Any]] = {
            d["verb"]: d
            for d in (skeleton or {}).get("verb_details", [])
            if isinstance(d, dict) and d.get("verb")
        }
        return validate_implements(cycle, capability, verb_metadata_lookup=details.get)

    @app.post("/cycles/draft")
    async def cycle_draft_endpoint(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Preview: lower a drawn cycle against the live skeleton. No side effect. Returns the
        validator verdict + AST content-hash + approval gates, or a structured refusal."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return JSONResponse({"error": "bad json"}, status_code=400)
        res, _skeleton, err = await _cycle_draft_from_body(body)
        if err is not None:
            return err
        if not res.ok:
            return {"ok": False, "refusal": _diag_list(res.diagnostics)}
        return {"ok": True, "content_hash": res.content_hash, "gates": list(res.gates)}

    @app.post("/cycles/register")
    async def cycle_register_endpoint(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Persist a passing cycle to the SSOT as `pending_approval` (kind='cycle', Cycle AST in
        `source`). A failing cycle is refused — never stored. Re-registering an identical cycle is an
        idempotent no-op."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return JSONResponse({"error": "bad json"}, status_code=400)
        res, skeleton, err = await _cycle_draft_from_body(body)
        if err is not None:
            return err
        if not res.ok:
            return JSONResponse(
                {"ok": False, "refusal": _diag_list(res.diagnostics)}, status_code=400
            )
        # A4-V7: a cycle that binds a capability contract must CONFORM to it at register time —
        # same refusal shape as V1–V6, so the hub renders it unchanged. Registry lookup is
        # workspace-pinned; a missing target refuses (V7_UNKNOWN_CAPABILITY), never stores.
        if res.cycle is not None and res.cycle.implements is not None:
            verdict = _v7_verdict(res.cycle, skeleton)
            if not verdict.ok:
                return JSONResponse(
                    {"ok": False, "refusal": _diag_list(verdict)}, status_code=400
                )
        stored = register_cycle(store, res, authored_by=body.get("authored_by", "") or "")
        return {"ok": True, "definition": stored}

    @app.get("/cycles")
    def cycles_list(workspace: str = "") -> dict[str, Any]:
        """The latest version of every registered cycle in a workspace (kind='cycle')."""
        cycles = [a for a in store.list_automations(workspace) if a.get("kind") == "cycle"]
        return {"cycles": cycles}

    # ── Capability + Strategy registries (plan B1): same disciplines as automations ──────────
    def _capability_from_body(body: dict[str, Any]) -> tuple[Capability | None, Any]:
        """Accept either `capability` (AST object) or `text` (.capability.nil source). Returns
        (Capability, None) or (None, JSONResponse-refusal) — an invalid shape never reaches the
        registry (refused, not stored)."""
        text = body.get("text")
        if isinstance(text, str) and text:
            try:
                return parse_capability_nil(text), None
            except NilSyntaxError as exc:
                return None, JSONResponse(
                    {"error": exc.message, "line": exc.line, "col": exc.col}, status_code=400
                )
        raw = body.get("capability")
        if not isinstance(raw, dict):
            return None, JSONResponse(
                {"error": "capability (AST object) or text (.nil source) is required"},
                status_code=400,
            )
        try:
            return Capability.model_validate(raw), None
        except (ValidationError, ValueError) as exc:
            return None, JSONResponse({"error": f"invalid capability: {exc}"}, status_code=400)

    def _strategy_from_body(body: dict[str, Any]) -> tuple[Strategy | None, Any]:
        """Same dual-surface intake for strategies. A reserved form's V9_UNSUPPORTED_FORM message
        passes through verbatim — the refusal IS the answer."""
        text = body.get("text")
        if isinstance(text, str) and text:
            try:
                return parse_strategy_nil(text), None
            except NilSyntaxError as exc:
                return None, JSONResponse(
                    {"error": exc.message, "line": exc.line, "col": exc.col}, status_code=400
                )
        raw = body.get("strategy")
        if not isinstance(raw, dict):
            return None, JSONResponse(
                {"error": "strategy (AST object) or text (.nil source) is required"},
                status_code=400,
            )
        try:
            return Strategy.model_validate(raw), None
        except (ValidationError, ValueError) as exc:
            return None, JSONResponse({"error": f"invalid strategy: {exc}"}, status_code=400)

    @app.post("/capabilities")
    async def capability_register_endpoint(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Register a capability version (state=draft — publishing is a separate governed act).
        Idempotent on the same content-hash; a new hash supersedes, never edits."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        capability, cap_err = _capability_from_body(body or {})
        if cap_err is not None:
            return cap_err
        stored = store.register_capability(
            workspace=capability.workspace,
            capability_id=capability.capability_id,
            content_hash=capability_content_hash(capability),
            body=capability.model_dump(by_alias=True, mode="json"),
        )
        return {"ok": True, "definition": stored}

    @app.get("/capabilities")
    def capabilities_list(workspace: str = "") -> Any:
        """The latest version of every capability in a workspace. Workspace-pinned, fail closed:
        no workspace, no list."""
        if not workspace:
            return JSONResponse({"error": "workspace is required"}, status_code=400)
        return {"capabilities": store.list_capabilities(workspace)}

    @app.get("/capabilities/{capability_id}")
    def capability_get(
        capability_id: str, workspace: str = "", version: int | None = None
    ) -> Any:
        if not workspace:
            return JSONResponse({"error": "workspace is required"}, status_code=400)
        rec = store.get_capability(workspace, capability_id, version)
        if rec is None:
            return JSONResponse({"error": "unknown capability"}, status_code=404)
        return rec

    @app.post("/capabilities/{capability_id}/publish")
    async def capability_publish(
        capability_id: str, request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """draft -> published for one version (default: the latest). A governed act — auth-gated
        like every registry write."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        workspace = (body or {}).get("workspace") or ""
        if not workspace:
            return JSONResponse({"error": "workspace is required"}, status_code=400)
        rec = store.get_capability(workspace, capability_id, (body or {}).get("version"))
        if rec is None:
            return JSONResponse({"error": "unknown capability"}, status_code=404)
        store.set_capability_state(workspace, capability_id, rec["version"], "published")
        return {"ok": True, "definition": store.get_capability(workspace, capability_id, rec["version"])}

    @app.post("/strategies")
    async def strategy_register_endpoint(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Register a strategy version. V9 well-formedness gates admission (capability-independent
        rules — the SoD/risk rules re-run at bind time with the owning capability): a failing
        strategy is refused with the structured diagnostics, never stored."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        strategy, strat_err = _strategy_from_body(body or {})
        if strat_err is not None:
            return strat_err
        verdict = validate_strategy(strategy)
        if not verdict.ok:
            return JSONResponse(
                {"ok": False, "refusal": _diag_list(verdict)}, status_code=400
            )
        stored = store.register_strategy(
            workspace=strategy.workspace,
            strategy_id=strategy.strategy_id,
            content_hash=strategy_content_hash(strategy),
            body=strategy.model_dump(by_alias=True, mode="json"),
        )
        return {"ok": True, "definition": stored}

    @app.get("/strategies")
    def strategies_list(workspace: str = "") -> Any:
        if not workspace:
            return JSONResponse({"error": "workspace is required"}, status_code=400)
        return {"strategies": store.list_strategies(workspace)}

    @app.get("/strategies/{strategy_id}")
    def strategy_get(strategy_id: str, workspace: str = "", version: int | None = None) -> Any:
        if not workspace:
            return JSONResponse({"error": "workspace is required"}, status_code=400)
        rec = store.get_strategy(workspace, strategy_id, version)
        if rec is None:
            return JSONResponse({"error": "unknown strategy"}, status_code=404)
        return rec

    @app.post("/strategies/{strategy_id}/publish")
    async def strategy_publish(
        strategy_id: str, request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        workspace = (body or {}).get("workspace") or ""
        if not workspace:
            return JSONResponse({"error": "workspace is required"}, status_code=400)
        rec = store.get_strategy(workspace, strategy_id, (body or {}).get("version"))
        if rec is None:
            return JSONResponse({"error": "unknown strategy"}, status_code=404)
        store.set_strategy_state(workspace, strategy_id, rec["version"], "published")
        return {"ok": True, "definition": store.get_strategy(workspace, strategy_id, rec["version"])}

    # ── Auto-wrap (plan B8): every registered cycle gets a v0 capability ─────────────────────
    @app.post("/capabilities/wrap")
    async def capability_wrap_endpoint(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Derive + register the v0 capability (and its owner-approval strategy) for a registered
        cycle. Risk comes from the live adapter's DECLARED verb metadata; with no reachable
        adapter every verb is undeclared and the floor is HIGH (fail closed, never guess).
        Deterministic: re-wrapping an unchanged cycle is a same-hash idempotent no-op."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        workspace = (body or {}).get("workspace") or ""
        cycle_id = (body or {}).get("cycle_id") or ""
        if not workspace or not cycle_id:
            return JSONResponse(
                {"error": "workspace and cycle_id are required"}, status_code=400
            )
        row = store.get_automation(workspace, cycle_slug(cycle_id))
        if row is None or row.get("kind") != "cycle" or not row.get("source"):
            return JSONResponse({"error": "unknown cycle"}, status_code=404)
        try:
            cycle = Cycle.model_validate(row["source"])
        except (ValidationError, ValueError) as exc:
            return JSONResponse({"error": f"stored cycle is invalid: {exc}"}, status_code=400)
        skeleton = await provider(workspace)
        details: dict[str, dict[str, Any]] = {
            d["verb"]: d
            for d in (skeleton or {}).get("verb_details", [])
            if isinstance(d, dict) and d.get("verb")
        }
        try:
            wrapped = wrap_cycle(cycle, details.get)
        except (ValidationError, ValueError) as exc:
            return JSONResponse({"error": f"cycle cannot be wrapped: {exc}"}, status_code=400)
        strategy_row = store.register_strategy(
            workspace=workspace,
            strategy_id=wrapped.strategy.strategy_id,
            content_hash=strategy_content_hash(wrapped.strategy),
            body=wrapped.strategy.model_dump(by_alias=True, mode="json"),
        )
        capability_row = store.register_capability(
            workspace=workspace,
            capability_id=wrapped.capability.capability_id,
            content_hash=capability_content_hash(wrapped.capability),
            body=wrapped.capability.model_dump(by_alias=True, mode="json"),
        )
        return {"ok": True, "capability": capability_row, "strategy": strategy_row}

    # ── Prepared executions (plans B2+B3): prepare → sign(strategy) → commit ──────────────────
    def _prepared_refusal(refusal: dict[str, Any], status_code: int = 409, **extra: Any) -> Any:
        return JSONResponse({"ok": False, "refusal": refusal, **extra}, status_code=status_code)

    def _prepared_strategy_body(row: dict[str, Any]) -> dict[str, Any]:
        rec = store.get_strategy(row["workspace"], row["strategy_id"], row["strategy_version"])
        return (rec or {}).get("body") or {}

    async def _commit_prepared(row: dict[str, Any]) -> dict[str, Any]:
        """A FULLY APPROVED prepared execution commits by firing the capability's default
        implementing cycle with the seeded inputs bound as $.input — the ONLY effect path.
        Honest on failure (cycle not registered/armed, runner blow-up): the row stays
        'approved' with the error recorded, retryable via /execute."""
        cap = (
            store.get_capability(
                row["workspace"], row["capability_id"], row["capability_version"]
            )
            or {}
        )
        cycle_id = ((cap.get("body") or {}).get("implemented_by") or {}).get("default") or ""
        if not cycle_id:
            result: dict[str, Any] = {
                "committed": False,
                "error": "capability has no default implementation to commit through",
            }
        else:
            fired = await fire_manual(
                store,
                workspace=row["workspace"],
                automation_id=cycle_slug(cycle_id),
                idempotency_key=f"prep:{row['prepared_id']}",
                runner=run_exec,
                fired_by=f"prepared:{row['prepared_id']}",
                input=row["inputs"] or None,
            )
            run = fired.get("run") or {}
            result = {
                "committed": bool(fired.get("ok")),
                "run_id": run.get("run_id"),
                "replayed": bool(fired.get("replayed")),
                "error": fired.get("error"),
            }
        store.record_prepared_commit(
            row["prepared_id"], result, "committed" if result["committed"] else "approved"
        )
        return result

    async def _execute_prepared_core(row: dict[str, Any]) -> dict[str, Any]:
        """The ONE execute path — shared by POST /prepared/{id}/execute and the tick's scheduled
        fires, so a scheduled commit obeys exactly the rules a manual commit does. Returns
        {"execution": ...} or {"refusal": ...} — the interpreter state is the authority, never a
        stored flag; an unsatisfied strategy refuses NOT_APPROVED (collecting signatures is the
        only way forward)."""
        if row["status"] == "committed":
            return {
                "refusal": {
                    "code": "ALREADY_COMMITTED",
                    "message": "this prepared execution already committed",
                    "commit_result": row.get("commit_result"),
                }
            }
        if row["status"] == "rejected":
            return {
                "refusal": {
                    "code": "ALREADY_DECIDED",
                    "message": "this prepared execution was rejected",
                }
            }
        if row["status"] == "pending":
            st = strategy_exec.state(
                store, row["prepared_id"], _prepared_strategy_body(row), inputs=row["inputs"]
            )
            if st.get("status") != "approved":
                return {
                    "refusal": {
                        "code": "NOT_APPROVED",
                        "message": "the strategy is not satisfied — collect the pending "
                        "signatures first (the commit is the only effect path)",
                        "pending": st.get("pending"),
                    }
                }
            store.set_prepared_status(row["prepared_id"], "approved", expect="pending")
        refreshed = store.get_prepared(row["prepared_id"], row["workspace"]) or row
        return {"execution": await _commit_prepared(refreshed)}

    @app.post("/prepared")
    async def prepared_create(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Prepare one capability invocation: validate the inputs against the typed contract,
        pin the registry versions, stamp the preparer (SoD), and hold the strategy's first
        stage. Returns the deterministic Permission Card. NO effect fires here."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        body = body or {}
        out = prepared_cards.prepare(
            store,
            workspace=body.get("workspace") or "",
            capability_id=body.get("capability_id") or "",
            inputs=body.get("inputs") if isinstance(body.get("inputs"), dict) else {},
            prepared_by=body.get("prepared_by") or "",
            version=body.get("version"),
        )
        if "refusal" in out:
            return _prepared_refusal(out["refusal"], status_code=400)
        return out

    @app.get("/prepared")
    def prepared_list(workspace: str = "", status: str = "") -> Any:
        """The workspace's Permission Cards, newest first — the Decisions feed. Workspace-pinned,
        fail closed; optional ?status= filter."""
        if not workspace:
            return JSONResponse({"error": "workspace is required"}, status_code=400)
        rows = store.list_prepared(workspace, status=status or None)
        return {"prepared": [prepared_cards.card_view(store, r) for r in rows]}

    @app.get("/prepared/{prepared_id}")
    def prepared_get(prepared_id: str, workspace: str = "") -> Any:
        """The Permission Card. Workspace-pinned, fail closed: another tenant's prepared_id
        is a 404 here, and no workspace means no card."""
        if not workspace:
            return JSONResponse({"error": "workspace is required"}, status_code=400)
        row = store.get_prepared(prepared_id, workspace)
        if row is None:
            return JSONResponse({"error": "unknown prepared execution"}, status_code=404)
        return prepared_cards.card_view(store, row)

    @app.post("/prepared/{prepared_id}/sign")
    async def prepared_sign(
        prepared_id: str, request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """One unit's decision on the card — the strategy-aware decision surface. SoD refusals
        (the preparer, distinct_from) come back as answers with code SOD_VIOLATION; an
        approve-with-edits inside `modifiable` VOIDS previously collected signatures
        (superseded) and re-holds the affected units before this signature lands; on the
        strategy's full approval the commit fires — the ONLY effect path."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        body = body or {}
        ws = body.get("workspace") or ""
        if not ws:
            return JSONResponse({"error": "workspace is required"}, status_code=400)
        decision = body.get("status")
        if decision not in ("approved", "rejected"):
            return JSONResponse(
                {"error": "status must be 'approved' or 'rejected'"}, status_code=400
            )
        row = store.get_prepared(prepared_id, ws)
        if row is None:
            return JSONResponse({"error": "unknown prepared execution"}, status_code=404)
        if row["status"] != "pending":
            return _prepared_refusal(
                {
                    "code": "ALREADY_DECIDED",
                    "message": f"this prepared execution is already {row['status']}",
                    "status": row["status"],
                }
            )
        actor = body.get("actor") or ""
        # SoD is checked BEFORE the edits path too — otherwise the preparer could void
        # everyone's signatures with an edit they are not even allowed to sign.
        if actor and actor == row["prepared_by"]:
            return _prepared_refusal(
                {
                    "code": "SOD_VIOLATION",
                    "message": f"{actor!r} prepared this card and cannot sign it "
                    "(preparer-not-approver, invariant I6)",
                    "actor": actor,
                },
                status_code=403,
            )
        strat_body = _prepared_strategy_body(row)
        superseded = 0
        edits = body.get("edits") if isinstance(body.get("edits"), dict) else None
        if decision == "approved" and edits:
            material = {k: v for k, v in edits.items() if row["inputs"].get(k) != v}
            if material:
                locked = sorted(k for k in material if k not in row["modifiable"])
                if locked:
                    return _prepared_refusal(
                        {
                            "code": "FIELD_NOT_MODIFIABLE",
                            "message": "these fields are locked on this card — edits are "
                            "lawful only inside `modifiable`",
                            "fields": locked,
                        }
                    )
                new_inputs = {**row["inputs"], **material}
                cap = (
                    store.get_capability(ws, row["capability_id"], row["capability_version"])
                    or {}
                )
                contract = prepared_cards.validate_inputs(cap.get("body") or {}, new_inputs)
                if contract is not None:
                    return _prepared_refusal(contract, status_code=400)
                held = strategy_exec.rehold(
                    store, prepared_id, strat_body, inputs=new_inputs,
                    risk=row["risk"], workspace=ws,
                )
                if "refusal" in held:
                    return _prepared_refusal(held["refusal"], status_code=400)
                store.update_prepared_inputs(prepared_id, new_inputs, branch=held.get("branch"))
                row = store.get_prepared(prepared_id, ws) or row
                superseded = int(held.get("superseded") or 0)
                if held["status"] == "approved":  # the edit re-routed onto an auto branch
                    store.set_prepared_status(prepared_id, "approved", expect="pending")
                    execution = await _commit_prepared(store.get_prepared(prepared_id, ws) or row)
                    return {
                        "ok": True, "status": "approved", "superseded": superseded,
                        "execution": execution,
                        "prepared": prepared_cards.card_view(
                            store, store.get_prepared(prepared_id, ws) or row
                        ),
                    }
        signed = strategy_exec.sign(
            store, prepared_id, strat_body, inputs=row["inputs"], actor=actor,
            role=body.get("role"), decision=decision, prepared_by=row["prepared_by"],
        )
        if "refusal" in signed:
            code = (signed["refusal"] or {}).get("code")
            return _prepared_refusal(
                signed["refusal"],
                status_code=403 if code == "SOD_VIOLATION" else 409,
                superseded=superseded,
            )
        result: dict[str, Any] = {"ok": True, "status": signed["status"], "superseded": superseded}
        if signed["status"] == "rejected":
            store.set_prepared_status(
                prepared_id, "rejected", expect="pending", reason=body.get("reason", "")
            )
        elif signed["status"] == "approved":
            store.set_prepared_status(prepared_id, "approved", expect="pending")
            result["execution"] = await _commit_prepared(store.get_prepared(prepared_id, ws) or row)
        result["prepared"] = prepared_cards.card_view(
            store, store.get_prepared(prepared_id, ws) or row
        )
        return result

    @app.post("/prepared/{prepared_id}/execute")
    async def prepared_execute(
        prepared_id: str, request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Commit a FULLY APPROVED prepared execution (the auto/complete path, or a retry after
        a failed commit). A pending strategy refuses with its pending units — collecting
        signatures is the only way forward."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        ws = (body or {}).get("workspace") or ""
        if not ws:
            return JSONResponse({"error": "workspace is required"}, status_code=400)
        row = store.get_prepared(prepared_id, ws)
        if row is None:
            return JSONResponse({"error": "unknown prepared execution"}, status_code=404)
        out = await _execute_prepared_core(row)
        if "refusal" in out:
            return _prepared_refusal(out["refusal"])
        return {
            "ok": bool(out["execution"].get("committed")),
            "execution": out["execution"],
            "prepared": prepared_cards.card_view(
                store, store.get_prepared(prepared_id, ws) or row
            ),
        }

    @app.post("/prepared/{prepared_id}/schedule")
    async def prepared_schedule(
        prepared_id: str, request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """B7 nil_schedule: register a ONE-SHOT schedule row for a pending/approved prepared
        execution. The /automations/tick sweep fires it through the SAME execute path a manual
        commit uses at/after `when` (ISO-8601) — a row, never an in-memory timer. Honest
        refusals: unknown/decided cards, unparseable timestamps, and timestamps already past."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        ws = (body or {}).get("workspace") or ""
        if not ws:
            return JSONResponse({"error": "workspace is required"}, status_code=400)
        row = store.get_prepared(prepared_id, ws)
        if row is None:
            return JSONResponse({"error": "unknown prepared execution"}, status_code=404)
        if row["status"] not in ("pending", "approved"):
            return _prepared_refusal(
                {
                    "code": "ALREADY_COMMITTED"
                    if row["status"] == "committed"
                    else "ALREADY_DECIDED",
                    "message": f"this prepared execution is already {row['status']} — only a "
                    "pending or approved card can be scheduled",
                    "status": row["status"],
                }
            )
        fire_at = _parse_when((body or {}).get("when"))
        if fire_at is None:
            return _prepared_refusal(
                {
                    "code": "INVALID_WHEN",
                    "message": "`when` must be an ISO-8601 timestamp (e.g. "
                    "2026-07-04T09:00:00Z)",
                },
                status_code=400,
            )
        now = _dt.datetime.now(_dt.UTC)
        if fire_at <= now:
            return _prepared_refusal(
                {
                    "code": "PAST_SCHEDULE",
                    "message": "`when` is not in the future — a one-shot schedule fires at/after "
                    "`when`; a past timestamp is refused, never fired retroactively",
                    "when": fire_at.isoformat(),
                    "now": now.isoformat(),
                },
                status_code=400,
            )
        sched = store.create_scheduled_execution(
            f"sched-{uuid.uuid4().hex[:12]}",
            prepared_id=prepared_id,
            workspace=ws,
            fire_at=fire_at.isoformat(),
        )
        return {"ok": True, "scheduled": sched}

    # ── Cycle .nil surface + language services (the LSP brain — a projection, no state) ────────
    async def _read_body(request: Request) -> tuple[dict[str, Any] | None, Any]:
        try:
            return await request.json(), None
        except (ValueError, TypeError):
            return None, JSONResponse({"error": "bad json"}, status_code=400)

    async def _lsp_ctx(workspace: str | None) -> ValidationContext | None:
        """Build a verb-catalog context from the workspace's live skeleton, or None when no workspace
        is given or no reachable active adapter answers (the LSP then skips V4/V5 verb checks)."""
        if not workspace:
            return None
        skeleton = await provider(workspace)
        if skeleton is None:
            return None
        return context_from_skeleton(workspace, skeleton)

    @app.post("/cycles/parse")
    async def cycle_parse_endpoint(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """`.nil` text → the validated Cycle AST, or a structured `{message, line, col}` syntax error."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        text = (body or {}).get("text", "")
        try:
            cycle = parse_nil(text)
        except NilSyntaxError as exc:
            return {
                "ok": False,
                "error": {"message": exc.message, "line": exc.line, "col": exc.col},
            }
        return {"ok": True, "cycle": cycle.model_dump(by_alias=True, mode="json")}

    @app.post("/cycles/print")
    async def cycle_print_endpoint(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """A Cycle AST → its canonical `.nil` text. 400 on a malformed cycle."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        try:
            cycle = Cycle.model_validate((body or {}).get("cycle"))
        except (ValidationError, ValueError) as exc:
            return JSONResponse({"error": f"malformed cycle: {exc}"}, status_code=400)
        return {"ok": True, "text": print_nil(cycle)}

    @app.post("/cycles/lsp/diagnostics")
    async def cycle_lsp_diagnostics(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Live diagnostics for `.nil` text. With a reachable `workspace` the verbs are validated
        (V4/V5); without one the verb checks are skipped (an info diag says so)."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        body = body or {}
        ctx = await _lsp_ctx(body.get("workspace"))
        return {"diagnostics": lsp_diagnostics(body.get("text", ""), ctx)}

    @app.post("/cycles/lsp/completions")
    async def cycle_lsp_completions(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Context-aware completions at (line, col) in `.nil` text."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        body = body or {}
        ctx = await _lsp_ctx(body.get("workspace"))
        items = lsp_completions(
            body.get("text", ""), int(body.get("line", 1)), int(body.get("col", 1)), ctx
        )
        return {"completions": items}

    @app.post("/cycles/lsp/hover")
    async def cycle_lsp_hover(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Hover detail for the identifier under the cursor (may be null)."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        body = body or {}
        ctx = await _lsp_ctx(body.get("workspace"))
        info = lsp_hover(
            body.get("text", ""), int(body.get("line", 1)), int(body.get("col", 1)), ctx
        )
        return {"hover": info}

    @app.post("/cycles/lsp/semantic-tokens")
    async def cycle_lsp_semantic_tokens(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Deterministic token classification for syntax highlighting."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        return {"tokens": lsp_semantic_tokens((body or {}).get("text", ""))}

    @app.post("/cycles/projections")
    async def cycle_projections_endpoint(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """A read-only projection of a Cycle AST: a mermaid diagram, markdown docs, a happy-path
        simulation, or the governance trust summary."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        body = body or {}
        kind = body.get("kind")
        projections = {
            "mermaid": to_mermaid,
            "markdown": to_markdown,
            "simulate": simulate,
            "governance": governance_report,
        }
        fn = projections.get(kind)
        if fn is None:
            return JSONResponse(
                {"error": f"unknown projection kind {kind!r}"}, status_code=400
            )
        try:
            cycle = Cycle.model_validate(body.get("cycle"))
        except (ValidationError, ValueError) as exc:
            return JSONResponse({"error": f"malformed cycle: {exc}"}, status_code=400)
        return {"result": fn(cycle)}

    # ── cross-system composed automations (P3) ──────────────────────────────────────────────
    async def _validate_composed_body(body: dict[str, Any]) -> tuple[Any, Any]:
        """Validate a composed-plan request: each stage against ITS adapter's live skeleton + handoff
        well-formedness + a valid trigger. Returns ((composed_raw, report), None) or (None, error)."""
        composed = body.get("composed")
        aid, name, trigger = (
            body.get("automation_id"),
            body.get("name"),
            body.get("trigger"),
        )
        if not isinstance(composed, dict) or not aid or name is None or trigger is None:
            return None, JSONResponse(
                {"error": "automation_id, name, composed, trigger are required"},
                status_code=400,
            )
        ws = composed.get("workspace")
        if not ws:
            return None, JSONResponse(
                {"error": "composed.workspace is required"}, status_code=400
            )
        try:
            parse_trigger(trigger)
        except (ValidationError, ValueError, TypeError) as exc:
            return None, JSONResponse({"error": f"bad trigger: {exc}"}, status_code=400)
        stages = composed.get("stages") or []
        adapter_ids = {s.get("adapter") for s in stages if isinstance(s, dict)}
        skeletons: dict[str, Any] = {}
        for adapter_id in adapter_ids:
            skeleton = await adapter_skeletons(ws, adapter_id)
            if skeleton is None:
                return None, JSONResponse(
                    {
                        "error": f"no reachable adapter {adapter_id!r} in workspace {ws!r}"
                    },
                    status_code=503,
                )
            skeletons[adapter_id] = skeleton
        try:
            parsed = parse_composed(composed)
        except (KeyError, TypeError) as exc:
            return None, JSONResponse(
                {"error": f"malformed composed plan: {exc}"}, status_code=400
            )
        return (composed, validate_composed(parsed, skeletons)), None

    @app.post("/automations/compose/draft")
    async def compose_draft(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Preview: validate a cross-system composed plan, each stage against its adapter. No effect."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return JSONResponse({"error": "bad json"}, status_code=400)
        res, err = await _validate_composed_body(body)
        if err is not None:
            return err
        composed, report = res
        if not report["ok"]:
            return {"ok": False, "report": report}
        return {"ok": True, "content_hash": composed_hash(composed), "report": report}

    @app.post("/automations/compose/register")
    async def compose_register(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Persist a passing composed plan as `pending_approval` (kind='composed')."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return JSONResponse({"error": "bad json"}, status_code=400)
        res, err = await _validate_composed_body(body)
        if err is not None:
            return err
        composed, report = res
        if not report["ok"]:
            return JSONResponse({"ok": False, "report": report}, status_code=400)
        stored = store.register_automation(
            workspace=composed["workspace"],
            automation_id=body["automation_id"],
            content_hash=composed_hash(composed),
            name=body["name"],
            plan=composed,
            trigger=body["trigger"],
            state="pending_approval",
            kind="composed",
            authored_by=body.get("authored_by", "") or "",
            description=body.get("description"),
        )
        return {"ok": True, "definition": stored}

    @app.get("/automations")
    def automations_list(workspace: str = "") -> dict[str, Any]:
        """Latest version of every automation in a workspace (public read — no secrets in the record)."""
        return {"automations": store.list_automations(workspace)}

    @app.get("/automations/{workspace}/{automation_id}")
    def automation_get(
        workspace: str, automation_id: str, version: int | None = None
    ) -> Any:
        a = store.get_automation(workspace, automation_id, version)
        if a is None:
            return JSONResponse({"error": "no such automation"}, status_code=404)
        return a

    @app.post("/automations/{workspace}/{automation_id}/{version}/state")
    async def automation_set_state(
        workspace: str,
        automation_id: str,
        version: int,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> Any:
        """Arm/disarm/approve an automation (operator-gated). Approving (→ active) records the owner.
        Arming a recurring automation is a governance act, so it sits behind the registry token."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return JSONResponse({"error": "bad json"}, status_code=400)
        state = body.get("state")
        if state not in ("pending_approval", "active", "paused", "archived"):
            return JSONResponse(
                {"error": "state must be pending_approval|active|paused|archived"},
                status_code=400,
            )
        ok = store.set_automation_state(
            workspace,
            automation_id,
            version,
            state,
            approved_by=body.get("approved_by"),
        )
        if not ok:
            return JSONResponse(
                {"error": "no such automation version"}, status_code=404
            )
        return {
            "ok": True,
            "automation": store.get_automation(workspace, automation_id, version),
        }

    @app.post("/automations/{workspace}/{automation_id}/run")
    async def automation_run(
        workspace: str,
        automation_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> Any:
        """Fire the active automation now (manual trigger). Requires an `idempotency_key` so a
        re-delivered fire replays the same run rather than executing twice. Operator-gated."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = {}
        idem = body.get("idempotency_key")
        if not idem or len(str(idem)) < 6:
            return JSONResponse(
                {"error": "idempotency_key (>= 6 chars) is required"}, status_code=400
            )
        fired_by = body.get("fired_by", "manual") or "manual"
        auto = store.get_automation(workspace, automation_id)
        if auto is not None and auto.get("kind") == "composed":
            out = await fire_composed(
                store,
                workspace=workspace,
                automation_id=automation_id,
                idempotency_key=str(idem),
                stage_runner=stage_exec,
                fired_by=fired_by,
            )
        else:
            out = await fire_manual(
                store,
                workspace=workspace,
                automation_id=automation_id,
                idempotency_key=str(idem),
                runner=run_exec,
                fired_by=fired_by,
            )
        if not out.get("ok"):
            return JSONResponse(out, status_code=out.pop("status", 400))
        return out

    @app.post("/automations/tick")
    async def automations_tick(authorization: str | None = Header(default=None)) -> Any:
        """Fire interval-scheduled automations that are due. Called by an external clock (cron /
        Temporal Schedule) — the control plane decides *which* are due; the caller owns the tick.
        Operator-gated."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        now = _dt.datetime.now(_dt.UTC)
        fired = await run_due_schedules(store, runner=run_exec, now=now)
        # The same clock resumes parked runs whose deadline passed (await_approval → on_timeout,
        # wait_for_event → its timeout route) — deadlines are rows, so restarts lose nothing.
        timed_out = await resume_due_waits(store, runner=run_exec, now=now)
        # And strategy unit deadlines (plan B3): escalate re-addresses a fresh signature slot;
        # reject rejects the whole prepared subject — same clock, same sweep discipline.
        signature_actions = strategy_exec.sweep_due(store, now=now)
        for act in signature_actions:
            if act.get("action") == "rejected":
                store.set_prepared_status(act["execution_id"], "rejected", expect="pending")
        # And one-shot scheduled executions (plan B7 nil_schedule): each due row fires through
        # the SAME execute path a manual commit uses; the outcome (fired | refused) is settled
        # on the row — a NOT_APPROVED strategy at fire time is a recorded answer, never a retry.
        scheduled_fires: list[dict[str, Any]] = []
        for sched in store.due_scheduled_executions(now.isoformat()):
            prep_row = store.get_prepared(sched["prepared_id"], sched["workspace"])
            if prep_row is None:
                outcome: dict[str, Any] = {
                    "refusal": {
                        "code": "UNKNOWN_PREPARED",
                        "message": "the scheduled prepared execution no longer exists",
                    }
                }
            else:
                outcome = await _execute_prepared_core(prep_row)
            fire: dict[str, Any] = {
                "schedule_id": sched["schedule_id"],
                "prepared_id": sched["prepared_id"],
            }
            if "refusal" in outcome:
                if store.settle_scheduled_execution(
                    sched["schedule_id"], "refused", outcome["refusal"]
                ):
                    fire.update(status="refused", refusal=outcome["refusal"])
                    scheduled_fires.append(fire)
            else:
                if store.settle_scheduled_execution(
                    sched["schedule_id"], "fired", outcome["execution"]
                ):
                    fire.update(status="fired", execution=outcome["execution"])
                    scheduled_fires.append(fire)
        return {
            "ok": True,
            "fired": len(fired),
            "runs": [f["run"] for f in fired if f.get("ok") and f.get("run")],
            "timed_out": timed_out,
            "signatures": signature_actions,
            "scheduled": scheduled_fires,
        }

    @app.get("/automations/{workspace}/{automation_id}/runs")
    def automation_runs(
        workspace: str, automation_id: str, limit: int = 50
    ) -> dict[str, Any]:
        """Newest-first run history for one automation (trace omitted — fetch via /runs/{run_id})."""
        return {"runs": store.list_runs(workspace, automation_id, limit)}

    @app.get("/runs/{run_id}")
    def run_detail(run_id: str) -> Any:
        run = store.get_run(run_id)
        if run is None:
            return JSONResponse({"error": "no such run"}, status_code=404)
        return run

    @app.post("/runs/{run_id}/rollback")
    async def run_rollback(
        run_id: str, request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """B5: per-phase rollback. Builds the REVERSE compensation chain of every write COMMITTED
        after `to_checkpoint` (each step's own `compensate_with` — the same declared inverse the
        kernel's saga unwind executes) and holds it as ONE governed proposal (`rb:{run}:{name}`).
        NO effect fires here: the human approves the plan via the normal decision endpoint, and
        THAT approval commits the compensations in reverse order with `rb-{run_id}-{n}` keys.
        A committed write in the segment with no compensation refuses honestly
        (IRREVERSIBLE_SEGMENT, listing the blocking steps) — never a partial pretend-reversal."""
        if not _registry_authed(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body, err = await _read_body(request)
        if err is not None:
            return err
        body = body or {}
        to_checkpoint = body.get("to_checkpoint") or ""
        if not to_checkpoint:
            return JSONResponse({"error": "to_checkpoint is required"}, status_code=400)
        run = store.get_run(run_id)
        if run is None:
            return JSONResponse({"error": "no such run"}, status_code=404)
        ws = body.get("workspace") or ""
        if ws and (run.get("workspace") or "") != ws:
            # Workspace-pinned, fail closed: another tenant's run id is indistinguishable from a
            # missing one.
            return JSONResponse({"error": "no such run"}, status_code=404)
        marker = store.get_checkpoint(run_id, to_checkpoint)
        if marker is None:
            return JSONResponse(
                {
                    "ok": False,
                    "refusal": {
                        "code": "UNKNOWN_CHECKPOINT",
                        "message": f"run {run_id!r} walked no checkpoint {to_checkpoint!r}",
                    },
                },
                status_code=404,
            )
        auto = store.get_automation(
            run.get("workspace") or "", run.get("automation_id") or "", run.get("version")
        )
        if auto is None or not isinstance(auto.get("plan"), dict):
            return JSONResponse(
                {"error": "the run's pinned automation version is gone"}, status_code=409
            )
        nodes = node_map(auto["plan"])
        context = (run.get("trace") or {}).get("context") or {}
        # Committed writes, in the plan's deterministic (pipeline) order, replaying the kernel's
        # own committed-output judgement over the persisted trace.
        committed_now = [
            node["id"]
            for node in auto["plan"]["pipeline"]
            if node.get("type") == "action"
            and looks_committed((context.get(node["id"]) or {}).get("output"))
        ]
        segment = [nid for nid in committed_now if nid not in set(marker["committed"])]
        blocking = [nid for nid in segment if not nodes[nid].get("compensate_with")]
        if blocking:
            return JSONResponse(
                {
                    "ok": False,
                    "refusal": {
                        "code": "IRREVERSIBLE_SEGMENT",
                        "message": "committed write step(s) after the checkpoint declare no "
                        "compensation — the segment cannot be honestly reversed",
                        "blocking_steps": blocking,
                    },
                },
                status_code=409,
            )
        steps: list[dict[str, Any]] = []
        for n, nid in enumerate(reversed(segment)):
            comp = nodes[nid]["compensate_with"]
            steps.append(
                {
                    "seq": n,
                    "node": nid,
                    "verb": comp["verb"],
                    # References ($.step_N.output.*) resolve NOW against the persisted run trace,
                    # so the held plan carries literal args the owner can actually read.
                    "args": resolve_references(comp.get("args") or {}, context, item=None),
                    "idempotency_key": f"rb-{run_id}-{n}",
                }
            )
        plan_view = {
            "run_id": run_id,
            "to_checkpoint": to_checkpoint,
            "workspace": run.get("workspace") or "",
            "steps": steps,
        }
        proposal_id = f"rb:{run_id}:{to_checkpoint}"
        held = store.await_approval(
            proposal_id,
            verb="run.rollback",
            tier="HIGH",  # reversing committed effects is always a human decision
            preview={"kind": "rollback", **plan_view},
            workspace=run.get("workspace") or "",
            resolved=plan_view,
        )
        return {
            "ok": True,
            "proposal_id": proposal_id,
            "status": held.get("status"),
            "rollback": plan_view,
        }

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _INDEX_HTML

    return app


_INDEX_HTML = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>nilscript · control plane</title>
<script>(function(){try{var t=localStorage.getItem('cp-theme')||(window.matchMedia&&matchMedia('(prefers-color-scheme:light)').matches?'light':'dark');document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','dark');}})();</script>
<style>
  :root{
    --blue:#5b8cff;--green:#46c266;--amber:#e0a629;--red:#fb5a4e;--violet:#a877f7;
    --radius:14px;--mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
  }
  :root,:root[data-theme=dark]{
    --bg:#090b0f;--panel:#0f131a;--elev:#141a23;--line:#1d2530;--line2:#283142;
    --fg:#e7eaf0;--mut:#8b94a6;--faint:#5a6373;
    --header-bg:rgba(9,11,15,.82);--verb:#9ec5ff;--verb-strong:#cfe0ff;--rowhover:rgba(91,140,255,.05)}
  :root[data-theme=light]{
    --bg:#f5f7fa;--panel:#ffffff;--elev:#eef1f5;--line:#e4e8ee;--line2:#d6dde6;
    --fg:#1b2230;--mut:#586374;--faint:#97a1b1;
    --blue:#2f6bff;--green:#1f9e44;--amber:#a9760f;--red:#db3a2f;--violet:#7a45d3;
    --header-bg:rgba(255,255,255,.85);--verb:#2f5bd0;--verb-strong:#2247b8;--rowhover:rgba(47,107,255,.06)}
  @media(prefers-color-scheme:light){:root:not([data-theme]){
    --bg:#f5f7fa;--panel:#ffffff;--elev:#eef1f5;--line:#e4e8ee;--line2:#d6dde6;
    --fg:#1b2230;--mut:#586374;--faint:#97a1b1;
    --blue:#2f6bff;--green:#1f9e44;--amber:#a9760f;--red:#db3a2f;--violet:#7a45d3;
    --header-bg:rgba(255,255,255,.85);--verb:#2f5bd0;--verb-strong:#2247b8;--rowhover:rgba(47,107,255,.06)}}
  *{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  body{margin:0;background:
      radial-gradient(1200px 600px at 80% -10%,rgba(91,140,255,.10),transparent 60%),
      radial-gradient(900px 500px at -10% 0%,rgba(168,119,247,.08),transparent 55%),var(--bg);
    color:var(--fg);font:14px/1.55 var(--mono);min-height:100vh;
    -webkit-font-smoothing:antialiased}
  a{color:inherit}

  /* ── header ── */
  header{position:sticky;top:0;z-index:20;backdrop-filter:blur(10px);
    background:var(--header-bg);
    border-bottom:1px solid var(--line);padding:14px clamp(14px,4vw,30px);
    display:flex;align-items:center;gap:14px;flex-wrap:wrap}
  .brand{display:flex;align-items:center;gap:10px;font-weight:600;letter-spacing:.02em}
  .brand b{font-weight:600}.brand .sl{color:var(--faint);font-weight:400}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--green);
    box-shadow:0 0 0 0 rgba(70,194,102,.6);animation:pulse 2.4s infinite}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(70,194,102,.55)}70%{box-shadow:0 0 0 7px rgba(70,194,102,0)}100%{box-shadow:0 0 0 0 rgba(70,194,102,0)}}
  .grow{flex:1 1 auto}
  .chip{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;border:1px solid var(--line2);
    border-radius:999px;color:var(--mut);font-size:12px;white-space:nowrap}
  .chip b{color:var(--fg)}
  .live{color:var(--faint);font-size:12px;display:inline-flex;align-items:center;gap:6px}
  .live i{width:5px;height:5px;border-radius:50%;background:var(--green);display:inline-block}

  main{padding:clamp(14px,3vw,26px);max-width:1280px;margin:0 auto}
  .sec-title{display:flex;align-items:center;gap:9px;margin:6px 2px 12px;
    color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.09em}
  .sec-title .n{color:var(--fg);background:var(--elev);border:1px solid var(--line2);
    border-radius:999px;padding:1px 8px;font-size:11px}

  /* ── pending approvals ── */
  #pendingWrap{margin-bottom:26px;display:none}
  #pending{display:grid;gap:12px}
  .pcard{position:relative;border:1px solid var(--line2);border-radius:var(--radius);
    background:linear-gradient(180deg,rgba(224,166,41,.10),rgba(224,166,41,.02)),var(--panel);
    padding:16px 18px;display:flex;gap:16px;align-items:center;flex-wrap:wrap;
    box-shadow:0 1px 0 rgba(255,255,255,.02) inset,0 10px 30px -18px rgba(0,0,0,.8)}
  .pcard::before{content:"";position:absolute;left:0;top:14px;bottom:14px;width:3px;border-radius:3px;background:var(--amber)}
  .pcard .body{flex:1 1 260px;min-width:0}
  .pcard .verb{font-size:15px;font-weight:600;color:var(--verb-strong);word-break:break-word}
  .pcard .prev{color:var(--mut);font-size:13px;margin-top:3px;word-break:break-word}
  .pcard .meta{color:var(--faint);font-size:11.5px;margin-top:6px}
  .pcard .actions{display:flex;gap:9px;flex:0 0 auto}

  .btn{appearance:none;font:inherit;font-size:13px;cursor:pointer;border-radius:10px;
    padding:9px 16px;border:1px solid var(--line2);background:var(--elev);color:var(--fg);
    transition:transform .06s ease,filter .15s ease,background .15s ease;display:inline-flex;
    align-items:center;gap:7px;white-space:nowrap}
  .btn:hover{filter:brightness(1.15)}.btn:active{transform:translateY(1px)}
  .btn.ok{border-color:rgba(70,194,102,.5);color:#bdf0cb;background:rgba(70,194,102,.12)}
  .btn.no{border-color:rgba(251,90,78,.5);color:#ffc7c2;background:rgba(251,90,78,.10)}
  .btn.ghost{background:transparent;color:var(--mut)}
  .btn.ghost:hover{color:var(--fg);border-color:var(--line2)}
  .btn.tiny{padding:5px 10px;font-size:12px;border-radius:8px}

  /* ── timeline (responsive: table on desktop, cards on mobile) ── */
  .feed{border:1px solid var(--line);border-radius:var(--radius);overflow-x:auto;background:var(--panel)}
  .feed-head,.row{display:grid;grid-template-columns:74px 76px 104px 96px minmax(140px,1.3fr) 72px 104px minmax(72px,.9fr) 100px;
    align-items:center;gap:12px;padding:8px clamp(12px,2vw,16px);min-width:880px}
  .feed-head{color:var(--faint);font-size:11px;text-transform:uppercase;letter-spacing:.08em;
    border-bottom:1px solid var(--line);background:var(--elev)}
  .row{border-bottom:1px solid var(--line);transition:background .12s ease;cursor:pointer}
  .row:last-child{border-bottom:none}
  .row:hover{background:var(--rowhover)}
  .row.sel{background:var(--rowhover)}
  .row .caret{color:var(--faint);transition:transform .15s ease;display:inline-block}
  .row.sel .caret{transform:rotate(90deg);color:var(--verb)}
  .t{color:var(--faint)} .src{color:var(--mut)} .ws{color:var(--faint)}
  .verbcell{color:var(--verb);font-weight:500;word-break:break-word}
  .vdetail{display:block;color:var(--faint);font-weight:400;font-size:11px;margin-top:2px;word-break:break-word}
  .vdetail b{color:var(--mut);font-weight:500}
  .pid{color:var(--faint);font-size:12px}
  .ev{justify-self:start}
  .pill{display:inline-flex;align-items:center;gap:6px;padding:2px 10px;border-radius:999px;
    font-size:12px;border:1px solid var(--line2);white-space:nowrap}
  .pill::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;opacity:.9}
  .ev-executed{color:var(--green);border-color:rgba(70,194,102,.35);background:rgba(70,194,102,.08)}
  .ev-proposed{color:var(--blue);border-color:rgba(91,140,255,.35);background:rgba(91,140,255,.08)}
  .ev-refused{color:var(--red);border-color:rgba(251,90,78,.35);background:rgba(251,90,78,.08)}
  .ev-rolled_back{color:var(--amber);border-color:rgba(224,166,41,.35);background:rgba(224,166,41,.08)}
  .tier{font-size:11px;padding:1px 8px;border-radius:6px;border:1px solid var(--line2);color:var(--mut)}
  .tier.HIGH{color:#f0c674;border-color:rgba(224,166,41,.45);background:rgba(224,166,41,.07)}
  .tier.CRITICAL{color:#ff9a90;border-color:rgba(251,90,78,.5);background:rgba(251,90,78,.10)}
  .tier.MEDIUM{color:#9ec5ff;border-color:rgba(91,140,255,.3)}
  .rowact{justify-self:end}
  .rev{color:var(--violet);font-size:11px}

  /* ── verified column: the SSOT read-back verdict, not the commit's say-so ── */
  .vf{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;padding:1px 8px;border-radius:6px;
    border:1px solid var(--line2);white-space:nowrap}
  .vf.verified{color:var(--green);border-color:rgba(70,194,102,.35);background:rgba(70,194,102,.07)}
  .vf.partial{color:#f0c674;border-color:rgba(224,166,41,.5);background:rgba(224,166,41,.10);font-weight:600}
  .vf.failed{color:#ff9a90;border-color:rgba(251,90,78,.55);background:rgba(251,90,78,.12);font-weight:600}
  .vf-na{color:var(--faint)}

  /* ── expanded row: the full payload journey ── */
  .exp{display:none;min-width:880px;border-bottom:1px solid var(--line);
    background:linear-gradient(180deg,rgba(91,140,255,.045),transparent 120px),var(--elev)}
  .exp.open{display:block;padding:6px clamp(12px,2vw,20px) 18px}
  .exp-load{color:var(--faint);padding:16px 4px}
  .dsec{margin-top:14px}
  .dsec>.h{color:var(--mut);font-size:10.5px;text-transform:uppercase;letter-spacing:.09em;
    margin:0 0 7px;display:flex;align-items:center;gap:8px}
  .dsec>.h::after{content:"";flex:1;height:1px;background:var(--line)}
  .facts{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px 18px}
  .fact{min-width:0}
  .fact .k{color:var(--faint);font-size:11px}
  .fact .v{color:var(--fg);word-break:break-word}
  .fact .v.mut{color:var(--mut)}
  /* field-level diff table — the heart of the expansion */
  .ftable{width:100%;border-collapse:collapse;font-size:12.5px}
  .ftable th{text-align:left;color:var(--faint);font-weight:500;font-size:10.5px;text-transform:uppercase;
    letter-spacing:.06em;padding:5px 10px;border-bottom:1px solid var(--line)}
  .ftable td{padding:6px 10px;border-bottom:1px solid var(--line);vertical-align:top;word-break:break-word}
  .ftable tr:last-child td{border-bottom:none}
  .ftable .fname{color:var(--verb)}
  .ftable .ok{color:var(--green)} .ftable .drop{color:#ff9a90;font-weight:600}
  .ftable tr.dropped{background:rgba(251,90,78,.06)}
  .dnote{color:var(--faint);font-size:11px;margin-top:7px}
  .draw{margin:0;padding:11px 13px;background:var(--bg);border:1px solid var(--line);border-radius:9px;
    font-size:11.5px;color:var(--mut);overflow:auto;max-height:340px;white-space:pre;line-height:1.5}
  .copybtn{margin-bottom:7px}

  .empty{padding:54px 22px;text-align:center;color:var(--faint)}
  .empty .big{font-size:15px;color:var(--mut);margin-bottom:4px}

  /* ── mcp routing (read-only registry) ── */
  #routingWrap{margin-bottom:26px;display:none}
  #routing{display:grid;gap:10px}
  .rrow{display:flex;align-items:center;gap:12px;flex-wrap:wrap;border:1px solid var(--line);
    border-radius:var(--radius);background:var(--panel);padding:11px 15px}
  .rrow.on{border-color:rgba(70,194,102,.45);background:linear-gradient(180deg,rgba(70,194,102,.07),transparent)}
  .rrow .nm{font-weight:600;color:var(--verb)}
  .rrow .sys{color:var(--mut);font-size:12px;border:1px solid var(--line2);border-radius:6px;padding:1px 7px}
  .rrow .host{color:var(--faint);font-size:12px}
  .rrow .grow{flex:1 1 auto}
  .rbadge{font-size:11px;padding:2px 10px;border-radius:999px;border:1px solid var(--line2);color:var(--mut)}
  .rbadge.on{color:var(--green);border-color:rgba(70,194,102,.45);background:rgba(70,194,102,.08)}
  #routing code,.sec-title code{font-size:11.5px;color:var(--verb);background:var(--elev);
    border:1px solid var(--line2);border-radius:5px;padding:1px 6px}

  /* ── adapters ── */
  #adaptersWrap{margin-bottom:26px;display:none}
  #adapters{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}
  .acard{border:1px solid var(--line);border-radius:var(--radius);background:var(--panel);
    padding:14px 16px;position:relative;overflow:hidden}
  .acard::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--green)}
  .acard.stale::before{background:var(--faint)}
  .acard .nm{font-weight:600;color:var(--verb);font-size:14.5px;display:flex;align-items:center;gap:8px}
  .acard .nm .live{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 7px var(--green)}
  .acard.stale .nm .live{background:var(--faint);box-shadow:none}
  .acard .ns{margin:9px 0 7px;display:flex;flex-wrap:wrap;gap:5px}
  .acard .ns span{font-size:11px;color:var(--mut);border:1px solid var(--line2);border-radius:6px;padding:1px 7px}
  .acard .st{display:flex;gap:12px;color:var(--mut);font-size:12px;flex-wrap:wrap}
  .acard .st b{color:var(--fg)}
  .acard .ch{color:var(--faint);font-size:11px;margin-top:6px}

  /* ── automations ── */
  #autoWrap{margin-bottom:26px;display:none}
  .auth-row{display:flex;align-items:center;gap:8px;margin:0 2px 12px;flex-wrap:wrap}
  .auth-row input{background:var(--elev);border:1px solid var(--line2);border-radius:8px;color:var(--fg);
    font:12px var(--mono);padding:6px 10px;width:230px;max-width:60vw}
  .auth-row .hint{color:var(--faint);font-size:11px}
  .auth-row .ok{color:var(--green);font-size:11px}
  #automations{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}
  .autocard{border:1px solid var(--line);border-radius:var(--radius);background:var(--panel);
    padding:14px 16px;position:relative;overflow:hidden}
  .autocard::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--faint)}
  .autocard.s-active::before{background:var(--green)}
  .autocard.s-pending_approval::before{background:var(--amber)}
  .autocard.s-paused::before{background:var(--blue)}
  .autocard.s-archived::before{background:var(--line2)}
  .autocard .top{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .autocard .nm{font-weight:600;color:var(--verb);font-size:14.5px;flex:1 1 auto;min-width:0;word-break:break-word}
  .sbadge{font-size:11px;padding:2px 9px;border-radius:999px;border:1px solid var(--line2);color:var(--mut);white-space:nowrap}
  .sbadge.s-active{color:var(--green);border-color:rgba(70,194,102,.45);background:rgba(70,194,102,.08)}
  .sbadge.s-pending_approval{color:#f0c674;border-color:rgba(224,166,41,.45);background:rgba(224,166,41,.08)}
  .sbadge.s-paused{color:var(--blue);border-color:rgba(91,140,255,.35);background:rgba(91,140,255,.08)}
  .sbadge.s-draft,.sbadge.s-archived{color:var(--faint)}
  .autocard .meta{display:flex;flex-wrap:wrap;gap:6px;margin:9px 0 4px}
  .autocard .meta span{font-size:11px;color:var(--mut);border:1px solid var(--line2);border-radius:6px;padding:1px 7px}
  .autocard .meta .kind{color:var(--violet);border-color:rgba(168,119,247,.3)}
  .autocard .meta .trig{color:var(--blue);border-color:rgba(91,140,255,.3)}
  .autocard .sub{color:var(--faint);font-size:11px;margin-top:5px;word-break:break-all}
  .autocard .acts{display:flex;gap:7px;margin-top:11px;flex-wrap:wrap}
  .autocard .runs{margin-top:10px;border-top:1px solid var(--line);padding-top:9px;display:none}
  .autocard .runs.open{display:block}
  .runrow{display:flex;align-items:center;gap:8px;font-size:11.5px;padding:3px 0;color:var(--mut)}
  .runrow .rst{padding:1px 7px;border-radius:5px;border:1px solid var(--line2);font-size:10.5px}
  .runrow .rst.completed{color:var(--green);border-color:rgba(70,194,102,.4)}
  .runrow .rst.failed,.runrow .rst.blocked{color:#ff9a90;border-color:rgba(251,90,78,.4)}
  .runrow .rst.partial,.runrow .rst.compensated{color:#f0c674;border-color:rgba(224,166,41,.45)}
  .runrow .rst.running{color:var(--blue);border-color:rgba(91,140,255,.35)}
  /* compose form */
  .cform{border:1px solid var(--line2);border-radius:var(--radius);background:var(--panel);
    padding:14px 16px;display:grid;gap:10px;margin-bottom:14px}
  .cform input,.cform select,.cform textarea{background:var(--elev);border:1px solid var(--line2);
    border-radius:8px;color:var(--fg);font:12px var(--mono);padding:7px 10px;width:100%}
  .cform textarea{min-height:46px;resize:vertical}
  .cform .row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  .cform .ids{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  .stageblk{border:1px solid var(--line);border-radius:10px;padding:11px 12px;display:grid;gap:8px}
  .stageblk .stitle{color:var(--verb);font-size:12px;font-weight:600}
  .stageblk.b2{border-color:rgba(168,119,247,.3)}
  .cform .handoff{display:flex;align-items:center;gap:8px;color:var(--mut);font-size:12px;flex-wrap:wrap}
  .cform .handoff input{width:auto;flex:1 1 120px}
  .arrow{color:var(--violet);font-weight:600}

  /* toast */
  #toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%) translateY(20px);
    background:var(--elev);border:1px solid var(--line2);color:var(--fg);padding:11px 16px;
    border-radius:11px;font-size:13px;opacity:0;pointer-events:none;transition:.25s;z-index:50;
    box-shadow:0 18px 40px -16px rgba(0,0,0,.9)}
  #toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
  #toast b{color:var(--violet)}

  /* Narrow screens keep the compact table (records) and scroll horizontally — never big cards. */
  @media(max-width:760px){
    main{padding:12px}
    .feed-head,.row{gap:10px;padding:8px 12px}
  }
</style></head><body>
<header>
  <span class=brand><span class=dot></span><b>nilscript</b><span class=sl>· control plane</span></span>
  <span class=grow></span>
  <span class=chip id=count><b>0</b>&nbsp;actions</span>
  <span class=live><i></i> live</span>
  <button class="btn tiny ghost" id=themeBtn title="Toggle light / dark" aria-label="Toggle theme" onclick=toggleTheme()>☾</button>
</header>

<main>
  <section id=pendingWrap>
    <div class=sec-title>⏳ Awaiting your approval <span class=n id=pcount>0</span>
      <span style="color:var(--faint);text-transform:none;letter-spacing:0">— nothing commits until you decide</span></div>
    <div id=pending></div>
  </section>

  <section id=routingWrap>
    <div class=sec-title>MCP routing <span class=n id=rcount>0</span>
      <span style="color:var(--faint);text-transform:none;letter-spacing:0">— the active backend agents reach via the hosted MCP (switch with <code>nilscript adapters activate</code>)</span></div>
    <div id=routing></div>
  </section>

  <section id=adaptersWrap>
    <div class=sec-title>Adapters <span class=n id=acount>0</span>
      <span style="color:var(--faint);text-transform:none;letter-spacing:0">— backends linked &amp; live, derived from the stream</span></div>
    <div id=adapters></div>
  </section>

  <section id=autoWrap>
    <div class=sec-title>Automations <span class=n id=autocount>0</span>
      <span style="color:var(--faint);text-transform:none;letter-spacing:0">— conversation-authored workflows: state, trigger, version &amp; run history</span></div>
    <div class=auth-row>
      <input id=optoken type=password placeholder="operator token (for controls)" autocomplete=off oninput=saveToken()>
      <span class=hint id=tokhint>controls (approve / pause / run) need the registry token — view is open</span>
      <button class="btn tiny" onclick=toggleCompose()>＋ New cross-system automation</button>
    </div>
    <div id=composeForm style=display:none>
      <div class=cform>
        <div class=ids><input id=cf_id placeholder="automation id (e.g. lead-to-invoice)">
          <input id=cf_name placeholder="name"></div>
        <div class="stageblk b1">
          <div class=stitle>Stage 1 — system A</div>
          <div class=row2><select id=cf_a1 onchange="loadVerbs('cf_v1',this.value)"></select><select id=cf_v1></select></div>
          <textarea id=cf_args1 placeholder='args JSON — e.g. {"name":"Acme Co"}'></textarea>
        </div>
        <div class="stageblk b2">
          <div class=stitle>Stage 2 — system B</div>
          <div class=row2><select id=cf_a2 onchange="loadVerbs('cf_v2',this.value)"></select><select id=cf_v2></select></div>
          <textarea id=cf_args2 placeholder='args JSON — use $.input.X for handoff, e.g. {"ref":"$.input.lead"}'></textarea>
          <div class=handoff>handoff: <input id=cf_hk placeholder="input key (e.g. lead)">
            <span class=arrow>←</span> <input id=cf_hr value="$.stage_1.step_1.output.state"></div>
        </div>
        <button class="btn ok" onclick=submitCompose()>Create automation</button>
      </div>
    </div>
    <div id=automations></div>
  </section>

  <div class=sec-title>Activity <span style="color:var(--faint);text-transform:none;letter-spacing:0">— every agent action, one pane</span></div>
  <div class=feed>
    <div class=feed-head>
      <span>time</span><span>source</span><span>event</span><span>verified</span><span>verb</span>
      <span>tier</span><span>proposal</span><span>workspace</span><span style=justify-self:end>action</span>
    </div>
    <div id=rows></div>
    <div class=empty id=empty><div class=big>Waiting for events…</div>
      <div>Agent actions will stream in here as they happen.</div></div>
  </div>
</main>

<div id=toast></div>

<script>
const EV={executed:'ev-executed',proposed:'ev-proposed',refused:'ev-refused',rolled_back:'ev-rolled_back'};
const REVERSIBLE=new Set(['REVERSIBLE','COMPENSABLE']);
const VFG={verified:'✓',partial:'⚠',failed:'✗'};
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function hhmmss(iso){const t=(iso||'').replace('T',' ');return t.slice(11,19)||'—';}
function toast(html){const t=document.getElementById('toast');t.innerHTML=html;t.classList.add('show');
  clearTimeout(toast._);toast._=setTimeout(()=>t.classList.remove('show'),2600);}

async function copyRollback(token){
  try{await navigator.clipboard.writeText(token);}catch(e){
    const ta=document.createElement('textarea');ta.value=token;document.body.appendChild(ta);ta.select();
    try{document.execCommand('copy');}catch(_){}ta.remove();}
  toast('Rollback token copied — run <b>nil_rollback</b> with it in your agent to reverse this.');
}

async function tick(){
  try{
    const r=await fetch('/api/events?limit=200');const {events}=await r.json();
    const rows=document.getElementById('rows'),empty=document.getElementById('empty');
    document.getElementById('count').innerHTML='<b>'+events.length+'</b>&nbsp;actions';
    empty.style.display=events.length?'none':'block';
    rows.innerHTML=events.map(e=>{
      const ev=e.event||e.performative||'';const cls=EV[ev]||'ev-proposed';
      const canRoll=ev==='executed'&&e.compensation_token&&REVERSIBLE.has(e.reversibility);
      const tier=e.tier?`<span class="tier ${esc(e.tier)}">${esc(e.tier)}</span>`:'';
      const detail=[e.system?`<b>${esc(e.system)}</b>`:'',esc(e.summary||'')].filter(Boolean).join(' · ');
      const vf=e.verify?`<span class="vf ${esc(e.verify)}">${VFG[e.verify]||''} ${esc(e.verify)}</span>`:'<span class=vf-na>—</span>';
      const act=canRoll
        ? `<button class="btn tiny ghost" title="Reversible (${esc(e.reversibility)})" onclick="event.stopPropagation();copyRollback('${esc(e.compensation_token)}')">⤺ rollback</button>`
        : (e.reversibility?`<span class=rev title="${esc(e.reversibility)}">${e.reversibility==='IRREVERSIBLE'?'— final':''}</span>`:'');
      return `<div class=row data-id="${e.id}" onclick="toggle(${e.id})">
        <span class=t data-l=time title="${esc(e.received_at)}"><span class=caret>›</span> ${hhmmss(e.received_at)}</span>
        <span class=src data-l=source>${esc(e.source||'')}</span>
        <span class=ev data-l=event><span class="pill ${cls}">${esc(ev)}</span></span>
        <span data-l=verified>${vf}</span>
        <span class=verbcell data-l=verb>${esc(e.verb||'—')}${detail?`<span class=vdetail>${detail}</span>`:''}</span>
        <span data-l=tier>${tier}</span>
        <span class=pid data-l=proposal>${esc((e.proposal||'').slice(0,10))}</span>
        <span class=ws data-l=workspace>${esc(e.workspace||'—')}</span>
        <span class=rowact data-l=action>${act}</span>
      </div><div class=exp id="exp-${e.id}"></div>`;
    }).join('');
    paintOpen();   // restore an open expansion across the 2s refresh (detail is cached & immutable)
  }catch(_){}
}

// ── expandable row: the full payload journey, lazy-fetched on click ─────────────────────────────
let openId=null;const detailHtml={};
function toggle(id){
  if(openId===id){openId=null;paintOpen();return;}
  openId=id;
  if(detailHtml[id]){paintOpen();return;}
  paintOpen('<div class=exp-load>Loading the payload journey…</div>');
  fetch('/api/events/'+id).then(r=>r.ok?r.json():Promise.reject(r.status))
    .then(d=>{detailHtml[id]=renderDetail(d);if(openId===id)paintOpen();})
    .catch(()=>{if(openId===id)paintOpen('<div class=exp-load>Could not load this event\\'s detail.</div>');});
}
function paintOpen(loadingHtml){
  document.querySelectorAll('.exp.open').forEach(el=>{el.classList.remove('open');el.innerHTML='';});
  document.querySelectorAll('.row.sel').forEach(el=>el.classList.remove('sel'));
  if(openId==null)return;
  const exp=document.getElementById('exp-'+openId);
  if(!exp)return;  // the row scrolled out of the 200-row window
  exp.innerHTML=loadingHtml||detailHtml[openId]||'';
  exp.classList.add('open');
  const row=document.querySelector('.row[data-id="'+openId+'"]');if(row)row.classList.add('sel');
}

function fact(k,v,mut){return v==null||v===''?'':`<div class=fact><div class=k>${esc(k)}</div><div class="v${mut?' mut':''}">${esc(v)}</div></div>`;}
function jval(v){return (v&&typeof v==='object')?JSON.stringify(v):String(v==null?'':v);}
function renderDetail(d){
  const out=[];
  const vf=d.verify?`<span class="vf ${esc(d.verify)}">${VFG[d.verify]||''} ${esc(d.verify)}</span>`:'';
  const tier=d.tier?`<span class="tier ${esc(d.tier)}">${esc(d.tier)}</span>`:'';
  const prev=d.preview&&(d.preview.ar||d.preview.en)||'';
  // a. intent
  out.push(`<div class=dsec><div class=h>intent — what the agent asked</div><div class=facts>
    ${fact('verb',d.verb)}${fact('tier',d.tier)}${fact('workspace',d.workspace)}
    ${fact('source',d.source)}${fact('grant',d.grant_id,1)}</div>
    ${prev?`<div class=dnote>“${esc(prev)}”</div>`:''}
    ${Object.keys(d.raw_args||{}).length?`<div class=dnote>raw args</div><pre class=draw>${esc(JSON.stringify(d.raw_args,null,2))}</pre>`:''}</div>`);
  // b. resolution
  if(Object.keys(d.resolved||{}).length||d.ignored||d.expires_at){
    out.push(`<div class=dsec><div class=h>resolution — what the system resolved it to</div><div class=facts>
      ${fact('expires at',d.expires_at,1)}${d.ignored?fact('ignored args',jval(d.ignored)):''}</div>
      ${Object.keys(d.resolved||{}).length?`<pre class=draw>${esc(JSON.stringify(d.resolved,null,2))}</pre>`:''}</div>`);
  }
  // c. field-level SSOT verdict — the heart. before → requested → after, read back from the source.
  if((d.fields||[]).length){
    const dropped=d.fields.filter(f=>!f.verified).length;
    const hasBA=d.fields.some(f=>('before' in f)||('after' in f));  // adapter emitted the real read-back
    const trs=d.fields.map(f=>{
      const cells=hasBA
        ? `<td class=v>${esc(jval(f.before))}</td><td>${esc(jval(f.requested))}</td><td class="${f.verified?'':'drop'}">${esc(jval(f.after))}</td>`
        : `<td>${esc(jval(f.requested))}</td>`;
      return `<tr class="${f.verified?'':'dropped'}">
        <td class=fname>${esc(f.field)}</td>${cells}
        <td class="${f.verified?'ok':'drop'}">${f.verified?'✓ landed':'✗ dropped'}</td></tr>`;
    }).join('');
    const head=hasBA
      ? '<th>field</th><th>before</th><th>requested</th><th>after (SSOT)</th><th>verdict</th>'
      : '<th>field</th><th>requested</th><th>verdict</th>';
    out.push(`<div class=dsec><div class=h>field verification — before → requested → SSOT read-back ${vf}</div>
      <table class=ftable><thead><tr>${head}</tr></thead><tbody>${trs}</tbody></table>
      ${dropped?`<div class=dnote>⚠ ${dropped} field(s) did not survive the write — the row claimed success but the SSOT disagrees.${hasBA?'':' (This adapter reports only the dropped field names, not per-field read-back values.)'}</div>`:''}</div>`);
  }
  // d. commit & effect
  const r=d.result||{};const e=r.entity||{};const ss=r.ssot||{};const c=r.compensation||{};
  const replayed=(d.journey||[]).some(j=>j.replayed);
  if(r.claim||e.id||c.reversibility){
    out.push(`<div class=dsec><div class=h>commit &amp; effect</div><div class=facts>
      ${fact('claim',r.claim)}${fact('changed',r.changed==null?'':String(r.changed))}
      ${fact('entity',e.type)}${fact('entity id',e.id)}${fact('entity url',e.url)}
      ${fact('backend',ss.system)}${fact('read-after-write',ss.read_after_write==null?'':String(ss.read_after_write))}
      ${fact('reversibility',c.reversibility)}${fact('compensation token',c.token,1)}
      ${replayed?fact('replayed','yes (idempotent — deduped)'):''}</div></div>`);
  }
  // e. refusal (security-relevant)
  if(d.refusal&&d.refusal.code){
    out.push(`<div class=dsec><div class=h>refusal</div><div class=facts>
      ${fact('code',d.refusal.code)}${fact('field',d.refusal.field)}</div>
      ${d.refusal.message?`<div class=dnote>${esc(d.refusal.message)}</div>`:''}</div>`);
  }
  // f. saga thread
  if((d.journey||[]).length>1){
    out.push(`<div class=dsec><div class=h>journey — every event on this proposal</div><div class=facts>
      ${d.journey.map(j=>fact(hhmmss(j.received_at),j.event)).join('')}</div></div>`);
  }
  // g. raw — reconstruct from the log alone
  const raw=esc(JSON.stringify(d.raw,null,2));
  out.push(`<div class=dsec><div class=h>raw envelopes</div>
    <button class="btn tiny ghost copybtn" onclick='event.stopPropagation();copyText(${JSON.stringify(JSON.stringify(d.raw,null,2))})'>⧉ copy raw</button>
    <pre class=draw>${raw}</pre></div>`);
  return out.join('');
}
async function copyText(t){
  try{await navigator.clipboard.writeText(t);}catch(e){
    const ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();
    try{document.execCommand('copy');}catch(_){}ta.remove();}
  toast('Raw envelopes copied.');
}

async function decide(id,status){
  try{
    await fetch('/proposals/'+id+'/decision',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});
    toast(status==='approved'?'Approved — the commit will proceed.':'Rejected — the write will not commit.');
  }catch(_){toast('Could not record the decision.');}
  pend();tick();
}

async function pend(){
  try{
    const r=await fetch('/api/pending');const {pending}=await r.json();
    const wrap=document.getElementById('pendingWrap'),sec=document.getElementById('pending');
    document.getElementById('pcount').textContent=pending.length;
    wrap.style.display=pending.length?'block':'none';
    sec.innerHTML=pending.map(p=>{
      let prev='';try{const o=JSON.parse(p.preview);prev=(o&&(o.en||o.ar))||'';}catch(_){prev=p.preview||'';}
      const tier=p.tier?`<span class="tier ${esc(p.tier)}">${esc(p.tier)}</span>`:'';
      return `<div class=pcard>
        <div class=body>
          <div class=verb>${esc(p.verb||'action')} ${tier}</div>
          ${prev?`<div class=prev>${esc(prev)}</div>`:''}
          <div class=meta>proposal ${esc((p.proposal_id||'').slice(0,12))}</div>
        </div>
        <div class=actions>
          <button class="btn ok" onclick="decide('${esc(p.proposal_id)}','approved')">✓ Approve</button>
          <button class="btn no" onclick="decide('${esc(p.proposal_id)}','rejected')">✕ Reject</button>
        </div>
      </div>`;
    }).join('');
  }catch(_){}
}

function ago(iso){if(!iso)return '—';var t=new Date(iso+(/[zZ]|[+-]\\d\\d:?\\d\\d$/.test(iso)?'':'Z')).getTime();
  var s=Math.max(0,(Date.now()-t)/1000);
  return s<60?Math.floor(s)+'s ago':s<3600?Math.floor(s/60)+'m ago':Math.floor(s/3600)+'h ago';}
async function loadAdapters(){
 try{
  const r=await fetch('/api/adapters');const {adapters}=await r.json();
  const wrap=document.getElementById('adaptersWrap'),box=document.getElementById('adapters');
  document.getElementById('acount').textContent=adapters.length;
  wrap.style.display=adapters.length?'block':'none';
  box.innerHTML=adapters.map(a=>{
   const t=new Date((a.last_seen||'')+(/[zZ]$/.test(a.last_seen||'')?'':'Z')).getTime();
   const stale=(Date.now()-t)>120000;
   const ns=(a.namespaces||[]).map(n=>`<span>${esc(n)}.*</span>`).join('')||'<span style=opacity:.6>—</span>';
   const by=a.by_event||{}, ex=by.executed||0, pr=by.proposed||0, rf=by.refused||0;
   return `<div class="acard ${stale?'stale':''}">
     <div class=nm><span class=live></span>${esc(a.system||a.adapter)}</div>
     <div class=ns>${ns}</div>
     <div class=st><span><b>${a.events}</b> events</span><span><b>${ex}</b> exec</span><span><b>${pr}</b> prop</span>${rf?`<span><b>${rf}</b> refused</span>`:''}</div>
     <div class=ch>via ${esc((a.sources||[]).join(', ')||'—')} · ${esc(ago(a.last_seen))}</div>
   </div>`;
  }).join('');
 }catch(_){}
}
function host(u){try{return new URL(u).host;}catch(e){return u||'';}}
async function loadRouting(){
 try{
  const r=await fetch('/api/registry');const data=await r.json();const adapters=data.adapters||[];const ws=data.workspace||'';
  const wrap=document.getElementById('routingWrap'),box=document.getElementById('routing');
  document.getElementById('rcount').textContent=adapters.length;
  wrap.style.display=adapters.length?'block':'none';
  box.innerHTML=adapters.map(a=>{
   const on=!!a.active;
   const tgl=on
     ? abtn('⏻ Disable','ghost',`adapterToggle('${esc(ws)}','${esc(a.adapter_id)}',false)`)
     : abtn('⏼ Enable','ok',`adapterToggle('${esc(ws)}','${esc(a.adapter_id)}',true)`);
   return `<div class="rrow ${on?'on':''}">
     <span class=nm>${esc(a.label||a.adapter_id)}</span>
     <span class=sys>${esc(a.system||a.adapter_id)}</span>
     <span class=host>${esc(host(a.url))}</span>
     <span class=grow></span>
     <span class="rbadge ${on?'on':''}">${on?'● active':'idle'}</span>
     ${tgl}
   </div>`;
  }).join('');
 }catch(_){}
}
async function adapterToggle(ws,id,enable){
  if(!tokenVal())return toast('Enter the <b>operator token</b> (Automations section) to toggle adapters.');
  try{const r=await fetch(`/adapters/${ws}/${id}/${enable?'enable':'disable'}`,{method:'POST',headers:authHeaders()});
    if(r.status===401)return toast('Operator token rejected.');
    toast(enable?'Adapter <b>enabled</b> — several can be active at once.':'Adapter disabled.');loadRouting();
  }catch(_){toast('Could not toggle the adapter.');}
}
function applyThemeGlyph(){var b=document.getElementById('themeBtn');if(b)b.textContent=document.documentElement.getAttribute('data-theme')==='light'?'☀':'☾';}
function toggleTheme(){var next=document.documentElement.getAttribute('data-theme')==='light'?'dark':'light';document.documentElement.setAttribute('data-theme',next);try{localStorage.setItem('cp-theme',next);}catch(e){}applyThemeGlyph();}

// ── automations: view + (token-gated) control ───────────────────────────────────────────────────
function tokenVal(){try{return localStorage.getItem('cp-optoken')||'';}catch(e){return '';}}
function saveToken(){var v=document.getElementById('optoken').value;try{localStorage.setItem('cp-optoken',v);}catch(e){}paintTokHint(v);}
function paintTokHint(v){var h=document.getElementById('tokhint');if(!h)return;h.className=v?'ok':'hint';
  h.textContent=v?'token set — controls enabled in this browser only':'controls (approve / pause / run) need the registry token — view is open';}
function initToken(){var i=document.getElementById('optoken');if(i){i.value=tokenVal();paintTokHint(tokenVal());}}
function authHeaders(){var t=tokenVal();var h={'Content-Type':'application/json'};if(t)h['Authorization']='Bearer '+t;return h;}
function trigSummary(t){if(!t)return '—';if(t.type==='manual')return 'manual';
  if(t.type==='schedule')return t.cron?('cron '+t.cron):('every '+t.interval_seconds+'s');
  if(t.type==='event')return 'on '+(t.on_verb||'?')+' → '+(t.on_event||'executed');return t.type;}
function abtn(label,cls,onclick){return `<button class="btn tiny ${cls}" onclick="event.stopPropagation();${onclick}">${label}</button>`;}

async function loadAutomations(){
 try{
  const r=await fetch('/api/automations');const {automations}=await r.json();
  const wrap=document.getElementById('autoWrap'),box=document.getElementById('automations');
  document.getElementById('autocount').textContent=automations.length;
  wrap.style.display='block';  // always visible — the compose form + token live here, even with 0 automations
  if(!automations.length){box.innerHTML='<div class=empty style=padding:22px><div class=big>No automations yet</div><div>Click “＋ New cross-system automation” above to build one between two systems — or ask the agent via MCP.</div></div>';return;}
  box.innerHTML=automations.map(a=>{
   const nm=(a.name&&(a.name.en||a.name.ar))||a.automation_id;
   const ps=a.plan_summary||{};
   const shape=a.kind==='composed'?((ps.stages||0)+' stages · '+((ps.adapters||[]).join(', ')||'—')):((ps.nodes||0)+' steps');
   const st=a.state,rid=esc(a.workspace)+'-'+esc(a.automation_id);
   const acts=[];
   if(st==='pending_approval')acts.push(abtn('✓ Approve','ok',`autoState('${a.workspace}','${a.automation_id}',${a.version},'active')`));
   if(st==='active'){acts.push(abtn('⏸ Pause','ghost',`autoState('${a.workspace}','${a.automation_id}',${a.version},'paused')`));
     acts.push(abtn('▶ Run now','',`autoRun('${a.workspace}','${a.automation_id}')`));}
   if(st==='paused')acts.push(abtn('▶ Resume','ok',`autoState('${a.workspace}','${a.automation_id}',${a.version},'active')`));
   acts.push(abtn('↻ Runs','ghost',`toggleRuns('${a.workspace}','${a.automation_id}')`));
   return `<div class="autocard s-${esc(st)}">
     <div class=top><span class=nm>${esc(nm)}</span><span class="sbadge s-${esc(st)}">${esc(st)}</span></div>
     <div class=meta><span class=kind>${esc(a.kind)}</span><span class=trig>${esc(trigSummary(a.trigger))}</span>
       <span>v${a.version}</span><span>${esc(a.workspace)}</span><span>${esc(shape)}</span></div>
     <div class=sub>${esc((a.content_hash||'').slice(0,12))}…${a.approved_by?(' · approved by '+esc(a.approved_by)):''}</div>
     <div class=acts>${acts.join('')}</div>
     <div class=runs id="runs-${rid}"></div>
   </div>`;
  }).join('');
 }catch(_){}
}
async function autoState(ws,id,ver,state){
  if(!tokenVal())return toast('Enter the <b>operator token</b> above to control automations.');
  try{const r=await fetch(`/automations/${ws}/${id}/${ver}/state`,{method:'POST',headers:authHeaders(),body:JSON.stringify({state,approved_by:'operator'})});
    if(r.status===401)return toast('Operator token rejected.');
    toast(state==='active'?'Armed — the automation is now <b>active</b>.':state==='paused'?'Paused.':'Updated.');loadAutomations();
  }catch(_){toast('Could not update the automation.');}
}
async function autoRun(ws,id){
  if(!tokenVal())return toast('Enter the <b>operator token</b> above to run automations.');
  try{const r=await fetch(`/automations/${ws}/${id}/run`,{method:'POST',headers:authHeaders(),body:JSON.stringify({idempotency_key:'ui-'+Date.now()})});
    if(r.status===401)return toast('Operator token rejected.');const d=await r.json();
    toast(d.run?('Run <b>'+(d.run.state||'started')+'</b>.'):'Fired.');loadAutomations();openRuns(ws,id);
  }catch(_){toast('Could not run the automation.');}
}
function toggleRuns(ws,id){const el=document.getElementById('runs-'+ws+'-'+id);if(!el)return;
  if(el.classList.contains('open')){el.classList.remove('open');el.innerHTML='';}else openRuns(ws,id);}
async function openRuns(ws,id){
  const el=document.getElementById('runs-'+ws+'-'+id);if(!el)return;
  el.classList.add('open');el.innerHTML='<div class=runrow style=color:var(--faint)>loading…</div>';
  try{const r=await fetch(`/automations/${ws}/${id}/runs?limit=8`);const {runs}=await r.json();
    el.innerHTML=runs.length?runs.map(x=>`<div class=runrow><span class="rst ${esc(x.state)}">${esc(x.state)}</span>
      <span>${esc((x.fired_by||'').slice(0,20))}</span><span style=color:var(--faint)>${hhmmss(x.started_at)}</span></div>`).join('')
      :'<div class=runrow style=color:var(--faint)>no runs yet</div>';
  }catch(_){el.innerHTML='<div class=runrow>could not load runs</div>';}
}

// ── compose form: build a two-system automation in one click ────────────────────────────────────
let cfWs='';
function val(id){var e=document.getElementById(id);return e?e.value.trim():'';}
function toggleCompose(){const f=document.getElementById('composeForm');if(!f)return;
  if(f.style.display==='none'){f.style.display='block';populateCompose();}else f.style.display='none';}
async function populateCompose(){
  try{const d=await(await fetch('/api/registry')).json();cfWs=d.workspace||'';const ads=d.adapters||[];
   const opts='<option value="">— select adapter —</option>'+ads.map(a=>`<option value="${esc(a.adapter_id)}">${esc(a.label||a.adapter_id)}${a.system?(' ('+esc(a.system)+')'):''}</option>`).join('');
   ['cf_a1','cf_a2'].forEach(id=>{const s=document.getElementById(id);if(s)s.innerHTML=opts;});
   ['cf_v1','cf_v2'].forEach(id=>{const s=document.getElementById(id);if(s)s.innerHTML='<option value="">— pick adapter first —</option>';});
  }catch(_){}
}
async function loadVerbs(vsel,adapter){
  const s=document.getElementById(vsel);if(!s)return;
  if(!adapter){s.innerHTML='<option value="">— pick adapter first —</option>';return;}
  if(!tokenVal()){s.innerHTML='<option value="">operator token required</option>';return;}
  s.innerHTML='<option>loading…</option>';
  try{const r=await fetch(`/api/adapter-skeleton?workspace=${encodeURIComponent(cfWs)}&adapter_id=${encodeURIComponent(adapter)}`,{headers:authHeaders()});
    if(r.status===401){s.innerHTML='<option value="">token rejected</option>';return;}
    if(!r.ok){s.innerHTML='<option value="">adapter unreachable</option>';return;}
    const d=await r.json();const vs=d.verbs||[];
    s.innerHTML=vs.length?('<option value="">— select verb —</option>'+vs.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('')):'<option value="">no verbs</option>';
  }catch(_){s.innerHTML='<option value="">error</option>';}
}
async function submitCompose(){
  if(!tokenVal())return toast('Enter the <b>operator token</b> above first.');
  const id=val('cf_id'),nm=val('cf_name')||id,a1=val('cf_a1'),v1=val('cf_v1'),a2=val('cf_a2'),v2=val('cf_v2');
  if(!id||!a1||!v1||!a2||!v2)return toast('Need id + both adapters + both verbs.');
  let ar1={},ar2={};
  try{ar1=val('cf_args1')?JSON.parse(val('cf_args1')):{};ar2=val('cf_args2')?JSON.parse(val('cf_args2')):{};}
  catch(e){return toast('Args must be valid JSON.');}
  const stage=(n,ad,vb,ar)=>({name:n,adapter:ad,plan:{wosool:"0.1",workspace:cfWs,entry:"step_1",
    pipeline:[{id:"step_1",type:"action",skill:vb.split('.')[0],verb:vb,args:ar}]}});
  const s2=stage('stage_2',a2,v2,ar2);const hk=val('cf_hk'),hr=val('cf_hr');if(hk&&hr)s2.input_from={[hk]:hr};
  const body={automation_id:id,name:{en:nm,ar:nm},trigger:{type:"manual"},
    composed:{workspace:cfWs,stages:[stage('stage_1',a1,v1,ar1),s2]}};
  try{const r=await fetch('/automations/compose/register',{method:'POST',headers:authHeaders(),body:JSON.stringify(body)});
    if(r.status===401)return toast('Operator token rejected.');
    const d=await r.json();
    if(!d.ok){const why=(d.report&&d.report.stages||[]).flatMap(s=>(s.diagnostics||[]).map(x=>x.code)).join(', ')||(d.report&&d.report.errors||[]).join(', ')||d.error||'refused';
      return toast('Refused: '+esc(why));}
    toast('Cross-system automation <b>registered</b> — pending approval.');toggleCompose();loadAutomations();
  }catch(_){toast('Could not create the automation.');}
}

initToken();tick();pend();loadAdapters();loadRouting();loadAutomations();applyThemeGlyph();
setInterval(()=>{tick();pend();loadAdapters();loadRouting();loadAutomations();},2000);
</script></body></html>"""


try:  # pragma: no cover - server entrypoint; prod mounts CP_DB_PATH's dir (e.g. /data volume)
    app = create_app()
except OSError:
    # No writable store dir at import (e.g. local test import without /data). The server process
    # in production constructs this successfully because the volume is mounted before boot.
    app = None  # type: ignore[assignment]
