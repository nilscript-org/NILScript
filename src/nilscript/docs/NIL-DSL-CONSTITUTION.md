# The NIL DSL Constitution & Language Reference
## The `.nil` cycle language — spec · authoring discipline · natural-language → NIL (skill-ready)

**Status:** Foundational language reference. Drafted 2026-07-06 · **grounded in `cycle/nil_printer.py`
+ `cycle/models.py` (the canonical form).** · **Companion NBEM corpus:**
`wosool-hub/docs/NBEM-CONSTITUTION.md`, `…/NBEM-ONTOLOGY.md`,
`…/CAPABILITIES-VERBS-CYCLES-ARCHITECTURE.md`.

> **Purpose.** This is the constitution of the **`.nil` cycle language** — the DSL a business uses to
> declare a **Business Cycle**. It is deep enough to become a **skill**: an agent that absorbs this can
> take a user's plain-language description of their operations ("when a low-stock alert fires, get a
> quote, have the owner approve, then order") and author **valid, governed `.nil`** — then verify it by
> round-trip (`parse_nil`). Everything here is grounded in the actual printer/parser, which are exact
> inverses (`parse_nil(print_nil(c)) == c`) — so if you follow this grammar, the compiler accepts it.

---

## 1. What the NIL DSL is (and is not)

- **It is** the textual authoring form of a **Cycle** (the blueprint; see the ontology). One `.nil`
  file = one Cycle. It is **1:1 with the frozen Cycle AST** — every surface construct maps to exactly
  one AST node; every AST field prints as exactly one token. There is no syntax without a model.
- **It is round-trippable and deterministic** — `print_nil(parse_nil(text)) == text` for canonical text.
  This is the trust contract: an agent can author `.nil`, parse it to validate, and re-print to confirm.
- **It is governed by construction** — the language can only express governed operations: verbs are
  two-step (PROPOSE→COMMIT under the hood), approvals are first-class gates, effects can declare
  compensation, long waits are explicit. You cannot write an ungoverned effect in `.nil`.
- **It is bilingual** — human-facing text carries Arabic + English by a strict bijection.
- **It is NOT** the NIL wire protocol (PROPOSE/COMMIT performatives — that is the runtime), and NOT a
  general programming language. It declares an operation's **shape, governance, and flow** — the kernel
  executes it.

**Dialect note:** v0.2 is the frozen core; **v0.3 is additive** — `wait_for_event`, `checkpoint`, and
`implements` (a cycle declaring the capability it fulfils). Use only these constructs; nothing else is
valid.

---

## 2. The design laws of the language (why it is shaped this way)

These tie the syntax to the platform constitution — an agent should *understand* them, not just emit:

1. **One construct per concept** — no two ways to say a thing (keeps it round-trippable and
   learnable). *(canonical form)*
2. **Verbs are the only effects** — a step `use`s a verb; you cannot inline a capability or a raw API
   call. Atoms are verbs. *(NBEM P12/P13; see CAPABILITIES-VERBS-CYCLES-ARCHITECTURE.md)*
3. **Governance is expressible and unavoidable** — approvals (`await approval`), policy tiers
   (`raises_tier`), reversibility (`compensate_with`) are language constructs, not afterthoughts.
   *(NBEM P9)*
4. **Waiting is first-class** — `wait_for_event` and approval timeouts (up to 2,592,000 s ≈ 30 days) are
   syntax, because real operations wait. *(NBEM P14)*
5. **Everything routes explicitly** — every step names its `next` / `on approve` / `on_true` /
   `-> route`. Control flow is a readable graph, never implicit fall-through.
6. **Human text is bilingual and separated from logic** — `intent`, `notify`, approval `title` carry
   ar/en; identifiers and verbs are machine tokens. *(product is ar/en)*

---

## 3. The grammar (canonical, complete)

The full shape of a `.nil` cycle. `[...]` = optional; `*` = repeatable; `<x>` = a value.

```nil
cycle <cycle_id> [implements <Capability>@<major.minor[.patch]>] <trigger> {
  workspace "<workspace_id>"
  intent <bilingual>
  meta { version: "<semver>"; owner: "<owner>"[; description: <bilingual>][; tags: ["<t>", ...]] }

  [ let <name> = <expression>; ]*                         # cycle variables (bindings)

  [ context {                                             # the entities this cycle acts on
      <name>: <entity_type> [(role: <role>)];             #   e.g.  vendor: Vendor (role: supplier);
      ...
  } ]

  [ roles { <role>, <role>, ... } ]                       # roles referenced by approvals/policies

  [ policies {                                             # governance rules
      policy <policy_id> [applies_to [<stepId>, ...]] [when "<condition>"] [raises_tier <TIER>]
      ...
  } ]

  [ resources ["<res>", ...] ]                            # declared resource scopes

  flow entry <stepId> {                                   # the executable plan; `entry` = first step
      step <id> { <one step body> }                       # (see §4 for each step type)
      ...
  }

  [ outcomes { <name> [when "<expr>"]; ... } ]            # named terminal outcomes
  [ documentation <bilingual> ]
}
```

**Triggers** (the header after the cycle id / `implements`):

```nil
triggers manual                                           # fired by a person / a prepared-card commit
triggers_on <verb> [where (on_event <e>; source_adapter "<a>"; match { k: v })]   # event-driven
triggers schedule { cron: "<expr>"; interval_seconds: <N>; timezone: "<tz>" }     # time-driven
```

**Bilingual text** (strict bijection):

```nil
"text"                     # ar == en (same string both languages)
{ ar: "نص" }               # Arabic only
{ ar: "نص"; en: "text" }   # both, distinct
```

**Values** are canonical JSON scalars/containers (`{ qty: 5, sku: "SSD-2TB", tags: ["a"] }`).
**Variable references** use a `$` prefix inside arg maps / match / conditions (`order_ref: "$po"`).

---

## 4. Every step type — form, meaning, when to use

A `flow` contains `step <id> { … }` blocks. There are **seven** step bodies:

### 4.1 `action` — do a governed effect (the workhorse)
```nil
step CreateInvoice {
  use odoo.create_purchase_invoice { vendor: "$vendor", amount: "$total" }
  [ retry { max_attempts: 3; backoff: "exponential"; initial_seconds: 5 } ]
  [ on_error compensate [-> <stepId>] ]        # or: on_error halt / retry / continue
  [ compensate_with odoo.cancel_invoice { id: "$invoice_id" } ]   # the saga inverse
  [ output invoice ]                            # bind the result to a variable
  [ next Notify ]                               # the continuation step
}
```
*Use for:* any state-changing backend action. `compensate_with` makes it reversible (Saga). `output`
captures the result for later `$`-references. **This is the only construct that changes the world.**

### 4.2 `query` — read data (no side effect)
```nil
step ReadStock { query odoo.read_product { sku: "$sku" } output stock next Decide }
```
*Use for:* reading rates, entities, current state to branch on. Same `use`/`with`/`output`/`next` shape
as `action`, minus the error/compensation tail (reads don't compensate).

### 4.3 `decision` — branch on a condition
```nil
step Decide { decision when "$stock.qty < $reorder_point" on_true Order on_false Done [next X] }
```
*Use for:* conditional flow. `when` is a guard expression over bound variables.

### 4.4 `await approval` — a first-class human gate (maker-checker)
```nil
step Approve {
  await approval {
    title: { ar: "اعتماد الشراء"; en: "Approve purchase" };
    [ description: <bilingual>; ]
    approver: owner;                 # a role/context actor
    timeout_seconds: 86400
  }
  on approve -> Order
  [ on reject -> Rejected ]
  [ on timeout -> Escalate ]
}
```
*Use for:* every point a human must decide. The gate **is** the node; the run parks here until decided
(SoD enforced at runtime). Route all three exits explicitly.

### 4.5 `wait_for_event` — park until the world responds (v0.3)
```nil
step AwaitReply {
  wait_for_event {
    on_event: "mail.received";
    [ match { order_ref: "$po" }; ]         # correlate to THIS operation
    timeout_seconds: 345600 -> route Remind  # deadline + its route on ONE line (required)
  }
  [ output reply ]
  [ next Process ]
}
```
*Use for:* waiting on an inbound email/WhatsApp/webhook. `match` is the correlation filter; the arriving
event's payload binds to `output`. This is how a cycle waits days for a vendor.

### 4.6 `checkpoint` — a compensation boundary (v0.3)
```nil
step OrderPlaced { checkpoint "order-placed" [next Track] }
```
*Use for:* marking a per-phase rollback boundary (no pause) so a later rollback unwinds cleanly.

### 4.7 `notify` — inform (governed send is a verb; this is a lightweight message)
```nil
step Done { notify { ar: "تم الطلب"; en: "Order placed" } [next X] }
```
*Use for:* a simple notification in the flow. (A *governed* email/WhatsApp send to a party is an
`action` using a comms verb, not `notify`.)

---

## 5. A complete worked example (annotated)

A minimal procurement-style cycle showing header, governance, a wait, and routing:

```nil
cycle procurement_order implements RunProcurementOrder@1.0 triggers manual {
  workspace "ws_acme"
  intent { ar: "تشغيل أمر شراء محوكم"; en: "Run a governed procurement order" }
  meta { version: "1.0"; owner: "operations"; tags: ["procurement"] }

  let po = "$input.order_ref"

  context { vendor: Vendor (role: supplier); }
  roles { owner }

  flow entry ReadStock {
    step ReadStock { query odoo.read_product { sku: "$input.sku" } output stock next Approve }

    step Approve {
      await approval {
        title: { ar: "اعتماد الشراء"; en: "Approve purchase" };
        approver: owner;
        timeout_seconds: 86400
      }
      on approve -> SendRFQ
      on reject -> Rejected
    }

    step SendRFQ {
      use comms.send_email { to: "$vendor.email"; subject: "RFQ"; reply_token: "$po" }
      next AwaitQuote
    }

    step AwaitQuote {
      wait_for_event { on_event: "mail.received"; match { order_ref: "$po" }; timeout_seconds: 345600 -> route Remind }
      output quote
      next Invoice
    }

    step Invoice {
      use odoo.create_purchase_invoice { vendor: "$vendor.id"; amount: "$quote.amount" }
      compensate_with odoo.cancel_invoice { id: "$invoice.id" }
      output invoice
      next Done
    }

    step Remind  { notify { ar: "تذكير للمورد"; en: "Vendor reminder" } next AwaitQuote }
    step Rejected{ notify { ar: "رُفض الطلب"; en: "Order rejected" } }
    step Done    { notify { ar: "اكتمل الطلب"; en: "Order complete" } }
  }

  outcomes { completed when "$invoice != null"; rejected; }
}
```

Read it as the operation it is: read stock → **owner approves** → send RFQ (governed, reply-token) →
**wait up to 4 days** for the vendor → create the invoice (**reversible**) → done; a rejection and a
reminder path are explicit. Every effect is a verb; every human point is a gate; the wait is first-class.

---

## 6. Authoring discipline (what makes valid, *good* NIL)

An agent must obey these or produce invalid/anti-pattern NIL:

- **Every effect is a `use <verb>`** — never invent an action; use a verb the adapter declares
  (discover them, don't guess). Unknown verb → the cycle won't register.
- **Route everything** — no step without an exit (`next` / `on … -> …` / `-> route`). A dangling step is
  a validation error.
- **Gate the risky** — any HIGH/CRITICAL or irreversible effect should sit behind `await approval` (and
  policy may `raises_tier`). Draft-then-approve, never auto-fire consequential effects.
- **Make effects reversible where possible** — add `compensate_with`; if truly irreversible, catch it at
  approval, not after.
- **Wait explicitly** — model "wait for the vendor/customer" as `wait_for_event` with a `match`
  correlation and a real deadline+route. Never busy-loop.
- **Bind and reference** — capture results with `output`, reference with `$name`; keep `match` keyed to
  the operation's correlation value (`$po`/order_ref) so replies find this thread.
- **Bilingual human text** — `intent`, approval `title`, `notify` carry ar/en.
- **One capability per cycle** — `implements Capability@ver` (the contract this cycle fulfils).

---

## 7. Natural-language → NIL — the skill core (a phrasebook)

This is what lets the agent author cycles from a business owner's words. Map the phrase → the construct:

| The user says… | NIL construct |
|---|---|
| "when a low-stock alert fires…" / "when an invoice is created…" | `triggers_on <verb>` (event trigger) |
| "every night" / "each Monday 9am" | `triggers schedule { cron: … }` |
| "let me run it on demand" | `triggers manual` |
| "look up / check / read the …" | a `query` step |
| "create / send / record / update the …" | an `action` step (`use <verb>`) |
| "the owner/manager must approve" | `await approval { approver: … }` + `on approve/reject/timeout` |
| "if X then … otherwise …" | `decision when "X" on_true … on_false …` |
| "wait for the vendor/customer to reply / for the delivery" | `wait_for_event { on_event; match; timeout -> route }` |
| "if it fails, undo the …" | `compensate_with <inverse verb>` (+ `on_error compensate`) |
| "remind them after N days" | a `wait_for_event` timeout `-> route <Remind>` |
| "notify / tell them" | `notify <bilingual>` (or a comms `action` for a real send) |
| "these people/roles are involved" | `roles { … }` + `context { name: Type (role: …) }` |
| "for high-value orders, require extra sign-off" | `policies { policy … when "…" raises_tier HIGH }` |

**Authoring loop the skill runs:**
1. **Elicit** the operation as a sequence of *events → actions → decisions → approvals → waits*.
2. **Discover verbs** available (from the active adapters) — map each "do X" to a real verb; never guess.
3. **Draft `.nil`** using §3–§6.
4. **Validate** by `parse_nil` (and compile) — fix diagnostics; the LSP layer gives positioned errors.
5. **Round-trip** (`print_nil(parse_nil(text))`) to confirm canonical, stable output.
6. **Present** the cycle bilingually for the owner to confirm before publishing.

**Golden rules for the agent:** verbs are atoms (never inline logic); gate consequential effects; wait
explicitly; route every step; bind results; keep it bilingual; and **validate before claiming it works**.

---

## 8. What EXISTS vs what SHOULD BE — the DSL evolution plan

Grounded in the code today, aligned to the NBEM corpus. `[have]` = in the language now · `[gap]` =
needed for the full vision.

### 8.1 What exists `[have]`
- The complete `.nil` cycle language: header + `implements` + 3 trigger kinds; body (`workspace`,
  `intent`, `meta`, `let`, `context`, `roles`, `policies`, `resources`, `flow`, `outcomes`,
  `documentation`); **7 step types**; bilingual bijection; canonical JSON values; `$` references.
- **Round-trip trust** (`parse_nil`⇄`print_nil`), an **LSP** layer (positioned diagnostics), a
  **compiler** (`compile_cycle`), and content-hashed versioning.
- Governance in-language: `await approval`, policy `raises_tier`, `compensate_with`, `wait_for_event`.

### 8.2 What should be `[gap]` (to reach the desired upgrades)
1. **Sub-cycle / capability invocation** *(the biggest)* — a step that **invokes another Capability**
   (runs a child cycle) and waits on it. Today cycles compose **verbs** only; composition across cycles
   is not a step type. → new `invoke`/`call` step; ties to **NBEM gap-plan W5**, P16, and
   CAPABILITIES-VERBS-CYCLES-ARCHITECTURE.md §3. *This is the top DSL gap.*
2. **Richer, unified triggers** — event-trigger sugar (`on_event`/`source_adapter`/`match`) is partly
   "deferred surface sugar" in the printer; make it first-class and consistent with `wait_for_event`
   correlation. Ties to NBEM P8/W9.
3. **Parallelism / fan-out** — model "do these in parallel / wait for all" (a `parallel`/`join`
   construct). Real operations branch concurrently; the DSL is currently sequential + decision-branch.
4. **Explicit correlation binding** — a language-level `correlation` field (not only `match`
   heuristics) so side-channels attach deterministically. Ties to NBEM Inv. 6 / gap-plan W4.
5. **Documents in-flow** — first-class attach/generate-document steps (ties to gap-plan W3), so a cycle
   can produce/collect the documents the Thread accumulates (P7).
6. **Timeline/observability semantics** — ensure a crash preserves the node trace (a runtime gap, D1)
   so the DSL's promise "the Timeline is the truth" holds even on failure (NBEM P15/Inv. 12).
7. **Human-text richness** — parameterized bilingual templates for `notify`/approval/emails (ties to the
   Cycle-Agent plan's communication templates).
8. **The authoring skill itself** — package §3–§7 as a governed skill the agent loads, with the
   validate/round-trip loop wired to `parse_nil`/`compile_cycle` and adapter-verb discovery.

### 8.3 Sequencing (DSL-specific, folds into the NBEM gap plan)
- **Now:** ship this reference as the **authoring skill** (§7) — immediate leverage; no engine change.
- **Phase 1:** explicit `correlation` + first-class event triggers (W4/W9) — small, high-value.
- **Phase 2:** **sub-cycle invocation** (W5) — the composition unlock (P16); the single most important
  language upgrade.
- **Phase 3:** parallelism/fan-out; in-flow documents (W3).
- **Continuous:** keep `parse_nil ⇄ print_nil` an exact inverse for every new construct (the trust
  contract); every addition is additive (never break the frozen core).

---

## 9. Turning this into a skill

To make the agent "speak NIL": package this file as a skill whose body is §3 (grammar) + §4 (steps) +
§5 (worked example) + §6 (discipline) + §7 (NL→NIL phrasebook + authoring loop). The skill's tools:
**discover adapter verbs**, **`parse_nil`/`compile_cycle`** (validate), **`print_nil`** (canonicalize).
The contract the skill must honor: *never emit a verb it did not discover; never leave a step unrouted;
gate consequential effects; validate before claiming success.* With that, a user describing their
operations in Arabic or English gets a governed, round-trip-valid `.nil` cycle back.

---

*Language home: `nilscript/src/nilscript/cycle/` (`nil_printer.py` = canonical form, `nil_parser.py` =
its inverse, `models.py` = the AST, `compile.py`, `lsp.py`). NBEM corpus:
`wosool-hub/docs/NBEM-*.md`, `CAPABILITIES-VERBS-CYCLES-ARCHITECTURE.md`, `CYCLE-AGENT-PLAN.md`.*
