# 05 — The Standard Library (Skills)

> A language is only as useful as its standard library. nilscript DSL's stdlib is the **skill
> catalog** — the set of whitelisted commerce operations an `action`/`query` node can call.
> Each skill is one "function" with a typed signature (`hint_schema`) and a grant scope.

The catalog is the source of truth shared by **both** gateway surfaces (the LLM-tools mode and
the MCP mode) via `skills/builtins.py::default_registry()` — so the two can never drift on which
skills exist. Registration ≠ exposure: a skill is *offered* only if the workspace's grant scopes
allow its verb (`SkillRegistry.offers`).

---

## 1. The catalog (v0.1, as implemented)

Every entry below is a real skill in
`packages/wosool_convlayer/src/wosool_convlayer/skills/`.

| Skill name | Intent | NIL verb | Grant scope needed | Required hints |
|---|---|---|---|---|
| `product` | `create_product` | `commerce.create_product@1.2.0` | `commerce.create_product` or `commerce.*` | `name`; `price` (flat) **or** `variants[]` |
| `coupon` | `create_coupon` | `commerce.create_coupon` | `commerce.create_coupon` or `commerce.*` | (coupon fields) |
| `refund` | `process_refund` | `commerce.process_refund@2.0.0` | `commerce.process_refund` or `commerce.*` | (order ref → maps to `refund_target`) |
| `record_fulfillment` | `record_fulfillment` | `commerce.record_fulfillment` | `commerce.record_fulfillment` or `commerce.*` | `order`, `event` |
| `record_payment` | `record_payment` | `commerce.record_payment` | `commerce.record_payment` or `commerce.*` | `order`, `event` |
| `invoice` | `create_invoice` | `services.create_invoice` | `services.create_invoice` or `services.*` | (invoice fields) |
| `list_clients` *(query)* | `list_clients` | `services.list_clients` | `services.list_clients` or `services.*` | — (optional `name`) |
| ~~`order_status`~~ | ~~`update_order_status`~~ | ~~`commerce.update_order_status`~~ | **DEPRECATED 0.2** → `record_fulfillment` / `record_payment` | — |

> **0.2 changes (synced from nilscript `versions/0.2.0.md`).** `update_order_status` is deprecated
> (status is a derived fact — GAP-001): a program using it still admits but the validator emits
> `V4_DEPRECATED_VERB` (warning). `record_fulfillment`/`record_payment` record facts. `process_refund`
> takes the abstract `refund_target {order|invoice|payment, id}` southbound (the DSL *hint* stays
> simple — hints ≠ NIL args). `create_product` gains the `variants[]` decomposition (`oneOf` with the
> flat shape). `list_clients` is the first **query** skill with a typed response profile.
>
> **Contract-version binding (the `$id` trap).** nilscript keeps schema `$id`s on `…/0.1/…` across
> releases; the release lives in `versions/` + verb semver. A DSL validator MUST source the bound
> profile version from the registry/`versions/`, **never** by parsing a version out of a schema `$id`
> — otherwise it reads `0.1` and silently misses the `0.2` shapes (`refund_target`, `query-answer`).

> **Verb namespaces.** Verbs follow the NIL pattern `^[a-z]+\.[a-z_]+$` — a *profile* (`commerce`,
> `services`) and an *operation*. The profile is the wildcard unit: a grant of `commerce.*`
> opens every commerce verb; `services.*` opens services. This is the `scope_allows` rule.

---

## 2. A skill's signature

Each skill publishes the same contract (`skills/base.py::Skill` Protocol). For the language,
the load-bearing parts are:

| Member | Role in the DSL |
|---|---|
| `name` | The `action.skill` value. |
| `required_verbs` | What `action.verb` must be; gates the whitelist (V4). |
| `hint_schema` | The JSON Schema for `args`; drives argument typing (V5). |
| `description` (bilingual) | Powers the preview and the MCP tool listing. |
| `to_proposes(intent)` | Compiles resolved hints → one or more NIL `ProposeBody`. |

Example — `ProductSkill.hint_schema` (verbatim shape):

```json
{
  "type": "object",
  "properties": {
    "name":        { "type": "string", "description": "Product name" },
    "price":       { "type": "string", "description": "Price (numeric hint)" },
    "description": { "type": "string" },
    "category":    { "type": "string", "description": "Category name or reference" },
    "sku":         { "type": "string" },
    "quantity":    { "type": "string", "description": "Optional stock quantity (integer)" },
    "sale_price":  { "type": "string", "description": "Optional discounted price (numeric)" }
  },
  "required": ["name", "price"],
  "additionalProperties": false
}
```

Note every property is `string` — because **`args` are hints** (numbers arrive as `"89"` and the
System resolves them authoritatively, see [03 §6](03-VALIDATION-AND-TYPES.md)). The skill's own
`parse_positive_amount` / `parse_positive_int` only *screen* a hint as plausible; they never
assert the canonical value.

---

## 3. The stdlib *is* the security boundary

The catalog defines the entire universe of operations the language can express. There is no
`action` that reaches outside it. This is the "modular blocks only snap together correctly"
property: adding a capability = adding a skill (a new stdlib function); the engine, validator,
and runtime are untouched. Removing a grant scope instantly removes that capability for a
workspace — no code change.

```
LLM may emit  ⊆  registered skills  ⊇offers  granted skills (per workspace)  =  admissible actions
                 (builtins.py)          (scope_allows)
```

A program that calls `commerce.delete_store` is rejected at V4 not because we wrote a rule
against it, but because no such skill is registered **and** no scope grants it — default-deny.

---

## 4. Extending the library (how a new "function" is added)

To add a capability to the language (the charter's "prove the stdlib is as powerful as
Python's, but for commerce"):

1. Write a `Skill` class (name, intents, `required_verbs`, `hint_schema`, `description`,
   `to_proposes`) — same contract as `ProductSkill`.
2. Register it in `default_registry()` (`builtins.py`).
3. Add the verb to the relevant grant profile so workspaces can be granted it.
4. **Nothing in the DSL engine changes.** The validator reads the new `hint_schema`; the LLM
   sees the new tool; the runtime compiles its `to_proposes` to NIL like any other.

This is YAGNI-friendly: the v0.1 catalog is deliberately small (five skills). It grows when a
real merchant need lands, not speculatively.

---

## 5. Versioning

The catalog is versioned with the language (`wosool: "0.1"`). A skill's `hint_schema` is part of
the language surface — changing a required hint is a breaking change and bumps the version. The
NIL verbs are versioned independently by the nilscript (the southbound contract); a verb's
profile (`commerce` vs `services`) is stable.

---

Next: **[06-EXAMPLES.md](06-EXAMPLES.md)** — programs that use this library.
