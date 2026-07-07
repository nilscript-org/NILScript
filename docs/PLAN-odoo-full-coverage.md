# PLAN — Odoo adapter: 100% module coverage (all of Odoo, not just CRM)

## Status (2026-06-26)
**Phases 1–6 BUILT (TDD, 98 conformance tests green).** Phase 1 merged (PR #10 → main, 0d2e937);
phases 2–6 on branch `feat/odoo-full-coverage-p2-6` in `adapters/odoo-crm-nil-adapter`.
- ✅ **P1 Dynamic discovery** — `describe_target` derives a lean projection from any model's live
  `fields_get` (heavy/collection fields dropped, sensitivity flagged); `nil.*` reads cover ANY model.
- ✅ **P2 Tier + sensitivity policy** (`governance.py`) — per-(model, op) tier table, model
  classification (financial/hr/system), DESTRUCTIVE-on-financial/HR escalates to CRITICAL, per-tenant
  grant overlay (isolated), and per-field sensitivity now ENFORCED on reads (sensitive fields redacted
  unless `reveal`-ed — closed a real gap where classification existed but wasn't applied).
- ✅ **P3 Generic `op="method"`** — `resource.method` + `system.call_method`; per-(model, method)
  allow-list (default-deny); reversibility per method (post→`button_draft`) → COMPENSABLE token +
  rollback previews/runs the inverse.
- ✅ **P5 Module scoping** — operator enables module GROUPS; out-of-scope models undiscoverable AND
  unwritable (discovery + write + method + curated verbs all consult `module_enabled`).
- ✅ **P6 Semantic verbs** — representative set across module groups (`account.create_invoice`,
  `stock.validate_picking`, `sale.confirm_order`); curated method dispatch generalized to any granted
  method. Long tail stays on the generic plane.
- ✅ **P4 Conformance** — one model per module group (account/stock/sale/hr/product): read+projection+
  count+aggregate, default-deny→governed write, default-deny→governed method, sensitivity redaction.
  The structural-unexpressibility invariant STILL holds — **SRR 100% / EL 0** on all corpora.

### Gap closure (2026-06-26, cont.)
- ✅ **Real-instance conformance harness** — `conformance/test_live_odoo.py`, GATED on `ODOO_*` creds
  (skips cleanly without them), read-only-safe by default, opt-in governed write via `NIL_LIVE_WRITE=1`.
  Ready to run; an actual live run still needs an operator to export credentials (none in this env).
- ✅ **Durability — adapter slice** — `RealSystemClient` retries transient transport faults (429/5xx)
  with exponential backoff + optional min-interval throttle; application Faults stay terminal. The
  "429 flood" lesson is handled at the single-call level.
- ✅ **`op=method` contract readiness** — kernel `Change` now carries `method`/`params` and
  `OP_TO_RESOURCE["method"] = "resource.method"`, so the one `nil_intent` payload can express workflow
  actions the moment the write-execution provider lands.

⬜ Remaining (each a deliberate separate effort, NOT a loose end of this work):
- **Live conformance RUN** — needs real Odoo credentials exported into the environment.
- **`nil_intent` write-execution provider** — the kernel resolver does reads only; a provider that maps
  `change`→propose→commit (CRUD *and* method) is unbuilt — part of [[PLAN-intent-unification-and-durability]].
- **P7 orchestration-level durable execution** — Temporal workflows/signals/per-tenant queues — the
  body of [[PLAN-intent-unification-and-durability]] (needs Temporal infra).

## The key realization (don't hand-write verbs)
The universal machinery we built **already works over ANY Odoo model** — it is not CRM-specific:
- `ReadPlane` reads any `target` once `describe_target` returns its shape (count/search/get/aggregate/
  export, projected + capped).
- `resource.create/update/delete` is **generic CRUD over any declared target** (synthesized
  reversibility), already in the adapter.
- `nil_intent`'s `about` can be **any model** (`account.move`, `stock.picking`, `hr.employee`, …).

**The CRUD/workflow split (the honest gap).** CRUD alone is not all of Odoo. Many high-value Odoo
operations are **workflow methods**, not create/update/delete: posting an invoice (`action_post` on
`account.move`), validating a picking (`button_validate` on `stock.picking`), confirming a sale order
(`action_confirm`). Generic CRUD does **not** cover these. But the adapter already has the primitive:
`op="method"` (used today by `crm.log_note` → `message_post`). So the one missing piece for true 100%
coverage is **exposing a generic `op="method"` in the intent layer** — then every workflow action is
covered universally, with no per-action verb, and semantic verbs stay a true luxury (ergonomics +
preview), not a capability requirement.

So the ONLY thing scoping us to CRM is the hardcoded **`DECLARED_TARGETS`** (crm.lead/res.partner/…)
in `translate.py` + the curated projections in `read_plane.py`. 100% coverage = replace that ceiling
with **dynamic, schema-driven, policy-governed exposure of every model the tenant's Odoo has** —
covering accounting, invoicing, sales, purchase, inventory, manufacturing, HR, projects, POS, etc.,
with zero hand-written per-module verbs.

## Principle (keep the safety invariant)
> "advertised ≡ committable" still holds — but the skeleton becomes **dynamic + policy-gated**, not a
> hardcoded list. Every model is discoverable and readable; every WRITE is governed by a per-(model,op)
> **tier policy** and per-field **sensitivity**; destructive ops on financial/HR models are default-deny
> until explicitly granted. The agent gains reach; governance gains teeth.

## Mechanisms (all schema/capability-driven, universal)
1. **Dynamic model discovery** — enumerate the live models via Odoo `ir.model` (+ `ir.module.module`
   for installed modules). Expose what the instance actually has, per tenant. No static target list.
2. **Schema-driven projections** — derive each model's lean default projection from `fields_get`:
   pick `display_name`/`name` + a few key scalar fields; classify cardinality (small/large/huge);
   mark `filterable/sortable` from Odoo field metadata; flag `sensitivity` (financial/HR/PII fields).
   Replaces the hand-curated `_TARGET_FIELDS`.
3. **Per-(model, op) tier policy** — a declarative policy table (not code-per-model):
   - reads: free (bounded/projected) — but sensitive models (`hr.*`, `account.*`) require a read grant.
   - writes: `create/update` MEDIUM by default; `delete` HIGH; financial posting / HR payroll /
     `unlink` on `account.move` → CRITICAL (held for owner). Default-deny destructive on financial/HR.
   - the policy is data, editable per tenant; ships with safe defaults.
4. **Capability profile per model** — `server_filter/sort/paginate/aggregate` true for Odoo (search_read
   /search_count/read_group), so the read plane works everywhere with the existing fallbacks.
5. **Intent layer is automatic** — `about=<any model>` flows through the same `IntentResolver` /
   `resource.*`; no new wiring per module. Bulk/heavy ops go through the durable executor
   ([[PLAN-intent-unification-and-durability]]) — essential once accounting/inventory volumes appear.
6. **Generic `op="method"` in the intent** — expose the existing method primitive through `nil_intent`
   so workflow actions (`action_post`, `button_validate`, `action_confirm`, …) are universally callable
   with no per-action verb: `nil_intent(about="stock.picking", where=[...], change={op:"method",
   method:"button_validate"})`. Governed by the **same per-(model, method) tier policy** as writes —
   methods are NOT free: posting/cancelling/validating are MEDIUM→CRITICAL by sensitivity, allow-listed
   per model (no arbitrary method call), reversibility synthesized or declared per method (post→cancel).
   This is the piece that makes CRUD + method = full capability; semantic verbs become pure sugar.
7. **Module scoping** — the operator enables module groups per tenant (Sales, Accounting, Inventory,
   HR, Manufacturing, …); discovery + policy respect the scope. Onboarding picks which modules to expose.

## Semantic verbs as an OPTIONAL top layer (not required for coverage)
The generic plane (CRUD **+ `op="method"`**) gives 100% coverage as the floor — including workflow
actions like post/validate/confirm. ON TOP, curated **semantic verbs** for common flows improve
ergonomics + bilingual previews (e.g. `account.create_invoice`, `account.register_payment`,
`stock.validate_picking`, `sale.confirm_order`) — same pattern as today's `crm.*`. What they buy is
**capability-free**: clean arguments (hiding `move_type`, the `[(0,0,{...})]` line format, the exact
method name), a human/bilingual approval preview, a precise per-verb tier and pre-flight check. Worth it
for the ~20 highest-value/most-dangerous flows; a trap for the long tail. The generic `resource.*` +
`method` intent path covers everything else.

## The Business Graph ties it together (business words → any model)
The ontology maps business concepts to Odoo models so the agent speaks **business**, the adapter covers
**all models**: `about="invoice"` → `account.move`; `about="payment"` → `account.payment`;
`about="stock"` → `stock.quant`. The `BindingResolver` (graph) does this mapping; full coverage makes
every business concept executable.

## Governance + safety (must-haves before turning it on)
- **Per-field sensitivity** → read-authz drops financial/PII fields without a grant (already in the
  ReadPlane); extend the field catalog from `fields_get`.
- **Default-deny destructive** on `account.*`/`hr.*` (post/cancel/unlink) until a tenant grant exists.
- **Tier escalation** for irreversible/financial ops (CRITICAL → owner approval, never auto).
- **Audit** every cross-module write to the CP ledger.
- **Rate-limit per tenant** (the Odoo 429 lesson) — heavy cross-module reads/writes throttled.

## Phases
1. **Dynamic discovery + schema-driven projections** — `OdooReadBackend.describe_target` reads
   `ir.model`/`fields_get`; remove the CRM `_TARGET_FIELDS`/`DECLARED_TARGETS` ceiling; cache per model.
2. **Per-(model,op) tier + sensitivity policy** — declarative table + safe defaults + per-tenant
   override; `resource.*` consults it; default-deny destructive financial/HR. Same table governs
   methods (per-(model, method) allow-list + tier).
3. **Generic `op="method"` in the intent** — surface the existing method primitive through `nil_intent`;
   per-model allow-list of callable methods; tier/reversibility per method (post→cancel, confirm→cancel);
   default-deny any method not allow-listed. Covers all workflow actions with no per-action verb.
4. **Conformance** — read/aggregate/export + governed write + governed method across a representative
   model from each module group (account.move `action_post`, stock.picking `button_validate`,
   sale.order `action_confirm`, hr.employee, product.product), against a synthetic + a real instance;
   verify projection/cap/tier/sensitivity/method-allow-list hold.
5. **Module scoping + onboarding** — operator enables module groups per tenant.
6. **Semantic verbs** for the top ~20 high-value flows (invoicing, payments, inventory moves, sales).
7. **Durable execution** for cross-module bulk/posting (depends on the Temporal integration).

## Acceptance
- "How many overdue invoices?", "revenue by account this quarter", "validate this picking", "approve
  invoices over 5000" all work via `nil_intent` over the real Odoo — **any installed module**, with the
  same lean/projected/governed/tier-gated discipline, no hand-written verb per model.
- Financial/HR destructive ops are default-deny and CRITICAL-gated; reads of sensitive fields require a
  grant; everything is audited and per-tenant rate-limited.
