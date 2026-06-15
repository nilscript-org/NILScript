# nilscript DSL — Conformance Corpus (v0.1)

> A shared suite of programs + expected validator verdicts. **This is what makes nilscript DSL a
> standard rather than a format.** Any implementation of `WosoolDSLValidator` — in Python, Go,
> TypeScript, Rust — claims conformance by running this corpus and matching every verdict.

This is the seed of the open standard described in
[../10-POSITIONING-AND-PUBLISHING.md](../10-POSITIONING-AND-PUBLISHING.md). When the language
moves to its own `nilscript-dsl-spec` repo, this directory travels with it as the compliance gate.

---

## Layout

```
conformance/
├── context.json     the world a program is validated against:
│                    the skill registry (V4/V5) + per-workspace grant scopes (V4).
├── valid/           programs that MUST be admitted (result: OK).
├── invalid/         programs that MUST be rejected — each isolates ONE validator pass.
└── manifest.json    the verdict contract: file → expected {result, codes[]}.
```

Every file in `valid/` and `invalid/` is a *real* Wosool program (pure JSON, no comments) — they
double as runnable examples.

## The verdict contract

For each program a conforming validator MUST:

1. produce the manifest's **`result`** (`OK` | `FAIL`) exactly, and
2. for `FAIL` cases, emit **at least** every listed diagnostic **`code`** (a superset is allowed
   — an implementation may legitimately detect more problems in one pass).

**Not asserted:** `severity`, `location`, `message` wording, or the *order* of diagnostics. This
mirrors AWS `ValidateStateMachineDefinition` guidance — branch on `result` + codes, not on exact
strings — so implementations stay free to improve diagnostics without breaking conformance.

## Diagnostic code table (canonical)

| Code | Pass | Meaning |
|---|---|---|
| `V1_SCHEMA` | V1 | Fails the JSON Schema (unknown `type`, missing required field, bad enum/pattern, extra key). |
| `V2_DANGLING_REF` | V2 | A `next`/branch/`on_*` target names a node that does not exist. |
| `V3_CYCLE` | V3 | The graph is not a DAG (Kahn topological sort leaves nodes unemitted). |
| `V4_UNKNOWN_SKILL` | V4 | `skill`/`verb` is not in the registered catalog (`context.skills`). |
| `V4_SCOPE_DENIED` | V4 | The verb is not allowed by the workspace's grant scopes (default-deny / `scope_allows`). |
| `V5_ARG_MISSING` | V5 | A required hint from the skill's `hint_schema` is absent. |
| `V5_ARG_TYPE` | V5 | An arg's shape contradicts the skill's `hint_schema`, or a reference is unresolvable. |
| `V6_FORWARD_REF` | V6 | A `$.step_k…` reference names a step that does not precede this one in topological order. |
| `V6_UNREACHABLE` | V6 | A node is not reachable from `entry`, or the program has no terminal node. |
| `V4_DEPRECATED_VERB` | V4 | **(0.2, WARNING — non-blocking)** The verb is deprecated in the bound profile (e.g. `commerce.update_order_status`). Admits, but the validator MUST surface it. |
| `V5_OUTPUT_FIELD_UNKNOWN` | V5 | **(0.2)** A `$.step_k.output.…` reference names a field absent from the source query's typed `response_schema`. |
| `V5_PATH_SHAPE_MISMATCH` | V5 | **(0.2)** A reference treats an array as an object (or vice versa) — e.g. `clients.id` where `clients` is an array of objects (missing index). |
| `V5_NEST_DEPTH` | V5 | **(0.2, D-1)** A structured arg or output reference exceeds the two-level non-recursive nesting bound (a fourth path component `$.x[0].y[0].z`). |

The canonical list lives here and in [../03-VALIDATION-AND-TYPES.md §8](../03-VALIDATION-AND-TYPES.md).

## What each case proves

| Case | Designed failure | Passes earlier stages? |
|---|---|---|
| `invalid/01-cycle` | `V3_CYCLE` (step_2 → step_1 → step_2) | yes — V1, V2 clean |
| `invalid/02-scope-denied` | `V4_SCOPE_DENIED` (`ws_limited` lacks `commerce.create_coupon`) | yes — V1–V3 clean |
| `invalid/03-dangling-ref` | `V2_DANGLING_REF` (`next: step_99`) | yes — V1 clean |
| `invalid/04-forward-ref` | `V6_FORWARD_REF` (step_1 reads `$.step_2.output`) | yes — V1–V5 clean |
| `invalid/05-unknown-type` | `V1_SCHEMA` (`type: loop`) | — fails at the gate |
| `invalid/06-missing-required-arg` | `V5_ARG_MISSING` (`product` without `price`) | yes — V1–V4 clean |
| `invalid/07-unreachable-node` | `V6_UNREACHABLE` (`step_3` orphaned) | yes — V1–V5 clean |
| `invalid/08-unknown-skill` | `V4_UNKNOWN_SKILL` (`store_admin`/`commerce.delete_store`) | yes — V1–V3 clean |
| `invalid/09-query-output-unknown-field` | `V5_OUTPUT_FIELD_UNKNOWN` (`clients[0].price` — not in response_schema) | yes — V1–V4 clean |
| `invalid/10-query-output-shape-mismatch` | `V5_PATH_SHAPE_MISMATCH` (`clients.id` — array read as object) | yes — V1–V4 clean |

**0.2 keystone — the typed QUERY response contract proves its weight by REJECTION.** Accepting a
correct reference (`valid/06`) is necessary but not sufficient; the contract is only "typed" if it
*rejects* a field that is not in the response shape (`invalid/09`) and a path that confuses an array
with an object (`invalid/10`). Those two negatives are what make `query-answer` + `*.response.json`
a type, not a label. `valid/07` proves deprecation is observable (a warning, not silence).

Each invalid program is constructed to be clean through every pass *before* the one it targets —
so a failing verdict pinpoints exactly which check the implementation got wrong.

## Running the corpus (reference harness, pseudocode)

```text
ctx = load("context.json")
for file, expected in load("manifest.json").cases:
    program = load(file)
    verdict = WosoolDSLValidator(ctx).validate(program)   # the impl under test
    assert verdict.result == expected.result
    if expected.result == "FAIL":
        assert set(expected.codes) ⊆ set(d.code for d in verdict.diagnostics)
```

The Python reference implementation (Phase 1, [../08-ROADMAP.md](../08-ROADMAP.md)) will ship a
real harness (`pytest`) driving exactly this loop. Until then, the corpus is validated
structurally against [../schema/nilscript-dsl.v0.1.schema.json](../schema/nilscript-dsl.v0.1.schema.json):
all `valid/*` and every `invalid/*` except `05-unknown-type` parse clean (the rest fail at
V2–V6, which the schema deliberately does not check).

## Contributing a case

1. Add a pure-JSON program to `valid/` or `invalid/`.
2. Add its expected verdict to `manifest.json` (`pass` + `codes`).
3. Keep an invalid case **single-fault** — clean through every prior pass — so it isolates one
   check. If a program trips two passes, split it.
