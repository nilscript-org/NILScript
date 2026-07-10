# PLAN — make the whole NIL system SaaS-grade multi-tenant

## Where we are (examined, not assumed)
The kernel already has the RIGHT multi-tenant bones — they're just collapsed to one tenant (`ws_acme`)
for the live demo:
- **Per-connection tenant binding** (`mcp/tenant.py`): an agent connects to the shared MCP and sends
  its backend coordinates as headers (`x-nil-adapter-url`, bearer, `x-nil-workspace`). **The kernel
  stores NO tenant creds** — the tenant points us at THEIR adapter, which holds the real creds. This is
  the correct SaaS isolation primitive.
- **`TenantToolsProvider`** (`mcp/server.py`): a per-connection `NilTools` (own proposal/idempotency
  session) — concurrent agents never see each other's proposals.
- **Registry-routed active adapter** (`mcp/registry.py`): a header-less connection for a workspace
  routes to whatever adapter that workspace activated (`GET /adapters/active`), token-gated.
- **Brain/CP are workspace-parametrized** (`tenant=` on every brain call; CP registry/ledger keyed by
  workspace).
- `NIL_MCP_MULTI_TENANT` flag exists.

**Gap:** the live stack runs single-tenant (one `ws_acme`, one Odoo shim, one brain store, one keycloak
user), and several layers added recently (the intent router's graph/automation providers, single-surface,
export handles, rate limits, durable workflows) are NOT yet tenant-scoped end-to-end.

## Principle
> One shared control/meaning/governance plane; **per-tenant everything else** — identity, data,
> adapters, credentials, quotas, audit. The kernel never holds a tenant's backend creds. Isolation is
> enforced at every layer by a single `tenant` (workspace) identity that flows from auth → MCP → router
> → brain → control-plane → adapters → export → durable workflows.

## The tenant identity spine (do this first)
A request's tenant must be **derived from authenticated identity**, not a free header, in SaaS mode:
- Auth (keycloak): the bearer/JWT carries a `workspace` claim (or realm-per-tenant). The MCP resolves
  `tenant = claim`, NOT the `x-nil-workspace` header (header-binding stays for self-hosted/dev only).
- Every downstream call carries that tenant. Default-deny if absent.

## Per-layer plan
| Layer | Now | SaaS-grade target |
|---|---|---|
| **Identity** | keycloak (one realm/user) | workspace claim in JWT → tenant; per-tenant users/roles; default-deny |
| **MCP relay** | per-connection tenant via header/registry | tenant from auth claim; `_GraphIntentProvider`/`_AutomationIntentProvider`/brain calls **tenant-scoped**; single-surface per tenant |
| **Intent router** | providers share one brain/automation | pass `tenant` into every provider.resolve; brain/automation/adapter all keyed by tenant |
| **Adapters** | one active odoo shim (ws_acme) | per-tenant active adapter from registry; tenant-owned creds (kernel holds none); per-tenant shim or per-tenant creds in the shim |
| **Brain (graph/instances/ledger)** | tenant param, shared store | enforce per-tenant partition in every store + query; authz that a token can only read its tenant; no cross-tenant leakage |
| **Control-plane** | workspace-keyed registry/ledger/approvals | per-tenant ledger + registry + approval queue; tenant-scoped tokens; audit per tenant |
| **Export handles** | tenant-scoped + TTL (built) | + access-controlled fetch, PII-at-rest, per-tenant storage prefix, no cross-tenant handle open |
| **Quotas / rate limits** | none per-tenant | **per-tenant throttle** (the Odoo 429!) + read/write/export quotas + fair-use; ties into durable-workflow rate policy |
| **Durable workflows (Temporal)** | not wired | per-tenant isolation: workflow IDs / Temporal namespaces include tenant; per-tenant rate policy; tenant-scoped signals |
| **Observability / audit** | shared logs | per-tenant audit trail + metrics + the dashboard timeline scoped to tenant |
| **Provisioning** | manual | onboarding flow: create tenant → keycloak workspace + CP registry slot + brain partition + quota defaults + connect adapter |
| **Secrets** | host `.env` | per-tenant secret scope (the adapter holds creds; the platform never co-mingles) |

## Phases
1. **Tenant identity spine** — derive tenant from the auth claim; thread it through MCP → router →
   brain → CP; default-deny. (Unblocks everything.)
2. **Tenant-scope the new surfaces** — intent router providers, single-surface, export handles all take
   `tenant`; conformance test: tenant A can never read/act on tenant B.
3. **Per-tenant quotas + rate limits** — the durable executor's rate policy is per-tenant (fixes 429
   fairness); read/write/export quotas.
4. **Brain + CP isolation hardening** — partition + authz audit; prove no cross-tenant leakage.
5. **Provisioning/onboarding** — one call stands up a tenant end-to-end.
6. **Durable workflows tenant-scoped** (depends on the Temporal integration in
   [[PLAN-intent-unification-and-durability]]).

## Acceptance (SaaS-grade)
- A token for tenant A, on the shared MCP, can read/write/aggregate/export/automate **only** A's data,
  routed to A's active adapter, governed by A's approvals, bounded by A's quotas, audited under A.
- No header can override the authenticated tenant in SaaS mode.
- Onboarding a new tenant is one provisioning call; zero shared mutable state between tenants except the
  control/meaning plane itself.
- A noisy tenant (bulk delete) is rate-limited per-tenant and cannot starve others (durable workflow +
  per-tenant policy).
