# Wave 4 §14.5 — cyc_order migration analysis (grounded in the live cycle)

> **Status:** ANALYSIS. Grounds the §14.5 migration in the *actual* `cyc_order` pulled from the live
> control plane (`/data/controlplane.db`, ws_acme), not an imagined cycle. Identifies exactly what maps
> cleanly onto the new Domain/Skill/BizSpec/compiler stack and the one concrete gap that must be closed
> first. Read after [NBEM-WAVE-4-CONSTITUTION](./NBEM-WAVE-4-CONSTITUTION.md).

## 1. The live cyc_order (runtime pipeline, `wosool/0.1`)

```
entry: step_1
step_1  action          resource.read
step_2  await_approval  timeout 24h
step_3  wait_for_event  mail.received  match {order_ref: $po}  timeout 7d  on_timeout→step_5  next→step_4
step_4  action          procurement.create_purchase_invoice
step_5  notify          "Escalate: supplier silent 7 days"        (next: null)
step_6  await_approval  timeout 24h
step_7  action          commerce.record_payment
step_8  notify          "Update GIT + notify logistics"           (next: null)
on_error: halt
```

Three effect verbs, under three skill namespaces: `resource.read`, `procurement.create_purchase_invoice`,
`commerce.record_payment`. Two human gates. One event-wait with a timeout escalation.

## 2. Target expression on the new stack

**Procurement Domain** (D2 imports + D8 bindings):
```
domain Procurement
  import Resource@1    as resource   bind Resource    → odoo
  import Procurement@1 as proc       bind Procurement → odoo
  import Commerce@1    as commerce   bind Commerce    → odoo
```

**Skills** (D3 semantic-first; each with a D5 envelope):
| Capability | Skill | resolves_to (verb) | tier |
|---|---|---|---|
| Resource | `read` | `resource.read` | LOW |
| Procurement | `createPurchaseInvoice` | `procurement.create_purchase_invoice` | HIGH |
| Commerce | `recordPayment` | `commerce.record_payment` | HIGH |

**BizSpec** (L2) — maps 1:1 for the linear spine:
```
bizspec in Procurement, intent "procure to pay"
  use resource.read                          bind po
  control approval  strategy OwnerApprove
  control wait      event mail.received  match {order_ref: $po}  timeout 7d   ← ⚠ needs escalation route
  use proc.createPurchaseInvoice
  control approval  strategy OwnerApprove
  use commerce.recordPayment
  control notify    message "Update GIT + notify logistics"
```

`compile_bizspec` + `lower_to_flow` already produce: the resolved verbs, the pinned versions, the odoo
backend on every effect, the aggregate envelope (HIGH IRREVERSIBLE), and a runnable Cycle that
round-trips through `print_nil`. **The linear spine migrates cleanly today.**

## 3. The one concrete gap — non-linear timeout routing

`cyc_order` step_3 is `wait … on_timeout→step_5` where **step_5 is an escalation notify, not the end**.
The current v0.1 lowering routes every `wait`/`approval` reject/timeout to the synthesized terminal
`Done` (§14.4c) — it is **linear + terminal only**. So it cannot yet express "if the supplier is silent
7 days, escalate (notify) and stop" as distinct from "proceed."

This is a **design gap, not a bug**: L2 must stay free of runtime scaffolding (no step ids / `next`
targets — §11), so the fix is *not* to add `on_timeout: "step_5"` to the BizSpec. The clean options:

- **A — inline escalation (recommended):** a control step carries an optional business-level
  `on_timeout` *action* (e.g. `wait … else notify "…"`), and the compiler synthesizes the branch +
  targets. Keeps L2 business-level; the routing scaffolding stays synthesized.
- **B — named outcomes:** BizSpec declares named terminal outcomes (`escalated`, `done`) and control
  steps route to an outcome by name; the compiler maps outcomes → synthesized terminal steps.
- **C — sub-flows:** a control step owns a small nested step list for its timeout path.

Option A is the smallest and most in keeping with D4 (control flow explicit, business-level).

Also minor (cosmetic parity, not blocking): the live gates use `on_rejected: null` / `on_timeout: null`
(halt) whereas the lowering routes them to `Done`; both halt the run, but a faithful parity pass should
let a control step opt into "halt" vs "route to terminal."

## 4. §14.5 plan

1. **Close the routing gap** — implement Option A: `ControlStep.on_timeout` (a business action:
   notify/escalate), `lower_to_flow` synthesizes the branch + target. Tests + round-trip.
2. **Author** the Procurement Domain + the three capabilities' Skills (extend `seed_catalog.py`),
   registered through the §14.2 gate.
3. **Express** cyc_order as a BizSpec; compile+lower it.
4. **Prove parity** — assert the lowered pipeline's effect verbs, gate positions, and the wait/escalation
   routing match the live cyc_order (same effects, same Cards, same escalation).
5. **Make verbs private** once parity holds — the registry/compiler reject a direct verb reference.

Until step 1 lands, a *faithful* cyc_order migration is blocked; the linear spine is already provable.
This analysis is the grounding — the actual migration is the next focused unit.
