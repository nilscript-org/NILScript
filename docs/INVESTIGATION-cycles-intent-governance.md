# INVESTIGATION — Cycles, Nodes, Flows, Intent & Governance (the full map)

> **Status:** deep cross-repo investigation, local doc. Written 2026-06-30.
> **Why this exists:** you felt confused about how the *Cycles page*, the *nodes/steps*, the *flow*,
> *Temporal*, *HITL*, and the *"agent only proposes intent"* rule actually fit together. They were
> built in **six different repos by different slices of work**, and three of them each invented their
> own "cycle / node / flow" model. This document untangles all of it from the actual code, names the
> one real architectural drift, and gives a clean mental model so you can prepare everything again.

---

## 0. TL;DR — read this first

1. **The philosophy is one sentence:** *the agent proposes **intent**; a deterministic kernel is the
   only thing that **commits**; an action a backend never declared is **unexpressible**, not filtered.*
   "AI proposes, code governs and executes." Everything else is plumbing in service of that line.

2. **There is not one "cycle." There are three, in three repos, with three data models** — and that
   triple is the entire source of your confusion:

   | # | Name | Repo | What it really is | Governed by the kernel? |
   |---|---|---|---|---|
   | 1 | **`Cycle` / `Flow`** | `nilscript-graph` (brain) | The *meaning* layer — a "constitution" that groups entities/roles/policies/flows for a domain (Sales, Finance). Descriptive. | n/a — it's ontology, it doesn't execute |
   | 2 | **`AutomationDefinition` / `WosoolProgram`** | `nilscript` (kernel) | The *governed execution* layer — a content-hash-locked, validator-checked, propose→commit plan. The **real** governed automation. | **YES** — this is the governed SSOT |
   | 3 | **`BusinessCycle` / `WorkflowNode`** | `os-server` (BFF) + `wosool-hub` (UI) | The *visible* drag-step builder you screenshotted ("create customer → Create Lead in Odoo → …"). | **NO** — parallel ungoverned engine |

3. **The screenshot you showed is #3 — the os-server step builder — and it is NOT a governed NIL
   automation.** It runs in os-server's own SQLite with a hand-rolled topological executor, commits
   each step under a hardcoded `grant:"cycle-engine"`, and its approval "gate" is a SQLite flag, not a
   NIL proposal and not Temporal. It bypasses the kernel's content-hash registry, the V1–V6 validator,
   and the control-plane approval gate. **This is the one real drift to fix.**

4. **"The agent only proposes intent" is true — but only on the paths the agent actually touches**
   (the MCP `nil_intent`/propose→commit gate, and the brain's `/api/assert`). The visible Cycles
   builder is driven by a *human clicking in the browser*, not by the agent — so today it sidesteps the
   intent gate entirely. The alignment you're looking for **exists in the kernel (#2) and is missing in
   the product surface (#3).**

5. **Temporal is built but not yet load-bearing in NIL.** The kernel has a tested Phase-6
   tenant-scoped durable layer (`durable_temporal.py`), but **nothing on the live path calls it yet**.
   The live HITL gate is the SQLite `approvals` table, HTTP-polled, where *approval drives execution*
   (the control plane commits on the agent's behalf). The mature Temporal HITL lives in **wosool-saas**,
   which NIL only borrows *infrastructure* (Temporal/Redis/Keycloak hosts) from, not workflow code.

If you read nothing else, read §6 (the drift) and §8 (how to make it clean).

---

## 1. The philosophy, precisely (the spine)

From the locked constitution ([POSITIONING-CONSTITUTION.md](./POSITIONING-CONSTITUTION.md)) and the
vision ([VISION-governed-automation-platform.md](./VISION-governed-automation-platform.md)):

- **NIL = Network Intent Layer.** The agent emits **one payload — an Intent (what it wants)**. The
  system **resolves → governs → executes deterministically** and returns an Outcome. No tool selection
  by the model, no keyword matching, no model-built filter. *Model intelligence is removed from the
  commit loop.* ([PLAN-intent-unification-and-durability.md §0](./PLAN-intent-unification-and-durability.md))

- **Four structural guarantees** (constitution §6):
  1. **No side effects on propose** — proposing leaves the backend byte-identical; only an approved
     commit changes state.
  2. **Skeleton-bounded** — an agent can only name verbs/targets the backend has *declared*. An
     undeclared verb has no representation to send (`β⁻¹(a) = ∅`). This is strictly stronger than
     filtering.
  3. **Honest, bounded reversibility** — every write declares reversible / compensable / irreversible;
     rollback runs a *real* compensation, never a fabricated undo.
  4. **Earned, not asserted** — success is confirmed by reading the record back; a reversibility tier
     is confirmed by a conformance run.

- **The product thesis** (vision §1): between *deterministic-but-manual* (Zapier/n8n) and
  *AI-but-ungoverned* (Lindy/Gumloop). The wedge: **the agent is generative, the validator is a total
  deterministic function** (the kernel). "AI proposes. Code governs and executes."

This is the yardstick. Every layer below either honors it or drifts from it — and naming exactly where
it drifts is the point of this doc.

---

## 2. The three "cycle/node/flow" models, side by side

This is the heart of the confusion. The same three words — *cycle, node, flow/step* — mean three
different things depending on which repo you're in.

### 2.1 Model #1 — Brain `Cycle` / `Flow` (the meaning layer)

Repo: `nilscript-graph` · `src/nilscript_graph/models.py`, `api.py`.

- A **`Cycle`** (`models.py:275`) is a *Business Cycle* — the "constitution" node that **groups**
  entities, roles, policies and flows for one domain. Fields: `cycle_id` ("sales"/"finance"), `label`
  (bilingual), `goal`, `metrics`. It carries **no members inline** — membership is **edge-based**:
  a Cycle `contains` other nodes via `Relationship(rel_type="contains")`.
- A **`Flow`** (`models.py:182`) is *"the semantic shape of Sales → Finance → Manager → System — the
  generalization of a composed automation."* It has a `trigger_event` and an ordered
  `tuple[FlowStep,…]`, each step `{order, from_role, to_role, action, condition}`. **A Flow is a member
  of a Cycle** (e.g. `flow:invoice-to-cash` is contained by `cycle:finance`).
- A **node** here is any ontology node (`Entity`, `Role`, `Policy`, `Flow`, `EventNode`, `Cycle`,
  `OperationalMapping`, …); an **edge** is a generic `from_node → to_node` with a `rel_type`
  (`contains`, `owns`, `approves`, `governed_by`, …).
- Served read-only by **`GET /api/graph/cycles`** (`api.py:223`): for each Cycle node it indexes the
  outbound `contains` edges and returns `{cycle_id, goal, metrics, members[], member_kinds{}}`.

**Key line** (`models.py:182`): *"The compiler lowers a Flow to a composed plan; the Flow says what the
coordination **means**, `compose.py` says how it **runs**."* → **Model #1 is the design-time meaning;
Model #2 is the runtime artifact it compiles into.**

### 2.2 Model #2 — Kernel `AutomationDefinition` / `WosoolProgram` (the governed execution layer)

Repo: `nilscript` (kernel) · [kernel/models.py](../src/nilscript/kernel/models.py),
[automation/models.py](../src/nilscript/automation/models.py).

- A **`WosoolProgram`** ([kernel/models.py:148](../src/nilscript/kernel/models.py#L148)) is the closed
  DSL: `{wosool:"0.1", workspace, entry, pipeline: tuple[Node,…] (1–256), on_error}`.
- A **node/step** is one of a **closed discriminated union** (an unknown type is *unrepresentable*):
  `ActionNode` (the write step: `verb`, `args`, `next`, `compensate_with`), `QueryNode` (read),
  `ConditionNode`, `ParallelNode`, `ForeachNode`, `AwaitApprovalNode`, `WaitNode`, `NotifyNode`.
- **Flow/wiring** = each node's `next` (and branch targets `on_true`/`body`/`branches`); **data
  handoff** = `$.step_k.output.field` references, type-checked at compile.
- An **`AutomationDefinition`** ([automation/models.py:93](../src/nilscript/automation/models.py#L93))
  wraps a validated `WosoolProgram` with a **`content_hash`** (SHA256 over canonical JSON — *the version
  lock*), a `TriggerSpec` (manual/schedule/event), and a lifecycle `state`
  (draft→pending_approval→active⇄paused→archived).

This is the **governed SSOT**: append-only versions, content-hash reproducibility, V1–V6 validation,
propose→commit per step. (Full mechanics in §4.)

### 2.3 Model #3 — os-server `BusinessCycle` / `WorkflowNode` (the visible builder — UNGOVERNED)

Repo: `os-server` · `app.py` · and its UI mirror `wosool-hub` ·
`src/lib/workflowTypes.ts`, `src/app/cycles/[id]/page.tsx`.

- A **`BusinessCycle`** (`workflowTypes.ts:15`) owns a **flat `nodes[]`** (steps) and a **flat
  `edges[]`** (flow) plus `triggers[]`, `version`, `active`.
- A **`WorkflowNode`** (the step) = `{node_id, label{en,ar}, adapter_id, verb (e.g. "crm.create_lead"),
  actor, gate, gate_role, input_mapping, output_fields, on_error, retry_count, …}`.
- A **`WorkflowEdge`** = `{edge_id, from_node, to_node, condition?}` — purely `from→to` by `node_id`.
- A **`CycleInstance`** is a run: `{status: running|waiting|blocked|completed|failed,
  current_node_id, node_states{}, context}`.

**This is the canvas in your screenshot.** The palette ("Odoo CRM" group, `Q`/`W` badges) comes from
`GET /api/os/contracts` (live adapter `describe` skeletons). The "Auto" badge = `gate:false` (runs
without approval); a gated node shows the approver role. "Run" calls
`POST /api/os/cycles/{id}/run`.

> **The trap:** Model #3's `BusinessCycle.nodes/edges` *looks* like Model #2's
> `WosoolProgram.pipeline` and *talks about* the same Odoo verbs — but **it is a completely separate
> schema and a completely separate engine.** It shares no code with #2 and no code with #1. See §6.

### 2.4 One picture

```
  MEANING (brain)                GOVERNED EXECUTION (kernel)         VISIBLE BUILDER (os-server/UI)
  nilscript-graph                nilscript                          os-server + wosool-hub
  ───────────────                ──────────                          ──────────────────────
  Cycle  (constitution)          AutomationDefinition (content-hash) BusinessCycle (SQLite row)
   └ contains →                   └ plan: WosoolProgram               ├ nodes[]  (WorkflowNode)
      Entity/Role/Policy/Flow        └ pipeline: Node[]               └ edges[]  (WorkflowEdge)
   Flow.steps  ──compiler──▶         (action/query/condition/…)      runs via advance_run_logic()
   "what it MEANS"               "what RUNS, governed"               "what the user DRAWS" (ungoverned)
        │                                  ▲                                    │
        └────── compile_intent ────────────┘        ❌ NO LINK TODAY ───────────┘
        (Flow → Intent → WosoolProgram)              (os-server reimplements its own engine)
```

The brain→kernel bridge (`compile_intent`) **exists and is governed**. The os-server-builder→kernel
bridge **does not exist** — that's the gap.

---

## 3. How the agent interferes with all this (intent, propose, commit, assert)

Two governed surfaces the agent actually uses. **The agent never holds standing write authority.**

### 3.1 The MCP intent gate (`nilscript` · [mcp/server.py](../src/nilscript/mcp/server.py), [mcp/tools.py](../src/nilscript/mcp/tools.py))

- **Single-surface mode** (`NIL_MCP_SINGLE_SURFACE`, default ON): the only model-facing tool is
  **`nil_intent`**, plus the keepers `nil_describe / nil_commit / nil_status / nil_rollback`. One
  payload (`about` + `where` + `seek`|`change`). A read returns a lean result; **a `change` returns a
  PREVIEW (proposal) — it does not execute.**
- **The two-step discipline:** `nil_propose`/`nil_intent` → preview, **no side effect**; **`nil_commit`
  is the ONLY tool that writes** (idempotent by `(session, proposal)`); `nil_query` reads;
  `nil_describe` lists the real verbs (don't invent others); `nil_rollback` only ever returns a
  *compensation preview* you then commit. Refusals (`UNKNOWN_VERB`, `IRREVERSIBLE`,
  `COMPENSATION_EXPIRED`, …) are **answers**, not retryable errors.
- **Verbs are discovered, not chosen:** the router (`dataplane/router.py`, `dataplane/intent.py`)
  delegates `about` to the first provider that structurally **owns** it (no keywords), and writes lower
  to the universal generic-CRUD `resource.{create,update,delete}`. Unknown rel/op → `INVALID_REL`/
  `INVALID_OP`. Default-deny on write authority lives **adapter-side** at propose time (the Odoo
  adapter's `governance.py`).

> **Naming flag:** human docs/skill say `nil_propose`; the registered tool id is **`nil_intent`**.
> Same performative, two names — worth unifying to kill confusion.

### 3.2 The brain assert path (`nilscript-graph` · `api.py:383`)

`POST /api/assert {tenant, event_type, facts}` is the **preferred** way for the agent to *act*:
**assert what is TRUE, let the brain derive what must happen.** Flow: `interpret` (read graph, fire
policies, match flow) → `derive_intent` → `resolve_bindings` (entity → `OperationalMapping` → candidate
verb by convention; missing → logged as a **gap**) → `run_event` (compile + execute through the
governed kernel) → `explain_outcome`. **Critical distinction** (`meaning/models.py:54`): the agent
asserts a **fact**; the brain derives an **Intent**; the *kernel* enforces governance. The agent never
asserts an Intent directly, and even the Intent has no execution authority.

### 3.3 The Hermes agent (`hermes-agent`) — how "propose only" is realized

- The NIL integration is **config-only**: an MCP manifest (`optional-mcps/nil/manifest.yaml` → remote
  `https://mcp.nilscript.org/mcp`) + a skill (`skills/nil/SKILL.md`). **No NIL logic in the agent
  core** — the loop is stock Hermes generic tool dispatch.
- So **"propose only" is enforced server-side** (the MCP gate; propose has no side effect by
  construction; HIGH/CRITICAL park for humans) and **steered model-side** by the skill text:
  *"You propose; you never dispose."* The SOUL files carry no NIL constraint.
- **Nuance that matters:** the agent **can** call `nil_commit` — for **LOW/MEDIUM** tiers that's the
  intended flow. HITL is **risk-tiered and kernel-enforced**, not a blanket "agent never commits."
  Calling `nil_commit` on a HIGH/CRITICAL proposal just returns "parked for approval."
- The agent can also author **multi-step automations** (`nil_automation_draft/register/approve/run`,
  `compose_register`) — and even those cross the propose→approve→commit gate (draft = no-write,
  register = pending, only `active` runs).

---

## 4. The governed automation path (Model #2) in detail

This is the path that **does** honor the philosophy end-to-end.

1. **Author (untrusted):** agent emits a candidate `WosoolProgram` + `TriggerSpec`.
2. **Lower-or-reject (deterministic):** `draft_automation` runs the **V1–V6 validator**
   ([kernel/validator.py](../src/nilscript/kernel/validator.py)) against the workspace's **live adapter
   skeleton**. **V4 whitelist** rejects any verb the backend never declared (`V4_UNKNOWN_SKILL`) or not
   granted to the workspace (`V4_SCOPE_DENIED`) — *the agent cannot talk past it.* Pass → `content_hash`
   computed.
3. **Register:** persisted as **`pending_approval`** in the append-only `automations` SSOT
   ([controlplane/store.py](../src/nilscript/controlplane/store.py)). Re-registering identical bytes is
   an idempotent no-op (same hash). **Never auto-armed.**
4. **Arm (human, operator-gated):** `→ active` requires the registry token
   ([controlplane/app.py](../src/nilscript/controlplane/app.py) `/state`). A human grants the *standing
   authority*.
5. **Fire:** `POST /automations/{ws}/{id}/run` (mandatory `idempotency_key`) → `fire_manual` →
   `LocalExecutor.execute(plan)`. Each `ActionNode` runs **propose→commit** in-process
   ([kernel/executor.py:162](../src/nilscript/kernel/executor.py#L162)). A refusal halts or triggers
   `_compensate` (saga unwind via `compensate_with`). `run_id = "{id}:v{version}:{key}"` → a re-fire
   **replays**, never double-writes. Every node emits ledger events → free audit.

### 4.1 How "agent only proposes intent" reconciles with auto-executing steps

When an armed automation runs, the executor **auto-commits** each step — there's no per-step human
click. Is that a contradiction? **No**, and here's the precise reconciliation:

- The agent's act was `draft → register` (landing `pending_approval`). **It is structurally impossible
  for the agent to make an automation fire** — arming is human/operator-gated; `fire_manual` refuses
  any non-`active` automation.
- The plan that runs is **frozen at the content-hash the human approved** and **every step was
  whitelisted at compose time** (V4). The auto-commits are bounded to a pre-approved verb set.
- Each step still does propose→commit, so **adapter-side default-deny governance + saga safety still
  apply per write.**
- **The standing authority is delegated by a human to a hash-locked program — not seized by the
  agent.** For mid-flow human checkpoints, the author inserts an `AwaitApprovalNode`.

> So "the agent proposes; only the kernel commits" holds at the level that matters: the agent never
> holds standing write authority. A human authorizes the *whole frozen plan* once at arm-time. **This
> is the correct, governed model — and it's exactly what the visible Cycles builder (#3) does NOT do.**

---

## 5. Temporal & HITL — what's real today vs. what's built-but-dormant

### 5.1 NIL kernel HITL (live path) — SQLite, HTTP-polled, *approval drives execution*

- `GATED_TIERS = {HIGH, CRITICAL}` ([mcp/tools.py](../src/nilscript/mcp/tools.py) `_gate_decision`).
  Lower tiers commit directly; gated tiers **hold**.
- Hold = a `'pending'` row in the **`approvals`** table
  ([controlplane/store.py](../src/nilscript/controlplane/store.py)), workspace-scoped (joined to the
  `events` table). The gate **fails safe**: control plane unreachable → held, never auto-committed.
- **The keystone:** on `POST /proposals/{id}/decision` `approved`, the **control plane itself commits**
  via `_execute_approved` ([controlplane/app.py:304](../src/nilscript/controlplane/app.py#L304)) —
  resolves the tenant's active adapter, builds a verb-scoped `NilClient`, calls `commit`. *"Approval
  DRIVES execution; the agent never re-commits"* and it survives MCP restarts. **No Temporal here.**

### 5.2 NIL kernel durable layer (Phase 6) — BUILT, TESTED, but NOT on the live path

- [durable.py](../src/nilscript/durable.py): tenant isolation primitives — `tenant_workflow_id`,
  `tenant_namespace` (`nil-{tenant}` = a Temporal namespace per tenant), `TenantDurablePolicy`
  (per-tenant rate/concurrency). No Temporal import.
- [durable_temporal.py](../src/nilscript/durable_temporal.py): `TenantGovernedWriteWorkflow` whose
  single activity `nil_governed_commit` runs a **governed commit** with `RetryPolicy` (backoff on
  429/transport, 8 attempts). **What becomes durable = the NIL commit**, idempotent by workflow id.
- **Finding:** grep shows the only callers are `durable_temporal.py` itself and `tests/`. **No
  controlplane/MCP code invokes it.** It's verified Phase-6 plumbing waiting to be wired — exactly the
  gap [PLAN-intent-unification-and-durability.md §7](./PLAN-intent-unification-and-durability.md)
  describes (the bulk-delete that executed ~5 of 41 due to Odoo 429s + an in-memory non-durable
  `run_bulk`). Temporal is the prescribed fix for **bulk/long/flaky** ops; single writes keep the
  direct propose→commit path.

### 5.3 wosool-saas — the mature Temporal HITL (NIL borrows infra, not code)

- Real signal-driven gate: `ApprovalBridgeWorkflow` (`packages/orchestrator/app/temporal/workflows/strategic/approval_bridge.py`)
  parks on `workflow.wait_condition(... timeout=24h)`, released by an `approval_received` **signal**;
  pending stored in MongoDB `approval_tasks`; owner replies (WhatsApp/dashboard) → `get_workflow_handle
  → signal`, Redis-bridged.
- **NIL's relationship = shared infrastructure dependency** (Temporal/Redis/Keycloak hosts), **not**
  shared workflow code. (See [[wosool-saas-deprecation]]: the Salla product tier was removed; the
  shared infra was kept because NIL depends on it.)

### 5.4 os-server Cycles "gate" — neither of the above

The visible builder's `gate:true` sets a node to `waiting_approval` and the run to `waiting` — **a flag
on a SQLite row** in os-server. Resumed by `POST /api/os/cycles/runs/{id}/advance` (marks the node
completed, re-enters the scheduler). **No Temporal, no kernel pending queue, no NIL proposal.** This is
a *third*, ungoverned HITL mechanism.

---

## 6. THE DRIFT — the one thing that's actually wrong

**The visible product surface (Model #3, the os-server `/cycles` step builder) is a parallel,
ungoverned re-implementation of what the kernel already does correctly (Model #2).**

From the os-server trace (`os-server/app.py`):

- **It does not import `nilscript` or `nilscript_graph`** — it talks to both over HTTP.
- A cycle lives in **os-server's own SQLite** (`cycles`/`runs` tables), with its **own schema** and a
  **hand-rolled topological executor** `advance_run_logic` + `_execute_node_via_adapter` (`app.py:2065`).
- Each node **does** call the *adapter's* `/nil/v0.1/propose` + `/commit` — **but** with a hardcoded
  **`grant:"cycle-engine"`** and a **self-minted proposal id**. It does **not** use `NilClient`/
  `LocalExecutor`, does **not** go through the kernel control-plane gate, and **never** registers the
  cycle as a content-hash-locked `AutomationDefinition`.
- **Therefore the cycle is ungoverned at the orchestration level:** no V1–V6 validator over the plan,
  no content-hash version lock, no `pending_approval` lifecycle, no propose→commit *at the cycle level*,
  and its HITL gate is a SQLite flag (§5.4).

What the same os-server **does** govern correctly (by proxying the kernel):
- `/api/os/automations` → proxies the kernel's governed `automations` registry (read).
- `/api/os/pending` + `/proposals/{id}/decision` → proxies the kernel's real held-proposal HITL queue
  (the agent's/MCP's gated writes).
- `/api/os/proxy/api/graph/*` → proxies the brain.

So os-server is a **correct governance broker for the agent's intents**, but a **parallel ungoverned
engine for the human-drawn cycles.** The two never meet. That mismatch is *precisely* the thing your
question kept circling: *"how does 'agent only proposes intent' align with these nodes?"* — **today it
doesn't, because those nodes don't run through the intent path at all.**

### Why this happened (not a mistake, a sequencing artifact)
The kernel automation registry (#2) and the visible builder (#3) were built in different slices. The
[VISION doc §8.3](./VISION-governed-automation-platform.md) explicitly calls for a **"canvas↔DSL
compiler"** as *"the load-bearing new component"* — i.e. the bridge from the drawn cycle to a validated
`WosoolProgram`. **That compiler was never built; os-server's local executor was used as a stand-in.**
The drift is the missing compiler, not a wrong decision.

---

## 7. Answering your exact questions

- **"How are node components linked to the cycle flow, and how does the system do it?"**
  Three different ways, one per model: brain — nodes are linked to a `Cycle` by `contains` *edges*, and
  a `Flow`'s steps are an ordered tuple (§2.1). Kernel — nodes are a `pipeline` linked by `next`/branch
  targets, data by `$.step.output` refs (§2.2). os-server/UI — a `BusinessCycle` owns flat `nodes[]` +
  `edges[]` (`from_node→to_node`), and the visible builder only ever appends a linear edge from the
  previous node (no drag-to-connect yet) (§2.3).

- **"How does the agent interfere with them?"**
  Via the MCP intent gate (`nil_intent`/propose→commit) and the brain `/api/assert` (§3). **It does not
  touch the os-server cycles builder at all** — that's human-driven in the browser. The agent's
  governed equivalent of "build a cycle" is `nil_automation_draft/register` (Model #2), which a human
  then arms.

- **"How do we manage them as Temporal?"**
  Today: we **don't** manage cycles as Temporal. The kernel's tenant-scoped Temporal durable layer
  exists and is tested but is **not wired to any live path** (§5.2). The only production Temporal HITL
  is in wosool-saas, which NIL borrows infra from, not code (§5.3). The os-server cycle gate is a SQLite
  flag, not Temporal (§5.4).

- **"How do the agent and our HITL expose this?"**
  Two *separate* HITL queues exist: (a) the **governed** kernel queue — `approvals` table, approve →
  control-plane commits (§5.1), surfaced in the UI `/decisions` page and dashboard `DecisionPanel`; and
  (b) the **ungoverned** cycle gate — `waiting_approval` SQLite flag, approve → os-server marks the node
  done (§5.4), surfaced in `/cycles/runs` (and the run-detail/advance UI isn't even built yet).

- **"How is 'agent only PROPOSE INTENT tools' aligning with these nodes?"**
  It aligns perfectly with **kernel nodes (#2)** — agent drafts/proposes, human arms, the frozen
  hash-locked whitelisted plan auto-commits under human-delegated authority (§4.1). It **does not align
  with the visible os-server cycle nodes (#3)** — those commit under a blanket `cycle-engine` grant
  outside the intent gate (§6). **Closing that gap = building the canvas→`WosoolProgram` compiler so the
  drawn cycle becomes a governed `AutomationDefinition`.**

---

## 8. How to make it clean (the prepared-again plan)

The fix is conceptually small and already designed (VISION §7, §8.3). **Collapse Model #3 into Model #2.**

1. **Build the canvas↔DSL compiler.** Lower a `BusinessCycle` (os-server `nodes[]`/`edges[]`) into a
   validated `WosoolProgram`. A `WorkflowNode{adapter_id, verb, args, gate, gate_role}` maps cleanly:
   a non-gated node → `ActionNode`/`QueryNode`; a `gate:true` node → an `AwaitApprovalNode` (so the
   human checkpoint becomes a *governed* gate, not a SQLite flag); an `edge` → the source node's `next`.
2. **Register, don't run-locally.** On Save, call the kernel `POST /automations/register` (Model #2):
   the plan gets **V1–V6 validated**, **content-hash locked**, and lands `pending_approval`. Delete
   `advance_run_logic` + `_execute_node_via_adapter`; replace "Run" with the kernel's
   `POST /automations/{ws}/{id}/run` (`fire_manual`).
3. **Unify the HITL queue.** Cycle approvals then flow through the **same** `approvals` table /
   `/decisions` UI as the agent's intents — one governance pane, not two. Kill the `waiting_approval`
   SQLite path.
4. **Kill the `cycle-engine` grant.** Every step then commits through `LocalExecutor`'s real
   propose→commit under the workspace's actual grant, with adapter-side default-deny + saga
   compensation — i.e. governed.
5. **Then (and only then) wire Temporal** for the bulk/long/flaky cycles: route `fire_manual` for
   heavy plans through `start_governed_write` (Phase 6 is already built and tested) per
   [PLAN-intent-unification §7](./PLAN-intent-unification-and-durability.md).
6. **Unify naming.** Pick one performative name (`nil_intent` vs `nil_propose`) and one word for the
   user-facing thing. Suggestion: keep **"Cycle"** for the brain's constitution layer (#1, it's a
   genuinely different concept) and rename the builder's output to **"Automation"** (matching the kernel
   SSOT and the existing `/automations` page) so the UI stops implying the builder and the brain-cycle
   are the same thing.

**Net:** after steps 1–4 there are **two** clean concepts, not three: *Cycle = meaning (brain)*,
*Automation = governed runnable plan (kernel, drawn or spoken or asserted)*. The visible builder becomes
a **front door to the governed kernel**, the agent's intents and the human's drawn automations share one
governance spine, and "the agent proposes, only the kernel commits" becomes true **everywhere**, not
just on the agent's own paths.

---

## Appendix — file map (where each truth lives)

| Concern | Repo · file |
|---|---|
| Locked philosophy / positioning | `nilscript` · [docs/POSITIONING-CONSTITUTION.md](./POSITIONING-CONSTITUTION.md) |
| Product vision / 3 front doors / canvas compiler | `nilscript` · [docs/VISION-governed-automation-platform.md](./VISION-governed-automation-platform.md) |
| Intent unification + durability gap | `nilscript` · [docs/PLAN-intent-unification-and-durability.md](./PLAN-intent-unification-and-durability.md) |
| Brain `Cycle`/`Flow`, ontology, `/api/graph/cycles`, `/api/assert`, projections | `nilscript-graph` · `src/nilscript_graph/{models,api,meaning/engine,bindings,projections}.py` |
| Kernel DSL nodes (`WosoolProgram`) | `nilscript` · [src/nilscript/kernel/models.py](../src/nilscript/kernel/models.py) |
| Governed automation SSOT + validator + dispatch | `nilscript` · [src/nilscript/automation/](../src/nilscript/automation/), [kernel/validator.py](../src/nilscript/kernel/validator.py), [kernel/executor.py](../src/nilscript/kernel/executor.py) |
| MCP intent gate (propose→commit) | `nilscript` · [src/nilscript/mcp/server.py](../src/nilscript/mcp/server.py), [mcp/tools.py](../src/nilscript/mcp/tools.py) |
| Control plane: events/approvals/HITL, tenant provisioning | `nilscript` · [src/nilscript/controlplane/app.py](../src/nilscript/controlplane/app.py), [store.py](../src/nilscript/controlplane/store.py) |
| Tenant-scoped Temporal durable layer (built, dormant) | `nilscript` · [src/nilscript/durable.py](../src/nilscript/durable.py), [durable_temporal.py](../src/nilscript/durable_temporal.py) |
| **Visible Cycles step builder (UNGOVERNED engine)** | `os-server` · `app.py` (executor `2065–2348`, schema `1654–1741`) |
| Cycles/graph/decisions UI | `wosool-hub` · `src/app/cycles/[id]/page.tsx`, `src/app/graph/page.tsx`, `src/app/decisions/page.tsx`, `src/lib/{workflowTypes,workflowApi,contractsApi,graphApi,governanceApi}.ts` |
| Hermes NIL skill + MCP manifest (config-only) | `hermes-agent` · `skills/nil/SKILL.md`, `optional-mcps/nil/manifest.yaml`, `NIL-INTEGRATION.md` |
| Mature Temporal HITL (infra NIL borrows) | `wosool-saas` · `packages/orchestrator/app/temporal/...` |
