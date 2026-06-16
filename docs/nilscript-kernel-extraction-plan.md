# NILScript Kernel — Extraction & Software-First Pivot (Deep Plan)

> **Status:** Plan / roadmap. No code is moved or published from this document. · **Date:** 2026-06-16
> **Companion docs:** [`adapter-ecosystem-strategy.md`](./adapter-ecosystem-strategy.md) · [`saas-grade-content-plan.md`](./saas-grade-content-plan.md) · [`../src/nilscript/dsl/11-RUNTIME-EXPLAINED.md`](../src/nilscript/dsl/11-RUNTIME-EXPLAINED.md)
> **Premise (corrected):** the runtime is **already implemented** in `wosool-cloud` (the 11-RUNTIME doc predates it). This is an **extraction**, not a net-new build.

---

## 0. The decision (the razor)

Repurpose the name **`nilscript`** so it refers to a **lightweight, installable, headless execution kernel** — not an abstract standard. Two halves, named precisely:

| Name | What it is | Where it lives | Installable? |
| --- | --- | --- | --- |
| **NILScript** | The **kernel software** — a local runtime gateway that parses a `plan.nil.json` DSL program, validates it, walks the graph, and drives a mounted **adapter** via NIL (PROPOSE→COMMIT/QUERY/ROLLBACK). Headless, **no dashboard** (LiteLLM-style). | `nilscript` package (pip / later npm) + `nilscript-org/nilscript` repo | **Yes** — `pip install nilscript`, then `nilscript run`. |
| **NILScript Protocol** | The **specification** — NIL wire contract, the DSL grammar, SEQRD-PC, the constitution. | **Docs only** (docs site + `docs/`/`nil/versions/*` in the repo). **Not** a separate pip/npm package. | **No** — it's reading material. |

**Why software-first wins (the viral thesis):** developers run code, they don't read specs. `pip install nilscript && nilscript run` is a <60-second time-to-value loop; a spec is "I'll read it later" (they don't). The spec stays as the *authority layer* embedded in the kernel's docs — enterprise dignity without splitting the package footprint. This mirrors LiteLLM (headless proxy, viral) and Langfuse (the OSS engine drives the cloud upsell), and MCP / JSON Schema (spec is docs, not a package you `pip install`).

**The flywheel:** the OSS kernel is the razor (free, local, viral, community adapters); **Wosool Cloud** is the blade (the *same* engine made durable + multi-tenant + dashboarded). The kernel's docs say: *"runs locally headless; connect to Wosool Cloud for durable, monitored, scaled execution."*

---

## 1. Current state — what's already built (ground truth)

The runtime lives in the **`wosool-cloud`** monorepo (`/home/ubuntu/Downloads/nizam/wosool-cloud/packages/`), as five packages:

```
wosool_convlayer   # conversation layer + the DSL ENGINE (dsl/)            ← contains the gold
wosool_worker      # Temporal worker: the interpreter + activities         ← walker is here, Temporal-bound
wosool_gateway     # FastAPI + Temporal client: start runs, read status    ← cloud entry
wosool_store       # persistence / tenancy                                 ← cloud
wosool_senders     # outbound channels (WhatsApp, …)                       ← cloud
```

### 1.1 The DSL engine — **pure, reusable as-is** (`wosool_convlayer/dsl/`)

| File | What it is | Deps |
| --- | --- | --- |
| `models.py` | Typed AST: `ActionNode`, `QueryNode`, `ConditionNode`, `ParallelNode`, `ForeachNode`, `AwaitApprovalNode`, `WaitNode`, `NotifyNode`, `WosoolProgram` (pydantic, frozen). | pydantic |
| `validator.py` (338 ln) | The full admission pipeline: `validate(raw, ctx)` → schema · references · acyclicity · whitelist · arguments · output-refs · reachability (V1–V6). | pydantic |
| `guards.py` (239 ln) | `evaluate_guard(expression, ctx)` — a **hand-written tokenizer + parser** for condition expressions. **No `eval`**, side-effect-free. | stdlib |
| `references.py` (135 ln) | `resolve($.step_k.output.x, ctx)`, `parse_reference`, `iter_references` — selection-only, pure. | stdlib |
| `context.py`, `diagnostics.py` | `ValidationContext`, `DiagnosticCollector`, `ValidationResult`. | stdlib |

**This is the heart of the kernel and it is already pure** — no Temporal, no FastAPI, no cloud. Package deps: `nilscript[sdk]` + `cryptography`.

### 1.2 The interpreter — split (pure helpers + Temporal walker)

- `wosool_worker/graph.py` (41 ln) — **pure**: `node_map(program)`, `next_after(node, output)` (routing), `idem_key(run_id, node_id)`, `propose_dict(verb, args)`. Lift **as-is**.
- `wosool_worker/workflows.py` — `DynamicGraphExecutorWorkflow`: the actual walk loop, **as a Temporal `@workflow`**. Uses `graph.py` helpers + `activities.py`.
- `wosool_worker/activities.py` — Temporal `@activity` wrappers that speak NIL (COMMIT/QUERY/POLL_STATUS/SEND_OUTBOUND) via the `nilscript` SDK.
- `wosool_worker/worker.py`, `schedules.py` — Temporal worker registration. **Cloud-only.**

### 1.3 The southbound — **reusable as-is** (`nilscript/sdk/`)

`NilClient` (propose/commit/query/status/rollback over httpx), `NilTransport` (circuit breaker + retry + bearer), `GrantRef`/`scope_allows`, sentence models. The kernel dispatches a DSL `action` by having `NilClient` POST PROPOSE then COMMIT to a mounted adapter's NIL URL — **no Temporal needed for this**.

### 1.4 Cloud-coupled — **leave behind**

`temporalio`, `wosool_worker/{worker,schedules,workflows,activities}.py` (the *Temporal* forms), `wosool_gateway/*` (FastAPI + Temporal client + `dashboard.py`), `wosool_store` (tenancy/persistence), `wosool_senders`, and convlayer's non-DSL parts (agents, routing, tenancy, LLM extra).

---

## 2. What the lightweight kernel *is* (precise scope)

A single installable package, `nilscript` (the kernel), that exposes:

```bash
nilscript run plan.nil.json \
  --adapter-url http://localhost:8080 \   # a running NIL shim (e.g. pocketbase-nil-adapter)
  --grant-id <id> --workspace <ws> --grant-secret-env NIL_GRANT_SECRET \
  --input '{"sku":"SHIRT-001"}' \
  --json                                  # machine-readable trace to stdout
```

It performs, **in-process, headless, no Temporal**:

1. **Validate** — `validate(program, ctx)` from the lifted DSL engine (V1–V6). Refuse with diagnostics on failure.
2. **Walk** — a new `async` executor (the port of `DynamicGraphExecutorWorkflow`): `node_map` + the `while node_id` loop + `next_after` routing.
3. **Dispatch** per node type, reusing the existing per-type logic but calling the SDK directly instead of Temporal activities:
   - `action` → `NilClient.propose()` → (preview) → `NilClient.commit(idem_key(run_id,node_id))`
   - `query` → `NilClient.query()`
   - `condition` → `evaluate_guard()` → route
   - `wait` → `asyncio.sleep()` (was `workflow.sleep`)
   - `notify` → emit to stdout/log (no channel senders locally)
   - `parallel` → `asyncio.gather()` over sub-branches
   - `foreach` → bounded loop (the `max_items` cap)
   - `await_approval` → poll `NilClient.status()` with a local timeout (was a durable signal race)
4. **Saga unwind** on `on_error: compensate` — walk committed steps in reverse, `NilClient.rollback()` each (auto only for blessed REVERSIBLE; park COMPENSABLE; honest partial on IRREVERSIBLE). The logic exists; re-home it off Temporal.
5. **Emit** a full execution trace (the `ctx`) as JSON.

**What it deliberately drops vs. the cloud runtime:** Temporal durability/replay (a crash loses the in-flight run — acceptable for a local dev kernel; *durability is the cloud upgrade*), the dashboard, multi-tenancy, channel senders, the LLM/conversation layer. **What it keeps:** the exact validator, guard semantics, reference resolution, idempotency-key format, and SEQRD-PC honesty — so a plan that runs locally runs identically (durably) in the cloud.

---

## 3. The extraction boundary (the map)

| Component | Source today | Kernel action |
| --- | --- | --- |
| DSL AST models | `wosool_convlayer/dsl/models.py` | **Lift as-is** |
| Validator (V1–V6) | `wosool_convlayer/dsl/validator.py` + `context.py` + `diagnostics.py` | **Lift as-is** |
| Guard evaluator | `wosool_convlayer/dsl/guards.py` | **Lift as-is** |
| Reference resolver | `wosool_convlayer/dsl/references.py` | **Lift as-is** |
| Routing / idempotency / node_map | `wosool_worker/graph.py` | **Lift as-is** |
| The walk loop + per-node dispatch | `wosool_worker/workflows.py` (Temporal `@workflow`) | **Rebuild headless** as `async` (≈150–300 ln): swap `execute_activity`→`NilClient`, `workflow.sleep`→`asyncio.sleep`, signal→poll |
| Saga unwind | `workflows.py` (`_unwind`) | **Rebuild headless** (same algorithm, direct `NilClient.rollback`) |
| NIL dispatch (PROPOSE/COMMIT/QUERY/ROLLBACK) | `nilscript/sdk/client.py` | **Reuse as-is** |
| Grants / scope (V4) | `nilscript/sdk/grants.py` | **Reuse as-is** |
| `nilscript run` CLI | — | **New** (≈100 ln) |
| Adapter mount | — | **New** — `--adapter-url` (HTTP) now; optional `--adapter <path>` spawn/in-process later |
| Temporal worker/activities/workflows | `wosool_worker/*` | **Leave behind** (becomes the cloud durability layer) |
| Gateway (FastAPI), store, senders, dashboard | `wosool_gateway`/`wosool_store`/`wosool_senders` | **Leave behind** (cloud) |

**Net new code is small** — the headless walker + CLI + adapter-mount glue. Everything load-bearing (validator, guards, refs, NIL client) is lifted intact.

---

## 4. Architecture of the kernel

```
  plan.nil.json  ─▶  nilscript run
                         │
                         ├─ validate()        ← lifted dsl/validator (V1–V6)  [refuse w/ diagnostics]
                         ├─ Executor (async)   ← port of DynamicGraphExecutorWorkflow (no Temporal)
                         │     ├─ resolve()        (dsl/references)
                         │     ├─ evaluate_guard() (dsl/guards)
                         │     ├─ node dispatch     (graph.next_after / node_map)
                         │     └─ saga unwind       (on_error: compensate)
                         └─ NilClient ───HTTP(NIL)──▶  mounted adapter  ──▶  backend
                               (nilscript.sdk)            (e.g. pocketbase-nil-adapter)
```

The **adapter** is exactly the artifact the [adapter ecosystem](./adapter-ecosystem-strategy.md) already produces — `nil-adapter-template` → `<service>-nil-adapter`. The kernel **mounts** one. This means the pivot **unifies** the two efforts: the adapters are the kernel's plugins; the template/PocketBase work is not wasted — it becomes the kernel's plugin ecosystem.

Proposed package layout (inside `nilscript`):

```
nilscript/
  nil/ dsl/ sdk/            # standard data + SDK (unchanged)
  cli/                      # existing toolkit (verbs/scaffold-shim/scan/conformance/manifest)
    run/                    # NEW: the `nilscript run` kernel entrypoint
  kernel/                   # NEW (lifted): validator, guards, references, models, executor, saga
```

---

## 5. The flywheel — kernel ↔ Wosool Cloud (clean seam)

The seam is the **Executor interface**: both implementations consume an admitted `WosoolProgram` and a NIL dispatch capability.

- **Kernel (OSS):** `LocalExecutor` — `asyncio`, in-process, best-effort, no persistence. `pip install nilscript`.
- **Wosool Cloud (commercial):** `TemporalExecutor` — the existing `DynamicGraphExecutorWorkflow`, durable/replayable, multi-tenant, dashboarded. Imports the **same** `nilscript.kernel` validator + guards + references (single source of truth — the cloud stops vendoring its own DSL engine and depends on the published kernel, just like adapters do).

Result: one DSL engine, two executors. A plan validated/previewed locally behaves identically in the cloud. The cloud's value is **durability + scale + observability**, not a different language.

---

## 6. Phased execution blueprint

### Phase 0 — Decide & de-risk (no code moved)
- [ ] **Naming/packaging lock:** confirm `nilscript` (pip) = the kernel; the spec is docs-only. Decide the published-package migration (see §7).
- [ ] **Adapter-mount model:** `--adapter-url` (HTTP, language-neutral) for v1; defer subprocess-spawn / in-process import.
- [ ] **Local durability:** v1 = none (best-effort, print trace). Optional later: a `--journal run.jsonl` append-only local log (reuses the SEQRD-PC ledger shape) — *not* full replay.
- [ ] **npm parallel:** TS port is a **later** track; v1 is Python only (don't split focus). The README may still say "npm coming."
- [ ] **Guard/version:** the kernel is a **major identity change** → version it honestly (see §7).

### Phase 1 — Implement & isolate the kernel
- [ ] Create `nilscript/kernel/` and **lift** `dsl/{models,validator,guards,references,context,diagnostics}.py` + `graph.py` from `wosool-cloud` (rename imports `wosool_convlayer.dsl`→`nilscript.kernel`). Keep them pure.
- [ ] Build `LocalExecutor` — the headless `async` port of `DynamicGraphExecutorWorkflow` + the saga unwind, dispatching via `nilscript.sdk.NilClient`.
- [ ] Build `nilscript run` CLI (argparse, matching the existing CLI style): load plan → validate → execute → emit trace; non-zero exit on validation refusal or terminal run error.
- [ ] **Tests:** port the DSL conformance corpus (`dsl/conformance/{valid,invalid}/*.json`) to drive the kernel; add executor tests against the in-memory `FakeSystem` (the one the adapters already ship) so `nilscript run` is provable with **no live backend**.
- [ ] **DoD:** `pip install -e ".[cli]"` then `nilscript run examples/<plan>.nil.json --adapter-url <fake>` runs a multi-step plan end-to-end (incl. a compensate path) in a clean env — green.

### Phase 2 — Migrate the docs & positioning (docs-first)
- [ ] Reframe the README around `pip install nilscript && nilscript run` as the **primary** onboarding (the §[saas-grade-content-plan] hero), kernel-first.
- [ ] Move the spec to a clear **"NILScript Protocol"** reference section (NIL + DSL + SEQRD-PC) — embedded, not a separate package. Keep `nil/versions/*` as the canonical source the docs render.
- [ ] Update the adapter docs to frame adapters as **kernel plugins** ("build an adapter, then `nilscript run --adapter-url`").
- [ ] Wosool Cloud page: "local headless now; connect for durable + dashboarded execution."

### Phase 3 — Lock
- [ ] Make `wosool-cloud` **depend on the published `nilscript.kernel`** for the DSL engine (delete the vendored copy → single source of truth). The cloud keeps only `TemporalExecutor` + activities + worker/gateway/store.
- [ ] Full verification: kernel suite green; conformance corpus green; cloud still green against the imported kernel; a clean-env smoke (`pip install`, run a plan).
- [ ] Freeze on a clean commit; cut the kernel release (see §7); update IMPLEMENTATIONS / topics.

**Critical path:** Phase 1 gates everything. Phase 2 (docs) can start drafting in parallel once the CLI shape is fixed. Phase 3 (cloud re-point) is last to avoid destabilizing the cloud mid-extraction.

---

## 7. Migrating the *already-published* `nilscript` package (honest)

The name `nilscript` is **already live on PyPI** as the spec + adapter toolkit (`0.2.0`, and a broken `0.2.1`/fixed `0.2.2` in flight). The pivot changes what the package *is* (now also a runtime). Handle it cleanly:

- **It's additive, not a rename.** The kernel `run` command and `nilscript.kernel` module are **added** to the existing package; the spec data + toolkit stay. So `pip install nilscript` keeps working and *gains* `nilscript run`. No name burn.
- **Version:** ship the kernel as a clear **minor** bump (e.g. `0.3.0`) with a CHANGELOG headline "NILScript is now a runnable kernel." (Per the earlier decision the current fix is `0.2.x`; the kernel is the next minor.) Reconcile the version line at Phase 3, not now.
- **Spec stays docs-only:** never publish a `nilscript-spec` package. The spec is rendered in docs from `nil/versions/*`.
- **The `[cli]/sdk` decoupling already done** (kernel needs the SDK's `NilClient`, so `run` will pull `nilscript[sdk]` — document the extra clearly).

---

## 8. Risks & honest caveats

- **Identity churn.** The package's meaning shifts from "the standard" to "the kernel that implements the standard." Mitigate with a crisp CHANGELOG + README hero; the spec remains, framed as "the Protocol."
- **Lost durability locally.** The local kernel is best-effort (a crash loses an in-flight run). This is *fine* for a dev tool and is the honest upsell to Wosool Cloud — but the docs must say so, not imply local durability.
- **Two executors can drift.** Mitigate by making the cloud import the published `nilscript.kernel` (Phase 3) so validator/guards/refs have **one** source.
- **`await_approval` semantics differ.** Durable signal (cloud) vs. local poll+timeout (kernel). Document that long human-in-the-loop pauses are a cloud feature; locally they poll/timeout.
- **Scope creep into npm/TS.** Resist in v1 — Python kernel first; TS port is a separate, later track.
- **Don't gold-plate before the kernel runs.** The viral asset is `nilscript run` working in 60 seconds; build that, then the docs/landing polish (which the [content plan](./saas-grade-content-plan.md) already stages).

---

## 9. Viral launch recipe (once locked)

- **Headline:** *"Stop letting your AI agents break your database. NILScript is a lightweight, deterministic kernel that governs agent intents and guarantees safe, previewable rollbacks — locally, in one `pip install`."*
- **The 30-second cast:** a terminal recording — `pip install nilscript` → `nilscript run plan.nil.json --adapter-url …` → it executes a pipeline, hits a failure, and **gracefully unwinds the committed steps** (the SEQRD-PC saga), printing an honest partial. That single GIF is the whole pitch.
- **The hook:** "Runs fully open-source on your own infrastructure. Build an adapter for *your* backend from the template in minutes. Scale to durable, monitored, multi-tenant execution with Wosool Cloud."
- **Surfaces:** GitHub README hero + the docs-first site + the landing (all staged in the content plan). The spec sits underneath as the authority layer (`SEQRD-PC`, NIL) — heavy, rigorous, enterprise-credible.

---

## 10. Open decisions (for sign-off)

1. **Adapter mount v1:** HTTP `--adapter-url` only (recommended), or also subprocess-spawn `--adapter <path>`?
2. **Local durability v1:** none (recommended) vs. an optional append-only `--journal` (no replay)?
3. **Kernel version:** ship as `0.3.0` (recommended) after the `0.2.x` fix lands?
4. **Cloud re-point timing:** make `wosool-cloud` import `nilscript.kernel` in Phase 3 (recommended) or keep vendored until later?
5. **npm/TS port:** explicitly out of scope for v1? (recommended yes — Python first.)

---

*This is a plan, not an implementation. Implement the kernel (Phase 1) → migrate docs/positioning (Phase 2) → re-point the cloud and lock (Phase 3). Nothing is published or migrated from this document without sign-off.*
