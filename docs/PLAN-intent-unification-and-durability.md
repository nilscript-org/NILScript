# PLAN — NIL Intent unification + heavy-ops durability (the recent essential changes)

Status legend: ✅ shipped+deployed · 🔶 partial · ⬜ next.

## 0. The principle (the spine of everything below)
> The model emits ONE payload — an **Intent** (what it wants). The system **resolves → governs →
> executes deterministically** and returns an Outcome. No tool selection, no filter built by the model,
> no keyword matching, universal at the contract level. Model intelligence is removed from the loop.

## 1. The read data plane ✅
Fixes the 590 KB context flood (whole-record dumps). `nilscript/dataplane/`:
- primitives: `enforce_byte_cap` (REFUSE-not-truncate), `project`/`project_items`, `parse_filter`.
- `ReadPlane` over a `ReadBackend` protocol: schema/count/search/get/aggregate/export + capability
  fallback + read-authz + keyset cursor.
- export → tenant-scoped TTL data-handles; `run_bulk` spine (batched, resumable, stoppable).
- MCP relay byte-cap **backstop**; Odoo adapter implements `ReadBackend` (search_read fields=,
  search_count, read_group, keyset). Conformance + 64 adapter tests.

## 2. The Intent contract ✅
`dataplane/intent.py`: `Intent{about, where[Binding{attr,rel,value}], seek|change, by}` · `Outcome`
(result | proposal | refusal) · `REL_TO_OP` / `OP_TO_RESOURCE` (fixed enum maps, NOT keywords) ·
pluggable `BindingResolver` (graph supplies ontology; `IdentityResolver` default) · `IntentResolver`
(the=1, all=page, count, summary→aggregate). Writes: `change{op,set}` → universal generic-CRUD
`resource.*` (create/update/remove); update/remove resolve target by `where` then propose; governance
unchanged (HIGH held, MEDIUM two-step).

## 3. The universal router ✅
`dataplane/router.py`: `IntentRouter` delegates `about` to the first provider that OWNS it (structural,
no keywords). Relay providers (`mcp/tools.py`): `_AdapterIntentProvider` (business → backend, fallback)
· `_GraphIntentProvider` (cycle/policy/role/instance/overview/activity → brain; change → `assert_fact`
POST /api/assert) · `_AutomationIntentProvider` (automation → registry: list/register). `NilTools`
gains optional `brain`+`automation`; wired once in `build_tools`/`build_server`.

## 4. Single surface ✅
`NIL_MCP_SINGLE_SURFACE=1` → the ONLY model-facing tools are `nil_intent` + describe/commit/status/
rollback; search/count/get/aggregate/export/query/propose/graph/automation/dynamic are hidden (subsumed
by nil_intent). Makes the correct path the only obvious one. `nil.intent` never 500s (broad refusal).

## 5. Batch + summary ✅
`intent_batch` (many intents, partial-allow). `seek="summary"` + `by` → server-side aggregate (Odoo
many2one `[id,label]`→label so "by country_id" works).

## 6. Live deploy + operational hardening ✅
mcp + playground images from main; Hermes SOUL (`/opt/data/skills/nil/*`) directs ALL reads+writes+
bulk to `nil_intent`. **Root fix for the recurring web "no tools":** Hermes discovers MCP tools once at
startup and never reconnects; the MCP cold-starts in ~54s; deploys restarted Hermes too early → the
dashboard cached 0 tools. Fix = `/root/redeploy-mcp.sh` gates the Hermes restart on MCP readiness;
`mcp_discovery_timeout` 1.5→30; skip startup adapter-describe under single-surface. UI: grouped
tool-call chips (`nil_intent ×42` progress) in wosool-hub Ask.tsx.

## 7. THE GAP — heavy-ops durability (the bulk-delete failure) ⬜
**Observed live:** owner approved 41 deletes; only ~5 executed. Logs show the real causes:
1. Odoo **429 Too Many Requests** + transport drops (`Idle`/`Request-sent`) — 41 rapid XML-RPC calls.
2. Odoo refuses some unlinks (`res.partner.unlink: archive instead`) — linked/policy-restricted records.
`run_bulk` is an **in-memory, non-durable** spine — it does not survive an executor restart, does not
throttle, does not retry/backoff. That is exactly what failed.

**The right fix = durable execution (Temporal — already running in wosool-saas: `orchestrator` +
`api/temporal`).** Clean separation:
```
NIL governs   : intent → propose → tier → approval   (SSOT = control-plane event ledger)
Temporal runs : approval = signal → DURABLE workflow
                activity per batch = governed commit, retry+backoff+rate-limit policy
the ledger    : every activity emits an event → control-plane stays source of truth
```
This solves 429 (backoff+throttle), partial execution (resume), crash-survival, and cancellation
("stop" = workflow cancel) — turning heavy ops from fragile to SaaS-grade. Plus a small local fix:
**archive-fallback** when Odoo refuses unlink. Not everything needs Temporal — single writes keep the
direct propose→commit path; durable workflows are for bulk / long-running / flaky-backend operations.

### Next steps (durability)
1. ⬜ Define the NIL↔Temporal contract: approval → workflow start; activity = one governed
   `commit`/batch with `RetryPolicy` (backoff on 429/transport) + per-tenant rate limit; signals for
   approve/stop; heartbeats for resumability.
2. ⬜ Route bulk/heavy NIL operations (export→batch writes, delete-many, update-many) through it; emit
   per-activity events to the CP ledger.
3. ⬜ Archive-fallback + honest reporting ("N could not be deleted, archived instead").
4. ⬜ Observability: per-workflow timeline surfaced in the dashboard (the agent-UX best practice).
