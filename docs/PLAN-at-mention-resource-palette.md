# PLAN — `@`-Mention Resource Palette (verbs · adapters · cycles · roles)

**Status:** Phase A shipped (2026-07-01) — see §11
**Date:** 2026-07-01
**Surface:** wosool-hub composer (the "Good morning" input box)
**Spans:** `wosool-hub` (frontend + BFF) · `nilscript` control plane (verbs, adapters, cycles) · `nilscript-graph` brain (roles/entities)

---

## 1. What the user wants

Typing `@` in the home composer should open a palette of **things that actually exist in the running system** — not a hardcoded list — so the operator can reference them by name:

- **Verbs** — the governed actions the active backend exposes (`crm.create_lead`, `services.create_invoice`, …)
- **Adapters** — the registered/active backends (`pb-prod`, Odoo, …)
- **Users** — *(see §3: this really means **Roles** — @Finance, @CFO — not people)*
- **Cycles / entities** — bonus, cheap to add, high value (`@finance`, `entity:invoice`)

The selected item is inserted as a typed directive (e.g. `@verb:crm.create_lead`) into the prompt that goes to Hermes.

## 2. Current state (verified in code)

- Composer is a plain `ComposerPrimitive.Root` at `wosool-hub/src/components/assistant-ui/thread.tsx:166-192`. Typing `@` today does **nothing** — no mention/slash plugin is wired. (The `@` in the screenshot is the user manually typing to test.)
- Submit path: `composer.send()` → `onNew()` in `src/lib/hermes-runtime.ts:351` → `gateway.request("prompt.submit", { session_id, text })` over WebSocket JSON-RPC to `/hermes/api/ws`. **The mention is just text in `text`** unless we attach metadata.
- The three quick-action chips (`Create Workflow / Policy Audit / System Health`) are hardcoded in `CHIPS` at `thread.tsx:47-63` and simply `setText(prompt)+send()`.

### 2.1 The library already supports this — no new dependency

`@assistant-ui/react@0.14.24` ships the primitives:

- `unstable_useMentionAdapter(options)` → `{ adapter, directive, iconMap, fallbackIcon }`
  (`node_modules/@assistant-ui/react/dist/unstable/useMentionAdapter.d.ts`) — supports **flat OR categorized (drill-down) items**, icon maps, and an `onInserted(item)` callback.
- `ComposerPrimitive.Unstable_TriggerPopover` (+ `TriggerPopoverRoot`, `TriggerPopoverItems`, `TriggerPopoverCategories`, `TriggerPopoverBack`) — bind a trigger `char="@"` to an adapter and render a floating, keyboard-navigable popover. Caret positioning, filtering, arrow-key nav, Enter/Esc are handled by the primitive.

This means **~all the frontend UX plumbing is free**. Our work is: (a) supply the data, (b) wrap the composer, (c) style the popover, (d) decide the directive format + downstream handling.

## 3. The honest data model — there is no "user"

Verified in `nilscript-graph/src/nilscript_graph/models.py`:

- The brain has **no `User`/`Person` entity**. It models **`Role`** as first-class (`kind=="role"`, `role_name`, bilingual `label`, `escalates_to`).
- `Role.members: tuple[str,...]` is **opaque principal ids resolved by the tenancy layer (file 09), which is not in the brain** — the brain returns them raw (usually `[]`).

**Decision:** the `@`-palette surfaces **Roles**, not people (`@Finance`, `@CFO`). This is also the *correct* governance primitive — NIL routes/escalates by role, and the tenancy layer expands role→people at execution time. If per-person mentions are ever needed, they come from the control-plane tenancy layer in a later phase, not the brain. We label the category **"Roles"** in the UI (not "Users") to avoid implying we know individual people.

## 4. Data sources — real endpoints, auth, CORS

| Category | Source | Endpoint | Auth | CORS for browser? |
|---|---|---|---|---|
| **Verbs** | control plane (live handshake) | `GET /api/adapter-skeleton?workspace=&adapter_id=` → `{verbs:[...], targets:[...]}` | **Bearer `NIL_REGISTRY_TOKEN`** | ❌ none |
| **Active adapter** (to know which verbs) | control plane | `GET /adapters/active?workspace=` | **Bearer** | ❌ none |
| **Adapters** (list) | control plane | `GET /adapters?workspace=` → bearer redacted `***` | none | ❌ none |
| **Cycles** | control plane | `GET /cycles?workspace=` | none | ❌ none |
| **Cycles + entities** | brain | `GET /api/graph/cycles?tenant=` → members grouped by kind | none (open reads) | ✅ (`NILGRAPH_CORS`) |
| **Roles / entities** | brain | `GET /api/graph/nodes?tenant=` → filter `kind=="role"` / `"entity"` | none (open reads) | ✅ (`NILGRAPH_CORS`) |

**Two hard constraints fall out of this table:**

1. **The control plane has no CORS and its verb/adapter/active endpoints are token-gated.** The browser must **not** call it directly — that would either be blocked by CORS or leak `NIL_REGISTRY_TOKEN`.
2. The brain is browser-safe (CORS + open reads), but mixing "some categories via BFF, some direct" is inconsistent and complicates caching/tenant-scoping.

→ **Architecture decision: a single BFF aggregation endpoint.** wosool-hub already runs this pattern (Next rewrites `/brain/*`, `/hermes/*`, `/api/os/*`). We add one server-side route that fans out, injects tenant + `NIL_REGISTRY_TOKEN` server-side, and returns one categorized, already-shaped payload. The browser hits only that route.

## 5. Architecture

```
Browser (thread.tsx)
  └─ unstable_useMentionAdapter  ──fetch──▶  GET /api/os/mentionables   (Next.js BFF, same-origin)
                                                   │  injects tenant + NIL_REGISTRY_TOKEN server-side
                                                   ├─▶ CP  GET /adapters?workspace
                                                   ├─▶ CP  GET /adapters/active?workspace     (Bearer)
                                                   ├─▶ CP  GET /api/adapter-skeleton?ws&adapter (Bearer)  → verbs
                                                   ├─▶ CP  GET /cycles?workspace
                                                   └─▶ Brain GET /api/graph/nodes?tenant       → roles + entities
                                                   ◀── merged, categorized MentionPayload (cached ~30s)
  ◀─ popover renders categories ──▶ user picks ──▶ inserts "@verb:crm.create_lead " into composer text
                                                   ──▶ prompt.submit carries the directive to Hermes
```

### 5.1 Directive / insertion format

Insert a **namespaced, machine-parseable token** plus a human label, so both the model and any future parser can resolve it unambiguously:

| Category | Inserted text | Notes |
|---|---|---|
| Verb | `@verb:crm.create_lead` | scoped to active adapter |
| Adapter | `@adapter:pb-prod` | |
| Cycle | `@cycle:finance` | |
| Role | `@role:cfo` | governance primitive |
| Entity | `@entity:invoice` | optional |

The `unstable_useMentionAdapter` `directive.formatter` controls the rendered chip; `onInserted` lets us also stash structured metadata (see §5.2). Keep the raw `@ns:id` in the submitted text so Hermes sees it even if metadata is dropped.

### 5.2 What the mention *does* downstream (the point of the feature)

Two levels, ship incrementally:

- **Phase A (text-only, zero backend change):** the directive is just richer prompt text. Hermes already has the NIL skill/MCP; `@verb:crm.create_lead` in the prompt meaningfully steers it. This alone delivers the demo value.
- **Phase B (structured):** attach `metadata.custom.mentions = [{kind, id, label}]` on `prompt.submit` (the runtime already supports `metadata.custom`, see `MsgWithParts` at `thread.tsx:44`). Hermes/orchestrator can then bind `@verb`→a concrete proposal target and `@adapter`→routing, skipping re-discovery. Requires a small orchestrator change — defer until A is proven.

## 6. Implementation plan (phased, file-level)

### Phase 0 — BFF aggregation endpoint  *(backend, ~half day)*
- **New:** `wosool-hub/src/app/api/os/mentionables/route.ts` (or extend os-server if BFF logic lives there).
  - Read tenant from session (`sessionApi`) / `NEXT_PUBLIC_GRAPH_TENANT`; read `NIL_REGISTRY_TOKEN`, `CP_ORIGIN`, `BRAIN_ORIGIN` from server env.
  - `Promise.allSettled` fan-out to the 5 endpoints in §4. **Degrade gracefully** — if verbs 503 (adapter unreachable) still return adapters/cycles/roles; never fail the whole palette because one source is down.
  - Resolve active adapter first; only then request its skeleton for verbs. If no active adapter, return verbs: [] with a `notes` field the UI can show ("connect an adapter to see actions").
  - Shape → `MentionPayload` (below). Cache ~30s per tenant (in-memory or `revalidate`).
- **Response contract:**
  ```ts
  type MentionItem = { id: string; kind: "verb"|"adapter"|"cycle"|"role"|"entity";
                       label: string; sublabel?: string; insert: string /* "@verb:..." */ };
  type MentionPayload = { categories: { key: string; label: string; items: MentionItem[] }[];
                          notes?: string[] };
  ```

### Phase 1 — Frontend adapter + composer wiring  *(frontend, ~half day)*
- **New:** `wosool-hub/src/lib/mentionsAdapter.ts` — `useMentionables()` (fetch `/api/os/mentionables`, SWR/react-query, dedupe) → build `unstable_useMentionAdapter({ items: categorized, iconMap, onInserted })`.
- **Edit:** `thread.tsx` `Composer` (166-192) — wrap `ComposerPrimitive.Root` in `Unstable_TriggerPopoverRoot`, add `Unstable_TriggerPopover char="@"` bound to the adapter, render `TriggerPopoverCategories` + `TriggerPopoverItems`. Icon per kind (reuse lucide: `Zap` verb, `Plug` adapter, `Workflow` cycle, `Users` role, `Box` entity).
- Loading/empty states in the popover; keyboard nav is free from the primitive.

### Phase 2 — Polish  *(frontend, ~half day)*
- Style popover to match the dark composer (design-quality rules: intentional hover/focus/active, not a default dropdown). Grouped headers, kbd hints, RTL (`dir="auto"`) support for Arabic labels (brain labels are bilingual — pick `label.en`/`label.ar` by locale).
- Debounced client-side filter over the fetched set (payload is small; no server round-trip per keystroke).
- Optional: same adapter on `/` for slash-commands later (the primitive takes any `char`).

### Phase 3 — Structured downstream (Phase B above)  *(optional, backend)*
- Attach `mentions` metadata to `prompt.submit`; teach orchestrator to bind them. Gate behind proving Phase A.

## 7. Decisions already made (not asking)
- **"Users" → Roles.** No person entity exists; roles are the right governed primitive. Category labeled "Roles".
- **BFF aggregation, not direct browser calls.** Forced by CORS + token-gating on the control plane.
- **Namespaced directive tokens** (`@verb:id`) kept in the submitted text so the feature works with zero orchestrator change (Phase A).
- **Use the library's unstable mention API**, not a hand-rolled dropdown — it's already installed and handles caret/keyboard/positioning.

## 8. Open questions (worth a decision before Phase 3, not blocking Phase 0–2)
1. **Verb scope when multiple adapters exist:** show only the *active* adapter's verbs (recommended, matches execution reality) or union across adapters with adapter sublabels? Default: active-only.
2. **Should picking `@adapter:x` re-scope the verb list** to that adapter within the same `@` session? Nice-to-have; needs the popover to refetch. Defer.
3. **Per-person mentions** ever needed? Would require the control-plane tenancy layer (file 09) to expose a members endpoint — out of scope now.

## 9. Test plan
- **BFF:** unit-test the aggregator with each source up/down (allSettled degradation), token injection, tenant scoping, shape conformance. Mock CP + brain.
- **Frontend:** RTL of the mention popover — open on `@`, filter, category drill-down, insert → asserts composer text contains `@verb:crm.create_lead `. Keyboard nav (↑/↓/Enter/Esc). Empty/loading/one-source-down states.
- **E2E (Playwright):** type `@` on the home screen → popover visible → pick a verb → send → assert the outgoing `prompt.submit` text carries the directive.

## 11. What shipped (Phase A)

Built in `wosool-hub` (TDD, 14 unit tests, `tsc` clean, `next build` green, 133/133 suite):

- **BFF route** `src/app/api/mentionables/route.ts` — fan-out + `allSettled`-style graceful degradation, 4s per-source timeout, server-side token injection.
  **Path correction vs the plan:** it lives at **`/api/mentionables`**, NOT `/api/os/mentionables` — the latter is rewritten to os-server (and Caddy bypasses Next for `/api/os/*` in prod), so a handler there would never run.
- **Pure aggregator** `src/lib/mentionables/aggregate.ts` (+ `types.ts`, `toCategories.ts`) — verbs/adapters/cycles/roles/entities → ordered categories, empty ones dropped, dedup, bilingual label pick. Fully unit-tested (`*.test.ts`).
- **Client hook** `src/lib/mentionsAdapter.ts` — react-query fetch (30s stale) → `unstable_useMentionAdapter`.
- **Composer wiring** `src/components/assistant-ui/thread.tsx` — `Unstable_TriggerPopoverRoot` + `Unstable_TriggerPopover char="@"` with categories/items/back, one lucide icon per kind.
- **Env** (`.env.local`, server-only): `BRAIN_ORIGIN` (default `:8099`), `CP_ORIGIN` (blank ⇒ brain-only degrade), `NIL_REGISTRY_TOKEN`.

**Directive insertion confirmed:** assistant-ui's default formatter serializes to `:type[label]{name=id}`, e.g. selecting a verb inserts `:verb[crm.create_lead]` straight into the composer text → carried to Hermes via `prompt.submit` with **zero orchestrator change**.

**Still open:** set `CP_ORIGIN` + `NIL_REGISTRY_TOKEN` on the host to light up Verbs/Adapters/Cycles (brain Roles/Entities work already); optional Playwright E2E; Phase B structured `mentions` metadata.

## 10. Effort
- Phase 0 (BFF): ~0.5d · Phase 1 (wire): ~0.5d · Phase 2 (polish/tests): ~0.5d → **~1.5–2 days for a shippable `@`-palette** (Verbs/Adapters/Cycles/Roles), text-directive level (Phase A). Phase 3 is separate and optional.
