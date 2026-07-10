# PLAN — Cycles page → SaaS-grade UX

**Status:** PLAN (council-backed). Not yet implemented.
**Date:** 2026-06-30
**Trigger:** Founder ask — "deeply enhance cycles page SaaS-grade; council it, audit what exists, plan it."
**Source:** 5-advisor LLM council (Contrarian, First Principles, Expansionist, Outsider, Executor).

---

## 1. What exists today (audit)

Files (`wosool-hub`):
- `src/app/cycles/page.tsx` (168) — **list**: cards = name · status dot (Inactive) · `5 nodes · v1 · 0 triggers` · `cyc_3144b4d9` · Edit/Run/delete. Header "Business Cycles — Define and manage your business process cycles" + Refresh + New Cycle.
- `src/app/cycles/[id]/page.tsx` (271) — **editor**: 3 panes — left `Node Palette` (search verbs; "No adapters connected"), middle dotted canvas with node cards (`Create Lead in Odoo / crm.create_lead`, `Log Note in Odoo / crm.log_note`) + edges, right properties ("Select a node to edit its properties"). Header: name · id · v1 · node count · Inactive · Run/Save.
- `src/app/cycles/new/page.tsx` (115), `src/app/cycles/runs/page.tsx` (192).
- `src/components/workflow/`: NodePalette, NodeEditor, WorkflowNode, WorkflowEdge, GateIndicator, ActorBadge, NotificationEditor. Custom canvas (not react-flow).

Backend: cycles have nodes (verb e.g. `crm.create_lead`), versions, triggers; agent executes governed (preview/approve/reversible) via the brain/control-plane.

---

## 2. Council verdict

### Agreements (high confidence)
1. **De-jargon everything.** nodes/v1/triggers/`cyc_*`/`crm.create_lead`/"Node Palette"/"No adapters connected" leak internals. Speak outcomes ("runs when X · does Y").
2. **Trust-first.** Run with no **dry-run/preview** and no **run history** is the top trust-killer for a *governed* product. Show "what will change" before commit, "what happened" after.
3. **Fix dead UI.** Empty properties pane, dead palette text, plain node cards → humanized cards (adapter icon + readable verb + status ring), guided empty states.
4. **Disable, don't delete**; show last-run status on every card.

### Clash
- **Canvas vs plain-rules as the PRIMARY surface.** First Principles: lead with plain-language rule view + run history (canvas is cargo-culted). Expansionist: make the canvas iconic with live execution. **Resolution:** plain-language is the default lens; canvas is the live-execution/transparency lens; **agent co-author** bridges them.

### Blind spots
- "0 triggers" with no UI to add triggers (schedules/webhooks/events).
- "v1" versioning theater — no diff/rollback.

---

## 3. The reframe

**"Trustworthy automations," not a circuit board.**
- **Default lens:** plain-language automation cards + a real **activity/run log**.
- **Power lens:** the canvas — now the **live-execution + transparency** view (nodes animate idle→evaluating→preview→approved→committed; inline approval cards).
- **Mandatory:** **dry-run** before first live run (shows before/after diff on real systems, zero commit).
- **Onboarding moment:** **agent co-author** — "describe what you want" → agent drafts the cycle.

---

## 4. Phased roadmap (Executor's path, council-prioritized)

### Phase 1 — first impression (≈1 day, pure frontend, zero backend risk) — DO FIRST
1. **Node cards** (`workflow/WorkflowNode.tsx`): humanize verb (`crm.create_lead` → "Create Lead · CRM"), adapter icon, status ring (idle/running/error), subtle depth. *(the one thing to do first)*
2. **Palette** (`workflow/NodePalette.tsx`): group verbs by adapter under collapsible headers; replace "No adapters connected" dead text with a **"Connect an adapter →"** CTA (links to Connect tab).
3. **List cards** (`cycles/page.tsx`): plain-language summary line ("Runs when … · does …"), status badge (dot+label), **last-run** timestamp, hover row-actions (Run/Edit/Duplicate); demote `cyc_*` id to a tiny copy-on-hover; **Disable** instead of (or alongside) delete.
4. **Empty states** (list + runs + editor): centered prompt + primary CTA ("Create your first automation" / "Select a step to edit, or drag one in").
5. **Inline validation** (`cycles/[id]/page.tsx`): red outline + tooltip on Save when required fields empty; block Run on invalid.

### Phase 2 — real value (≈1 week)
6. **Properties panel** (`workflow/NodeEditor.tsx`): render each verb's schema as typed inputs (string/select/number); auto-save on blur.
7. **Run preview drawer** (`cycles/runs` + `cycles/[id]`): side panel = agent reasoning + node-by-node **proposed actions** + Approve/Reject. Needs `POST /api/os/cycles/{id}/preview` (dry-run) on os-server → brain/control-plane.
8. **Gate indicator wired** (`workflow/GateIndicator.tsx`): show real gate policy (human-approve vs auto) per node from backend.
9. **Triggers UI**: surface add-trigger (schedule/webhook/event) — close the "0 triggers" dead-end.

### Phase 3 — premium (next sprint)
10. **Live run visualization**: poll/stream run state; highlight the active node on the canvas; stream the agent log. (Governance as the main character.)
11. **Dry-run mode**: "Test without committing" → preview with `dry_run=true`, before/after diff of real-system changes.
12. **Agent co-author**: "Describe what you want" → agent proposes the cycle (nodes) → user confirms. Onboarding delight; do last.
13. **Versioned diffs**: snapshot per save; side-by-side canvas diff (added=green/removed=red/changed=amber); rollback.

---

## 5. Open decisions for the founder
1. **Primary surface:** plain-language-first (recommended) vs keep canvas-first? (affects Phase 1 scope)
2. **Scope now:** Phase 1 only (1 day, big perceived jump) vs Phase 1+2?
3. **Dry-run backend:** is there a preview/dry-run path in the brain/control-plane to wire, or does that need building first?
