# 06 — Worked Examples

> Programs from a one-liner to a conditional, data-passing, approval-gated graph — each shown
> with the merchant intent that produced it and the NIL it compiles to. Status tags
> ([00-INDEX.md](00-INDEX.md)) show which run on today's primitives vs. need the interpreter.

All examples are `wosool: "0.1"`. Arabic-first; `args` are hints the System re-resolves.

---

## Example 1 — Single action 🟢

**Merchant:** «أضف منتج قميص قطن بسعر ٨٩»  ·  *"Add a product: cotton shirt, price 89."*

```json
{
  "wosool": "0.1", "workspace": "ws_demo", "locale": "ar", "entry": "step_1",
  "pipeline": [
    { "id": "step_1", "type": "action", "skill": "product",
      "verb": "commerce.create_product",
      "args": { "name": "قميص قطن", "price": "89" }, "next": null }
  ]
}
```

Compiles to one NIL `PROPOSE`; the merchant sees the System's verbatim `PROPOSAL` preview;
on confirm, one idempotent `COMMIT`. This is the path `engine.py::_propose` runs **today** — the
DSL just makes it an explicit one-node program.

---

## Example 2 — Multi-intent batch (parallel) 🟢

**Merchant:** «سوّ كوبون خصم ١٠٪ وأنشئ منتج بنطلون بسعر ١٢٠»
· *"Make a 10% coupon and create a product: trousers, 120."*

```json
{
  "wosool": "0.1", "workspace": "ws_demo", "locale": "ar", "entry": "step_1",
  "pipeline": [
    { "id": "step_1", "type": "parallel",
      "branches": ["step_2", "step_3"], "join": "all", "next": "step_4" },

    { "id": "step_2", "type": "action", "skill": "coupon",
      "verb": "commerce.create_coupon",
      "args": { "percent": "10" }, "next": null },

    { "id": "step_3", "type": "action", "skill": "product",
      "verb": "commerce.create_product",
      "args": { "name": "بنطلون", "price": "120" }, "next": null },

    { "id": "step_4", "type": "notify",
      "message": { "ar": "تم تجهيز طلبيك للمعاينة.", "en": "Both items are ready to preview." },
      "next": null }
  ]
}
```

Maps directly to **`MultiIntentFlow`**: one durable `IntentTaskFlow` child per branch,
`asyncio.gather`, per-branch isolation, ONE aggregate reply. The two proposals preview together;
nothing commits until the merchant confirms (safe to fan out N — hard rule 3).

---

## Example 3 — Conditional on a fresh read (data flow) 🟡

**Merchant:** «شيك على مخزون القميص، لو أقل من ١٠ سوّ كوبون ٢٠٪»
· *"Check the shirt's stock; if under 10, make a 20% coupon."*

```json
{
  "wosool": "0.1", "workspace": "ws_demo", "locale": "ar", "entry": "step_1",
  "pipeline": [
    { "id": "step_1", "type": "query", "verb": "commerce.product",
      "args": { "sku": "SHIRT-001" }, "next": "step_2" },

    { "id": "step_2", "type": "condition",
      "expression": "$.step_1.output.stock < 10",
      "on_true": "step_3", "on_false": "step_4" },

    { "id": "step_3", "type": "action", "skill": "coupon",
      "verb": "commerce.create_coupon",
      "args": { "percent": "20" }, "next": null },

    { "id": "step_4", "type": "notify",
      "message": { "ar": "المخزون كافٍ، ما سوّيت خصم.", "en": "Stock is fine — no discount made." },
      "next": null }
  ]
}
```

`step_1` → NIL `QUERY` (reads business truth fresh; never memorized). `step_2` is a pure route
on a CEL guard against the **referenced** output. `$.step_1.output.stock` is resolved at runtime
*after* `step_1` completes — the LLM never guessed the stock number (axiom 2). **🟡** because the
`query`+`action` primitives exist, but the `condition` interpreter is net-new.

---

## Example 4 — Approval gate (human-in-the-loop) 🟢 primitives / 🔴 wiring

**Merchant:** «اعمل استرجاع للطلب ١٢٣، وبلّغني بالنتيجة»
· *"Refund order 123, and tell me the outcome."*

```json
{
  "wosool": "0.1", "workspace": "ws_demo", "locale": "ar", "entry": "step_1",
  "pipeline": [
    { "id": "step_1", "type": "action", "skill": "refund",
      "verb": "commerce.process_refund",
      "args": { "order": "123" }, "next": "step_2" },

    { "id": "step_2", "type": "await_approval",
      "proposal": "$.step_1.output.proposal_id",
      "timeout_seconds": 86400,
      "on_approved": "step_3", "on_rejected": "step_4", "on_timeout": "step_4" },

    { "id": "step_3", "type": "notify",
      "message": { "ar": "تم تنفيذ الاسترجاع.", "en": "The refund was carried out." }, "next": null },

    { "id": "step_4", "type": "notify",
      "message": { "ar": "ما تم تنفيذ الاسترجاع.", "en": "The refund was not carried out." }, "next": null }
  ]
}
```

A refund is typically a HIGH/CRITICAL tier → it **parks** for owner approval. `step_2` is
`AwaitDecisionFlow`: poll `STATUS` (or catch a pushed `EVENT`) until terminal, then route. The
DSL waits; it never speaks the approval. **🔴 wiring:** the chat-channel "merchant said yes →
commit" handler is the known prerequisite (see the multi-intent roadmap Phase 5 connect-step).

---

## Example 5 — Bounded fan-out (foreach) 🔴

**Merchant:** «كل المنتجات اللي مخزونها صفر، حدّث حالتها لمخفي»
· *"For every out-of-stock product, set it hidden."*

```json
{
  "wosool": "0.1", "workspace": "ws_demo", "locale": "ar", "entry": "step_1",
  "pipeline": [
    { "id": "step_1", "type": "query", "verb": "commerce.products",
      "args": { "filter": "out_of_stock" }, "next": "step_2" },

    { "id": "step_2", "type": "foreach",
      "items": "$.step_1.output.products", "as": "p", "max_items": 50,
      "body": "step_3", "next": "step_4" },

    { "id": "step_3", "type": "action", "skill": "order_status",
      "verb": "commerce.update_order_status",
      "args": { "id": "$.item.p.id", "status": "hidden" }, "next": null },

    { "id": "step_4", "type": "notify",
      "message": { "ar": "خلصت التحديث.", "en": "Done updating." }, "next": null }
  ]
}
```

`max_items: 50` is **required** — the language has no unbounded iteration (totality). Each
iteration still previews/commits per hard rule 3. **🔴** the `foreach` interpreter is net-new;
the per-item `action` is not.

---

## What every example shares

- **`args` are hints**, never asserted business values.
- **Data crosses steps only by `$.step_k.output…` reference** — never a fabricated value.
- **Nothing commits without a previewed, human-confirmed proposal.**
- **Every leaf reaches a terminal node**, and the graph is acyclic — so each program is
  admissible by the validator in [03](03-VALIDATION-AND-TYPES.md).

A **rejected** program, for contrast:

```json
{ "id": "step_2", "type": "action", "skill": "store_admin",
  "verb": "commerce.delete_store", "args": {}, "next": "step_1" }
```

Three independent ERRORs: `V4_SCOPE_DENIED` (no such grant), `V1_SCHEMA`/whitelist (no such
registered skill), and `V3_CYCLE` (`step_2.next → step_1 → step_2`). It never reaches preview.

---

Next: **[07-MAPPING-TO-REPO.md](07-MAPPING-TO-REPO.md)** — concept → code.
