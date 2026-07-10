# Governed dependent plans (ordered, linked approval cards)

**Problem:** "invoice for a NEW client Ahmed Co" decomposes into create-client (MEDIUM → auto-commits
silently) + create-invoice (HIGH → card). The client is created before the invoice is approved →
orphan risk, no link, no ordering. There is NO plan/dependency concept in the gate today.

**Decision (user, 2026-07-01):**
- **Ordered, step-by-step**: two linked cards; the prerequisite (client) card is FIRST, the dependent
  (invoice) card is BLOCKED until the prerequisite is approved+committed. Reject either → whole plan
  cancelled (no orphan). Approving the prerequisite feeds its real id into the dependent.
- **Card-when-part-of-a-plan**: a create that would be MEDIUM (auto) standalone becomes a visible,
  held card when it is a prerequisite step inside a gated plan.

## UNIVERSAL by construction

Plan grouping, ordering, blocking, and the ordered executor live entirely in the **kernel (MCP gate)
+ control-plane + UI** — adapter-agnostic. NO adapter carries plan logic. The only per-adapter input
is the already-universal `WriteVerb.references` declaration. So EVERY adapter (odoo, daftara,
pocketbase, erpnext, future) gets dependent-plan governance for free.

## Integration contract (the ONE interface all surfaces share)

A pending approval item (`GET /api/pending` → `pending[]`, and the os-server BFF passthrough) MAY carry:

```
plan_id:    string | null   // items sharing a plan_id are ONE plan
seq:        number           // 0-based order within the plan
depends_on: string | null   // proposal_id of the prerequisite step this one needs committed first
blocked:    boolean          // true while depends_on is pending/rejected (not yet committed)
```

- Standalone proposals keep `plan_id=null` (unchanged behavior).
- The UI groups by `plan_id`, orders by `seq`, renders the prerequisite first, shows a "depends on
  <prereq>" badge on dependents, and DISABLES Approve while `blocked=true`.
- Approving a prerequisite commits it; on the next pending read its dependents have `blocked=false`.
- On the dependent's commit, the control-plane executor resolves any handoff reference to the
  prerequisite's committed id (e.g. invoice.client_id ← the client's new id) — mirrors the composed
  automation `$.input.X` handoff.

## Agent surface

A new MCP `nil_plan(steps)` (or a `then`/`plan` extension of nil_intent): steps are ordered; a later
step may reference an earlier step's output via `$.step<i>.<field>` (default `$.step0.id`). The kernel
proposes each step against the active adapter, then registers ALL of them as one linked plan in the
control plane (holding every step, including MEDIUM ones, because they belong to a gated plan). The
NIL skill instructs the agent to use `nil_plan` whenever a write needs a brand-new referenced entity.
