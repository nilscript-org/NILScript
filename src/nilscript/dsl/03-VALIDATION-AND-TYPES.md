# 03 — Validation & Types (The Compiler Frontend)

> The `WosoolDSLValidator` is the gate between an LLM's output and any side effect. It is a
> deterministic, side-effect-free static-analysis pass that *admits* a safe graph or *rejects*
> an unsafe one with structured diagnostics. Nothing reaches the runtime un-admitted.

This is where the language earns the right to be called safe. The validator is the most
important component to build first ([08-ROADMAP.md](08-ROADMAP.md) Phase 1).

---

## 1. The pipeline

Six ordered passes. Each is pure (no I/O, no NIL calls) and either appends diagnostics or
hands a richer model to the next pass. **All ERROR-severity diagnostics block admission.**

```
raw JSON
   │
   ├─▶ V1  Schema gate          (shape, closed objects, enums, oneOf per node type)
   ├─▶ V2  Reference integrity  (every next/branch/on_* target is a defined node id)
   ├─▶ V3  Acyclicity & order   (Kahn topological sort; cycle ⇒ reject; emit run schedule)
   ├─▶ V4  Whitelist            (skill registered AND verb ∈ workspace grant scopes)
   ├─▶ V5  Argument typing       (args ⊨ skill.hint_schema; refs resolve to prior outputs)
   ├─▶ V6  Reachability         (entry reaches all; ≥1 terminal; no orphans; no fwd refs)
   │
   └─▶ admitted Semantic Model  ──▶ preview render ──▶ human approval ──▶ runtime
```

> **Semantic Model (Fowler).** The validator does not hand the runtime the raw JSON. It parses
> into a *separate, typed, validated* model object (`WosoolProgram` → `Node` subtypes) and the
> runtime executes *that*. The raw JSON stays inert data the LLM can never make "run." This
> lets us evolve syntax and semantics independently and test the runtime without an LLM.

---

## 2. V1 — Schema gate

Validate against [`schema/nilscript-dsl.v0.1.schema.json`](schema/nilscript-dsl.v0.1.schema.json)
(JSON Schema 2020-12). The schema is strict on purpose:

- **`additionalProperties: false` everywhere.** A hallucinated or misspelled key (`"nxt"`,
  `"skil"`) is rejected, not silently ignored.
- **`oneOf` discriminated on `type`.** Each node type is a tagged variant with its own required
  fields — a `condition` *must* have `expression`; an `action` *must* have `skill` + `verb`.
  Illegal node shapes are structurally unrepresentable ("make illegal states unrepresentable").
- **`enum` for closed sets** — `type`, `join`, `on_error.action`, `wosool` version. An unknown
  enum value fails here.
- **`pattern` for IDs** — `^step_[0-9]+$` and the NIL verb pattern `^[a-z]+\.[a-z_]+$`.

Mirrors the discipline already enforced by `NilModel` (`extra="forbid"`, frozen) in
`packages/nilscript/sdk/src/nilscript/sdk/sentences.py`.

---

## 3. V2 — Reference integrity

Build the node-id set. Then every structural reference must point into it:

| Rule | Check |
|---|---|
| V-REF-1 | `entry` ∈ node ids. |
| V-REF-2 | every `next`, `on_true`, `on_false`, `on_approved`, `on_rejected`, `on_timeout`, `on_error.to`, `parallel.branches[*]`, `foreach.body` is a defined node id (or `null` where terminal is allowed). |
| V-REF-3 | every **data** reference `$.step_k.output…` names a node `step_k` that exists. (Resolution to a *prior* step is V6.) |

A dangling target (`"next": "step_99"` with no such node) is the graph analog of an unresolved
`$ref` — rejected. (Serverless Workflow validates `functionRef`/`eventRef` the same way.)

---

## 4. V3 — Acyclicity & execution order

The graph must be a **DAG**. Run **Kahn's topological sort** over the success/branch edges:

1. Compute in-degree of every node.
2. Repeatedly emit zero-in-degree nodes, decrementing successors.
3. **If emitted-count < node-count, a cycle exists → reject** (diagnostic names the nodes still
   in the cycle).

The topological order is reused two ways: as the **legal execution schedule**, and as the basis
for which steps a given step may reference (a step may read only strictly-earlier steps — the
forward-reference prohibition, finalized in V6). O(V+E).

> Cycles are the one structural failure an LLM most plausibly emits (step_3 → step_2 → step_3).
> This pass is non-negotiable: a cycle on a Turing-incomplete language would still hang the
> interpreter. Catching it statically is what preserves the termination guarantee.

---

## 5. V4 — Whitelist (the security core)

For every `action` / `query` node, **default-deny**:

```
admit(node) ⟺ skill_registered(node.skill)
            ∧ node.verb ∈ skill.required_verbs
            ∧ scope_allows(workspace.scopes, node.verb)
```

This is **not** new code — it is exactly the repo's existing gate:

- `SkillRegistry.offers(scopes)` returns only skills whose every required verb is granted.
- `grants.scope_allows(scopes, verb)` is the default-deny check: exact verb match or a
  `profile.*` wildcard (`commerce.*`).

A verb the workspace was never granted (`commerce.delete_store` when scopes are
`{commerce.create_product, commerce.create_coupon}`) is rejected here — the merchant is
confined to their lane. This is the "Whitelist Verification" the charter calls for, and it is
already battle-tested in `skills/registry.py`.

The tool name is also a closed `enum` derived from the registry, so V1 already blocks
*hallucinated* skills; V4 blocks *ungranted* ones.

---

## 6. V5 — Argument typing

For each `action`/`query`, validate `args` against the skill's `hint_schema` (the JSON Schema
each skill already publishes — e.g. `ProductSkill.hint_schema` requires `name` + `price`):

- **Literals** are checked against the declared type/required-ness.
- **Data references** (`$.step_k.output.f`) are checked for *resolvability* (the source step
  exists and precedes this one), not for runtime value — values are unknown until execution.
  The validator records the dependency edge so V3/V6 see it.

> **A deliberate boundary on type strictness.** Because `args` are *hints* the business OS
> re-resolves authoritatively (hard rule 3), the validator type-checks **shape**, not business
> truth. It confirms `price` is *present* and *string-shaped*; it does **not** assert the price
> is correct — the System does that and returns it in the preview the merchant confirms. The
> charter's "is the price a number not a string?" check is therefore intentionally *softened*:
> we forward `"89"` as a hint; the System parses and authoritatively resolves it. (See
> `parse_positive_amount` in `skills/base.py` — even our own screening is "is this a *plausible*
> hint," never "this is the canonical value.")

---

## 6b. V5+ — Structured args (D-1) & typed QUERY output references (0.2)

Synced from nilscript `versions/0.2.0.md` (D-1 + the typed QUERY response contract). Two additions
to V5, both static and deterministic.

### D-1 — structured argument paths

Args may be typed objects and arrays-of-objects, bounded by the **self-defined** D-1 rule:
non-recursive, **at most two chained structural levels** (an array of objects may contain one array
of objects; no third level). The arg-shape → reference-path grammar a validator MUST implement:

| Arg / output shape | Example (nilscript) | Reference path |
|---|---|---|
| object (level 1) | `refund_target` | `$.x.field` (`$.refund_target.id`) |
| array of objects (level 1) | `variants[]`, `data.clients[]` | `$.x[0].field` (`$.variants[0].price`) |
| nested array of objects (level 2, max) | `options[].values[]` | `$.x[0].values[0].field` |

A reference with a fourth structural component (`$.x[0].y[0].z[0]`) exceeds D-1 → `V5_NEST_DEPTH`.
(`create_product.options` is the deepest *application* of the rule, never its definition.)

### Typed QUERY output references — the keystone

A `query` node's `output` has a shape: the verb's **typed response profile**
(`query_skills.<skill>.response_schema` in the conformance context; nilscript
`schemas/profiles/<profile>/<verb>.response.json`). When a later node references `$.step_k.output.…`
and `step_k` is a query, V5 resolves the path **against that response shape**, not just for existence:

- the field at each step must exist in the response schema, else **`V5_OUTPUT_FIELD_UNKNOWN`**
  (e.g. `$.q.output.clients[0].price` — `price` is not in `clients` items `{id,name}`);
- the path must respect array-vs-object at each step, else **`V5_PATH_SHAPE_MISMATCH`**
  (e.g. `$.q.output.clients.id` — `clients` is an array; an index is required).

> **Why this is the load-bearing check.** Accepting a correct reference is necessary but not
> sufficient. The response contract is "typed" only because the validator **rejects** the two
> negatives above. A loose `{data: object}` would admit both — satisfying an adapter but not the
> DSL. The corpus pins this with `valid/06` (accept), `invalid/09` (unknown field), `invalid/10`
> (shape mismatch). The higher layer (DSL) is what forces the contract to be typed.

> **Contract-version binding (the `$id` trap).** The bound profile version comes from the
> registry / `versions/`, **never** from a schema `$id`. nilscript keeps `$id`s on `…/0.1/…` across
> releases (the release is tracked in `versions/` + verb semver); a validator that read the version
> from `$id` would see `0.1` and silently miss the `0.2` response shapes. Bind by registry path.

---

## 7. V6 — Reachability, terminality, forward references

| Rule | Check |
|---|---|
| V-RCH-1 | Every node is reachable from `entry` (no orphan nodes). |
| V-RCH-2 | At least one terminal node (`next: null` / a `notify` end / an explicit terminal). No infinite dangling. |
| V-RCH-3 | **No forward data reference:** for each `$.step_k…` inside node `step_n`, `step_k` must precede `step_n` in topological order. |

V-RCH-3 is the charter's "Forward Reference Prohibition" — you cannot consume an output before
it is produced.

---

## 8. Structured diagnostics

The validator returns a **result**, not an exception, modelled on AWS
`ValidateStateMachineDefinition` (consumers should branch on `result`, not on exact codes):

```json
{
  "result": "FAIL",
  "diagnostics": [
    { "code": "V4_SCOPE_DENIED", "severity": "ERROR",
      "location": "pipeline[2]", "node": "step_3",
      "message": "verb 'commerce.delete_store' is not in workspace ws_demo grant scopes" },
    { "code": "V3_CYCLE", "severity": "ERROR",
      "location": "pipeline", "node": "step_5",
      "message": "cycle: step_5 → step_2 → step_5" }
  ]
}
```

| Field | Use |
|---|---|
| `result` | `OK` \| `FAIL`. Admission = `OK`. |
| `code` | Stable-ish category (`V1_SCHEMA`, `V2_DANGLING_REF`, `V3_CYCLE`, `V4_SCOPE_DENIED`, `V5_ARG_TYPE`, `V6_FORWARD_REF`, …). |
| `severity` | `ERROR` (blocks) \| `WARNING` (informs). |
| `location` | JSON-path-ish pointer into the offending node. |
| `node` | The offending node id, when applicable. |
| `message` | Bilingual-capable human text. |

Diagnostics serve **two** consumers:

1. **Engineers / dashboards** — debugging a bad program.
2. **The LLM itself** — fed back into the Generation layer so it can re-compile a corrected
   program (axiom 4 / self-healing). Precise `location` + expected-vs-actual is what makes the
   repair loop converge.

---

## 9. Layered defense (not single-point)

The whitelist + schema is enforced at **three** independent layers, so no single failure admits
an unsafe action:

1. **Generation** — the LLM is given a closed tool `enum` and (where supported) **constrained
   decoding / strict structured outputs**, so it emits schema-valid DSL *by construction*. This
   is strictly stronger than validate-then-retry, but it is **not** the only line.
2. **Validation** — this document. Even a perfectly-typed graph is re-checked for references,
   cycles, scopes, reachability. Constrained decoding cannot prove acyclicity or grant scope.
3. **Runtime / NIL** — the business OS independently re-validates every `PROPOSE` (it can return
   `SCOPE_DENIED`, `INVALID_ARGS`, `UNKNOWN_VERB` refusals — Annex A). The DSL whitelist is a
   *fast local* check; the System remains the final authority. Defense in depth.

---

Next: **[04-EXECUTION-MODEL.md](04-EXECUTION-MODEL.md)** — what the runtime does with an
admitted graph.
