# NIL DSL — Comparative Study & Deep Upgrade Plan
## What to borrow from the world's DSLs · what NIL already has · the real delta

**Status:** Research + plan. Drafted 2026-07-06 · **grounded in `cycle/projections/`, `cycle/lsp.py`,
`nil_printer.py`.** · **Companion:** [NIL-DSL-CONSTITUTION.md](./NIL-DSL-CONSTITUTION.md) ·
NBEM corpus (`wosool-hub/docs/NBEM-*.md`).

> **The reframing.** The instinct is "study the great DSLs and *become* them." The finding, from the
> code, is stronger: **NIL already embodies most of the synthesis.** It has code↔visual projection, a
> text→Mermaid graph, a docs projection, a **simulation/dry-run**, an LSP (diagnostics, verb-aware
> completion, hover), round-trip trust, and declarative governance. So this is not a rewrite — it is a
> **completion**: borrow the few things NIL lacks, and sharpen the thesis it is already living.
>
> **The thesis (correct, and already ~75% built):** NIL is **the HTML of governed business execution** —
> one canonical source, projected into many views (runtime · thread-state · canvas · graph · docs ·
> simulation · audit · LSP).

---

## 1. NIL is already the projection engine the thesis describes `[grounded]`

The "HTML → many renders" idea is not aspirational for NIL — it is shipped:

| Thesis capability | NIL today | Where |
|---|---|---|
| Canonical source ⇄ visual (HTML-like) | `.nil` ⇄ **canvas** (round-trippable) | `nil_printer`/`nil_parser`; hub `SourceTab`/`CanvasTab` |
| Text → graph (Mermaid) | **`to_mermaid(cycle)` → `flowchart TD`** | `cycle/projections/mermaid.py`; hub `CycleFlowDiagram` |
| Docs projection | **`to_markdown(cycle)`** | `cycle/projections/docs.py` |
| Simulation / dry-run ("preview what will happen") | **`simulate(cycle)`** (proposes only) | `cycle/projections/simulate.py` |
| Governance projection | **governance view** | `cycle/projections/governance.py` |
| LSP (diagnostics, completion, hover) | **`diagnostics` · `completions` (verb-aware) · `hover`** | `cycle/lsp.py` |
| Declarative validation | `extra="forbid"`, validators, dead-reference diagnostics | `cycle/models.py`, `compile.py`, `lsp.py` |
| Round-trip trust | `parse_nil(print_nil(c)) == c` | the printer/parser contract |

**Implication:** the right posture is *pride + completion*, not reinvention. The rest of this document
is the honest **delta** against each inspiration.

---

## 2. The comparative study — lesson · what NIL has · the delta

For each inspiration: the one thing to borrow, where NIL **already** has it `[have]`, and the precise
**gap** `[gap]` to close.

### 2.1 BPMN 2.0 — *business semantics* (the closest business language)
- **Borrow:** events, gateways, timers, human tasks, message events — the shared vocabulary of process.
- **`[have]`** NIL covers most 1:1 — event trigger, `decision` (exclusive gateway), timeout (timer),
  `await approval` (user task), `wait_for_event` (message event), `checkpoint` (compensation boundary).
- **`[gap]`** **Parallel gateway (fan-out/join)** and **sub-process** (see 2.4). Everything else is
  present; **do NOT borrow BPMN's XML** — NIL's text is the point (this is the Bicep lesson, 2.12).

### 2.2 Terraform / HCL — *clean declarative blocks*
- **Borrow:** readable block syntax, typed, simple, diffable.
- **`[have]`** NIL is already block-structured (`cycle X { … step Y { … } }`), text-diffable, typed via
  the AST. This is a solved dimension.
- **`[gap]`** Minor: HCL-style *interpolation ergonomics* — NIL's `$name` refs are good; could add
  richer expression typing (ties to 2.10 Rust).

### 2.3 GitHub Actions YAML — *instant readability*
- **Borrow:** the "anyone can read the steps" quality.
- **`[have]`** NIL steps read linearly and route explicitly — arguably *more* legible than YAML
  (no significant-whitespace traps) and bilingual.
- **`[gap]`** None structural; a lesson in **keeping the common case terse** (don't let governance
  boilerplate bury the flow — the canonical printer already elides defaults).

### 2.4 Temporal — *durable execution primitives* (the runtime twin)
- **Borrow:** `await`, `signal`, `sleep`, `continue`, **child workflow**.
- **`[have]`** `await approval` (await), `wait_for_event` (signal-ish + sleep via timeout), park/resume
  (durable continue), `compensate_with` (saga). NIL's runtime *already feels Temporal-like*.
- **`[gap] ⭐ Child workflow = sub-cycle invocation.** NIL cycles compose **verbs** only; a step that
  **invokes another Capability/Cycle and awaits it** does not exist. **This is the #1 language gap**
  (NBEM P16 / gap-plan **W5** / DSL-constitution §8.2). Also: a first-class **`signal`** (external nudge
  to a running thread distinct from a world-event) is worth separating from `wait_for_event`.

### 2.5 AWS Step Functions — *orchestration semantics*
- **Borrow:** Wait, Choice, **Retry, Catch, Parallel**.
- **`[have]`** Wait (`wait_for_event`/timeout), Choice (`decision`), **Retry** (`retry {}`), **Catch**
  (`on_error`).
- **`[gap]`** **Parallel** (fan-out + join). Same gap as BPMN's parallel gateway — the one control-flow
  primitive NIL lacks. (Reject Step Functions' JSON syntax — the Bicep lesson again.)

### 2.6 Mermaid — *text → diagram*
- **Borrow:** one-click render of the source to a graph.
- **`[have]` FULLY.** `to_mermaid(cycle)` emits a deterministic `flowchart TD`; the hub renders the
  canvas/`CycleFlowDiagram`. This is done.
- **`[gap]`** Polish: state-colored diagrams for a *running Thread* (overlay live state on the graph) —
  a projection of the Thread, not just the Cycle.

### 2.7 HTML — *code ↔ visual projection* (the north-star analogy)
- **Borrow:** one declarative source, the renderer produces the view; edit either, they stay in sync.
- **`[have]`** The round-trippable `.nil` ⇄ canvas *is exactly this*. NIL is already "the HTML of
  business execution" in mechanism, not just metaphor.
- **`[gap]`** Complete the projection set (audit projection; live-thread canvas) so *every* view derives
  from the one source — the thesis, fully realized.

### 2.8 Kubernetes — *declarative desired state*
- **Borrow:** declare the desired *what*; a controller reconciles the *how*.
- **`[have]`** Partial: NIL declares intent + **`policies`** (desired governance constraints) +
  **`outcomes`** (valid terminal states) — declarative *goals* alongside the flow.
- **`[gap] / decision`** NIL is **flow-primary** (explicit `next` routing), not pure desired-state.
  **This is correct for business execution** — audit and governance *need* the explicit sequence (you
  must prove *the order* things happened). The K8s lesson to adopt is **more declarative constraints
  around the flow** (policies-as-desired-state, outcome goals), **not** replacing the flow with
  reconciliation. See §4-D1.

### 2.9 SQL — *describe what, not how*
- **Borrow:** the operation declares intent; the engine/adapter decides execution.
- **`[have]`** A step says `use odoo.create_purchase_invoice { … }` (the *what*); the **adapter**
  performs the *how* (P13). NIL already separates declaration from execution.
- **`[gap]`** None fundamental; keep resisting "how" leaking into `.nil` (no inline scripts).

### 2.10 Rust — *make illegal states impossible* (philosophy, not syntax)
- **Borrow:** push errors to compile time; unrepresentable = safe.
- **`[have]`** NIL already does a lot: `extra="forbid"`, `implemented_by` must be a cycle id,
  IRREVERSIBLE-by-default, dangling/dead-reference diagnostics, a deadline without a route is
  *unrepresentable* (printer comment).
- **`[gap] ⭐** Deepen the guarantees so the user's example — *"approve without an approval policy →
  compiler error"* — actually holds. Candidate compile-time rules: a **consequential/HIGH effect not
  behind an `await approval`** → error/warn; an **IRREVERSIBLE effect with no catch/approval** → error;
  **verb args type-checked against the adapter contract** (arity/types); **unreachable steps** → error;
  **a `match`/`$ref` to an unbound variable** → error. This is the highest-leverage *quality* upgrade.

### 2.11 React JSX — *component → state → render*
- **Borrow:** the mental model *definition → state → rendered view*.
- **`[have]`** Cycle (component) → Thread state → rendered case file/console *is this pattern*.
- **`[gap]`** Mostly conceptual; the "live-thread canvas" (2.6) is the JSX-like re-render of state.

### 2.12 Bicep — *a readable DSL over an ugly standard*
- **Borrow:** be to BPMN/Step-Functions-JSON what Bicep is to ARM XML.
- **`[have]`** NIL *is* already the readable text form; BPMN/JSON are the "compile targets/imports" at
  most.
- **`[gap]`** Optional: **import/export bridges** — parse a BPMN/DMN subset in, emit BPMN out — for
  interop with existing BPM tools (a go-to-market lever, not a core need).

### 2.13 Open Policy Agent (OPA) — *externalized governance*
- **Borrow:** policy as reusable, testable, externally-authored modules.
- **`[have]`** NIL has **in-language `policies`** (`policy … when … raises_tier …`) + runtime tiers/
  reversibility/approval.
- **`[gap] / decision`** Whether to **externalize** policy (reusable policy library, à la OPA/Rego)
  vs keep it inline. Recommendation: **inline for readability, referenceable for reuse** — a `policy`
  can name a shared, versioned policy in a registry (best of both). See §4-D2.

### 2.14 VS Code LSP — *rich dev experience*
- **Borrow:** IntelliSense, diagnostics, hover, rename.
- **`[have]`** `diagnostics`, **verb-aware `completions`**, `hover` already exist (`lsp.py`).
- **`[gap]`** **Rename refactoring**, **go-to-definition** across steps/verbs, **signature help** for
  verb args (needs the adapter contract, ties to 2.10), and hover showing a verb's tier/reversibility.

---

## 3. The synthesized target (what NIL becomes when the delta closes)

> **NIL = one canonical `.nil` source → projected into: the execution runtime · live Thread state · the
> visual canvas · a Mermaid graph · human docs · a governed simulation · an audit trail · full LSP —
> with Rust-grade compile-time guarantees, Temporal-grade durable primitives (incl. child cycles &
> parallelism), and OPA-informed, referenceable governance.**

Most of that clause is already true. The words that are *not yet* true: **child cycles · parallelism ·
the deeper compile-time guarantees · signature-level LSP · the live-thread canvas & audit projection ·
referenceable policy.** That is the entire upgrade surface — and it is small relative to what exists.

---

## 4. Key design decisions (resolve before building)

**D1 · Flow-primary vs desired-state (K8s/SQL pull).** → **Keep flow-primary.** Business execution must
prove *the sequence and the gates* for audit (NBEM P15); a reconciler that "figures out how" cannot
produce a defensible Timeline. **Borrow declarativeness around the flow** — richer `policies`
(desired constraints) and `outcomes` (goal states) — not instead of it.

**D2 · Inline vs externalized policy (OPA pull).** → **Both, layered.** Keep `policies` inline for
readability; let a `policy <id>` *reference* a shared, versioned policy module in the registry for reuse
and central compliance. Inline is the default; reference is the escape hatch for org-wide rules.

**D3 · How hard to push "illegal states impossible" (Rust pull).** → **Tiered.** Ship the high-value
compile rules as **errors** (unreachable step, unbound `$ref`, dangling route — some already exist) and
the judgment ones as **warnings** first (consequential effect not gated; irreversible without catch),
promoting to errors once teams trust them. Never make a *warning* block authoring (keep the round-trip).

**D4 · New control-flow primitives (Temporal/BPMN/SF pull).** → Add **two**, additively (never break the
frozen core): **`invoke` (child cycle)** and **`parallel`/`join` (fan-out)**. Keep each 1:1 with a new
AST node + printer/parser inverse + a Mermaid/simulate/docs projection (the projection contract is the
gate for any new construct).

---

## 5. The upgrade roadmap (prioritized, folded into NBEM/DSL plans)

Ordered by leverage; each ties to the gap plan.

1. **Deepen compile-time guarantees (Rust) — `[quality, do first]`.** Add the error/warn rules in §2.10
   / D3. Highest safety-per-effort; no new syntax. *(NBEM Inv. 1/4/9; DSL-constitution §6.)*
2. **Signature-level, verb-aware LSP — `[quality]`.** Type-check `with {}` args against the adapter
   contract; hover shows verb tier/reversibility; add rename + go-to-def. *(pairs with #1.)*
3. **`invoke` — child-cycle composition — `[the #1 feature]`.** A step invokes another Capability's
   cycle and awaits it. Unlocks P16 / **W5**. New AST node + printer/parser + projections. *(DSL §8.2.)*
4. **`parallel`/`join` — fan-out — `[feature]`.** The one missing control primitive (BPMN/SF). Additive.
5. **Live-thread projections — `[thesis completion]`.** State-colored Mermaid of a *running* Thread + an
   **audit-trail projection**, so every view derives from the one source (the HTML thesis, finished).
6. **Referenceable policy (OPA) — `[governance]`.** `policy <id>` may reference a shared registry module.
7. **First-class `signal` + unified event triggers — `[feature]`.** Separate an external signal from a
   world-event; make event-trigger sugar first-class. *(NBEM W9.)*
8. **BPMN import/export bridge — `[interop, optional]`.** Parse a BPMN subset in / emit BPMN out.

**Continuous invariant for every item:** preserve `parse_nil ⇄ print_nil` as exact inverses, keep every
new construct 1:1 with the AST, and ship a Mermaid + simulate + docs projection for it. **The projection
round-trip is the definition of "done" for a language change** — that is what keeps NIL the HTML of
business execution rather than drifting into a pile of features.

---

## 6. The one-line strategy

**Do not rebuild NIL to imitate these languages — it already unifies most of them.** Borrow the *few*
missing pieces (child cycles, parallelism, deeper compile guarantees, signature LSP, live projections,
referenceable policy), hold the line on the thesis (one governed source → many projections), and NIL
becomes what none of the twelve individually are: **the canonical, governed, projectable language of
business execution.**

---

*Companion: [NIL-DSL-CONSTITUTION.md](./NIL-DSL-CONSTITUTION.md) · Architecture:
`wosool-hub/docs/CAPABILITIES-VERBS-CYCLES-ARCHITECTURE.md` · Roadmap:
`wosool-hub/docs/NBEM-GAP-PLAN.md` (W5) · Thesis: `wosool-hub/docs/NBEM-CONSTITUTION.md`.*
