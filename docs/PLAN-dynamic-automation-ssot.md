# PLAN — Dynamic Automation by Conversation, Registered in an SSOT

> **Status:** design doc, local-only (not committed). Working title: *Automation Registry*.
> **Scope owner:** kernel + control plane.
> **One-line thesis:** *Talking to the agent produces a named, versioned, governed automation —
> the agent drafts it, deterministic code lowers it, a human approves it, and it lives in an SSOT
> with its own trigger, timing, lifecycle state, and run history.* The agent never owns the
> automation; the **code** does.

---

## 0. What this is, in your words → in the system's terms

You want: *"add dynamic automation automatically just by talking to the agent, register them in
an SSOT, each with its own timing and state."* Decomposed:

| Your phrasing | System concept | Exists today? |
|---|---|---|
| "just by talking to the agent" | **Conversational authoring loop**: NL → candidate plan | Partial — agent can emit a plan; no authoring surface |
| "dynamic automation … on the spot" | A `WosoolProgram` (closed JSON plan, ≤256 nodes) | ✅ [kernel/models.py:151](../src/nilscript/kernel/models.py#L151) |
| "the code does the final proposal, 100% reflecting SSOT" | **Deterministic validator** (V1–V6), total pure function: lower-or-reject | ✅ [kernel/validator.py](../src/nilscript/kernel/validator.py) |
| "lock it on a certain version" | **Content-hash** over the validated program; immutable versions | ❌ small, new |
| "register them in an SSOT" | **AutomationDefinition** registry table (append-only versions) | ❌ new — the spine of this doc |
| "its own timing" | **TriggerSpec**: schedule / event / manual | ❌ new |
| "its own state" | **Lifecycle state machine** (definition) + **run state** (execution) | Half — run trace exists, lifecycle does not |
| "results reflected from sales→marketing→accounting" | **Cross-adapter dispatch + handoff** | ❌ new — the hard, deferred part |
| "it closed the gap of data integrity" | **Choice Gate + universal field resolver** (fuzzy ref → verified ID) | ✅ [scaffold/_templates.py:248](../src/nilscript/cli/scaffold/_templates.py#L248) |

**The reframe that matters:** ~70% of the *execution engine* already ships. This plan is mostly
about a **registry, a trigger model, and a lifecycle** wrapped around the existing kernel — not a
new engine. The genuinely hard, genuinely new part (cross-system semantic mapping + authority
composition) is isolated in Phase 3 and **does not block launch**.

---

## 1. The invariant we will not break

> The agent is an **untrusted proposer**. The transformation from "agent's draft" to "registered,
> runnable automation" is a **total, deterministic function** that either emits a content-addressed,
> validated automation or a precise structured refusal. No probabilistic step sits between intent
> and a registered effect.

Everything below is in service of that sentence. The moment registration depends on the model's
judgment rather than the validator's verdict, the guarantee collapses and this is just another
flaky agentic workflow builder. The kernel already enforces this for a *single run*
([validator.py](../src/nilscript/kernel/validator.py)); we are extending it to a *stored,
re-triggerable* automation.

---

## 2. The SSOT: `AutomationDefinition`

The new spine. One row = one **version** of one automation. Versions are **append-only**; "editing"
an automation writes a new version. "Lock on a version" = pin a `content_hash`.

### 2.1 Record shape (frozen, mirrors `NilModel`/`DslModel` discipline)

```python
class AutomationDefinition(DslModel):           # frozen, extra="forbid"
    automation_id: str                          # stable across versions (workspace-scoped slug)
    workspace: str
    version: int                                # monotonic; 1, 2, 3…
    content_hash: str                           # sha256 over canonical-JSON(plan); the "version lock"
    name: BilingualText                          # human label (ar/en) — reuse models.BilingualText
    description: BilingualText | None
    plan: WosoolProgram                          # the validated program (already a closed AST)
    trigger: TriggerSpec                         # schedule | event | manual (§3)
    state: AutomationState                       # draft|pending_approval|active|paused|archived (§4)
    authored_by: str                             # grant_id of the agent/session that drafted it
    approved_by: str | None                      # owner who approved (None until approved)
    created_at: datetime
    superseded_by: int | None                    # version number that replaced this one
```

### 2.2 Why content-hash is load-bearing

- **Reproducibility.** A scheduled run months later executes *exactly* the bytes a human approved —
  not "whatever the agent regenerates today." The hash is the contract.
- **Drift detection.** If anything edits the stored plan out-of-band, the hash mismatches and the
  run refuses. This is the same honesty discipline as the manifest drift-guard
  ([NIL-paper-additions.md §E](./NIL-paper-additions.md)).
- **Idempotent registration.** Re-proposing an identical plan is a no-op (same hash) — the agent
  can't accidentally fork an automation by re-running the conversation.

Canonicalization: `json.dumps(plan.model_dump(by_alias=True), sort_keys=True, separators=(",",":"))`
→ `sha256`. Deterministic, matches the existing `nil_uuid` philosophy
([sdk/idempotency.py](../src/nilscript/sdk/idempotency.py)).

### 2.3 Storage

New table in the existing control-plane store ([controlplane/store.py](../src/nilscript/controlplane/store.py)),
alongside `events` / `approvals` / `adapters`:

```sql
CREATE TABLE automations (
    automation_id   TEXT NOT NULL,
    workspace       TEXT NOT NULL,
    version         INTEGER NOT NULL,
    content_hash    TEXT NOT NULL,
    name            TEXT NOT NULL,        -- JSON BilingualText
    plan            TEXT NOT NULL,        -- JSON WosoolProgram
    trigger         TEXT NOT NULL,        -- JSON TriggerSpec
    state           TEXT NOT NULL,
    authored_by     TEXT,
    approved_by     TEXT,
    created_at      TEXT NOT NULL,
    superseded_by   INTEGER,
    PRIMARY KEY (workspace, automation_id, version)
);
CREATE INDEX idx_auto_active ON automations(workspace, state);
```

Append-only is the same model already proven for `events`. The registry reuses the store's existing
thread-safe SQLite plumbing — no new infrastructure.

---

## 3. Timing: the `TriggerSpec`

"Its own timing" = a closed, discriminated union (same pattern as the node set, so an unknown
trigger type is unrepresentable):

```python
class ScheduleTrigger(DslModel):
    type: Literal["schedule"]
    cron: str | None = None                 # "0 9 * * *"  (validated against croniter)
    interval_seconds: int | None = None     # OR fixed interval
    timezone: str = "Asia/Riyadh"

class EventTrigger(DslModel):
    type: Literal["event"]
    on_verb: str = Field(pattern=VERB_PATTERN)   # e.g. "crm.create_lead"
    on_event: Literal["executed","refused","rolled_back"] = "executed"
    match: dict[str, Any] = Field(default_factory=dict)  # field filter over the envelope
    source_adapter: str | None = None       # which backend's events (Phase 3 multi-adapter)

class ManualTrigger(DslModel):
    type: Literal["manual"]                 # only fires on explicit run request

TriggerSpec = Annotated[ScheduleTrigger | EventTrigger | ManualTrigger,
                        Field(discriminator="type")]
```

### 3.1 EventTrigger rides the existing ledger

The control plane **already ingests every NIL event** into an append-only timeline
([controlplane/store.py](../src/nilscript/controlplane/store.py), `events` table, HMAC-verified
`/events/ingest`). An `EventTrigger` is therefore **a subscriber on a stream that already exists** —
"when a lead is created in Odoo, run automation X" is: match the incoming `executed` envelope for
`crm.create_lead` against `match`, and if it fits, dispatch a run. No new event bus; we tap the
ledger that's already the system's SSOT for what happened.

### 3.2 ScheduleTrigger → Temporal, not a homegrown cron

The durable executor is already a Temporal workflow in the cloud sibling
(`DynamicGraphExecutorWorkflow`). **Temporal Schedules** are the correct home for `ScheduleTrigger`
— do not hand-roll a scheduler with its own clock and persistence. The local asyncio executor
([kernel/executor.py](../src/nilscript/kernel/executor.py)) stays the dev/offline path; the
scheduled/durable path is Temporal. This respects the existing "local sibling / durable cloud"
split rather than inventing a third runtime.

---

## 4. State: two distinct state machines

People conflate these. They are different and both needed.

### 4.1 Definition lifecycle (the automation as a registered thing)

```
draft ──propose──▶ pending_approval ──owner approve──▶ active ⇄ paused ──▶ archived
   │                      │                                                    ▲
   └──────────────────────┴─────────── owner reject / supersede ──────────────┘
```

- `draft` — agent emitted it, validator passed it, not yet approved. No trigger armed.
- `pending_approval` — sitting on the **existing human-approval gate**
  ([controlplane/app.py](../src/nilscript/controlplane/app.py) `/proposals/{id}/await` →
  `/decision`). Registering a *recurring automation* is a HIGH-tier act by definition — it should
  always pass through the gate, never auto-arm.
- `active` — trigger armed; eligible to fire.
- `paused` — trigger disarmed; definition retained. Owner toggle.
- `archived` — terminal; superseded or retired. New version → old version `superseded_by` set,
  old version archived, new version enters at `draft`.

### 4.2 Run state (one execution of an automation)

This already exists as the executor trace — we just persist and link it. The executor returns
`{completed, partial, blocked_at, refusal, compensated, notifications, context}`
([NIL-paper-additions.md §A.4](./NIL-paper-additions.md)). A run row:

```sql
CREATE TABLE automation_runs (
    run_id          TEXT PRIMARY KEY,     -- deterministic: f"{automation_id}:{version}:{trigger_fire_id}"
    automation_id   TEXT NOT NULL,
    version         INTEGER NOT NULL,
    content_hash    TEXT NOT NULL,        -- which exact bytes ran
    workspace       TEXT NOT NULL,
    fired_by        TEXT NOT NULL,        -- "schedule" | "event:<event_id>" | "manual:<grant_id>"
    state           TEXT NOT NULL,        -- running|completed|partial|blocked|failed|compensated
    trace           TEXT,                 -- JSON executor trace
    started_at      TEXT NOT NULL,
    ended_at        TEXT
);
```

`run_id` determinism (automation+version+fire) means a re-delivered trigger replays the same run —
the same idempotency philosophy as `idem_key(run_id, node_id)` already in
[kernel/graph.py](../src/nilscript/kernel/graph.py). **A double-fired schedule cannot double-execute.**

Every node inside a run still emits its `proposed`/`executed`/`refused` events to the ledger, so the
**single-pane audit already shows the full journey** of every automated run for free — no new
observability surface.

---

## 5. The conversational authoring loop (the "just by talking" part)

This is the new product surface. It is a **state machine the agent drives but does not control the
verdict of.** Sequence:

```
1. Owner (NL):  "Every morning, pull yesterday's new Odoo leads and create a follow-up task for each."
2. Agent reads:  - the NL intent
                 - the capability registry = describe() skeleton of the workspace's adapter(s)
                   (verbs + targets + field schemas) — kernel/connect.py handshake
3. Agent emits:  a candidate WosoolProgram (JSON) + a candidate TriggerSpec.  ← UNTRUSTED
4. CODE lowers:  validator V1–V6 over the plan, against the live skeleton.    ← DETERMINISTIC
                   ├─ reject → structured refusal (which node, which verb, why) → back to step 3
                   └─ pass  → content_hash computed, AutomationDefinition built in `draft`
5. PREVIEW:      bilingual human-readable plan summary (reuse node `preview`/`notify` rendering)
                 + the trigger in plain words ("daily at 09:00 Asia/Riyadh").
6. GATE:         register as `pending_approval`; owner approves via existing control-plane gate.
7. ACTIVE:       trigger armed. The automation now lives in the SSOT, independent of the chat.
```

**Critical discipline at step 4:** the validator is the *only* thing that turns a draft into a
registrable artifact. The agent's job ends at "emit a candidate." If V4 (whitelist) finds a verb the
backend never declared, the draft is refused — the agent cannot talk its way past it. This is the
multi-step generalization of NIL's skeleton-bounded guarantee, now applied at **registration time**,
not just run time.

### 5.1 New verbs / tools the agent uses (themselves NIL-governed)

The authoring loop is itself expressed as governed operations — dogfooding the model:

| Verb | Tier | Effect |
|---|---|---|
| `automation.draft` | — (read-ish) | submit candidate plan+trigger → returns validator verdict + preview (no side effect) |
| `automation.register` | HIGH | promote a passed draft to `pending_approval` (two-step: propose→commit) |
| `automation.activate` / `automation.pause` | HIGH | arm/disarm trigger (operator-grade, like adapter activation) |
| `automation.run` | per-plan tier | fire a `manual` trigger now |
| `automation.list` / `automation.describe` | read | SSOT read-back of registered automations + versions |

`automation.draft` returning the **validator verdict** (not an execution) is the key: it's the
"propose" half — preview-only, no effect — applied to *the automation itself*. Same two-step
discipline NIL uses for every write.

---

## 6. Cross-system (sales → marketing → accounting): the deferred hard part

This is the part of your vision that is **genuinely new and genuinely hard**, and it is correctly
**out of the launch path**. Three sub-problems, in increasing difficulty:

### 6.1 Cross-adapter dispatch (smallest)
Today every node hits the *one* active adapter ([kernel/models.py:153](../src/nilscript/kernel/models.py#L153),
one `workspace`). Give a node an optional `adapter` field and route per-node using the registry that
**already holds multiple adapters per workspace**
([controlplane/store.py](../src/nilscript/controlplane/store.py) `adapters` table). ~1–2 days for the
mechanism. Low conceptual risk.

### 6.2 Cross-system reference handoff (hard)
Step in Odoo outputs a lead id; step in the accounting system needs the *corresponding* account.
The reference plumbing (`$.step_k.field`) and the per-adapter Choice Gate both exist — but **Odoo's
"customer" is not the accounting system's "account."** This is **ontology mapping, not plumbing**,
and it is the real 80%. For a demo, hardwire one mapping. For a product, this is a mapping registry
all its own.

### 6.3 Authority composition (security-critical)
"Sales triggers marketing triggers accounting" composes *permissions* across departments. An
agent-composed cross-boundary automation is a **confused-deputy surface**: the automation runs with
*whose* authority at each hop? Grants are per-workspace today. Cross-boundary needs **explicit
per-edge authority** declared in the plan and checked by a guard, never inherited silently. This must
be designed before any cross-org automation ships — it is not polish.

> **Verdict on §6:** name it in the deck as the vision ("single governed op → composed governed
> workflow across N systems"), demo a hardwired two-adapter slice if time allows, **build the general
> engine post-launch.** Building 6.2 + 6.3 generally before launch is the highest-EV way to miss the
> deadline (bus factor 1, MVP scope = single-instance correctness).

### 6.4 Cross-system composition — engine built + tested (P3 core)

`tests/test_automation_compose.py` (7 tests, incl. a real run across **two** in-memory PocketBase
backends where a value committed on adapter A drives a write on adapter B).
[src/nilscript/automation/compose.py](../src/nilscript/automation/compose.py):

- A **composed plan** is an ordered list of `Stage(name, adapter, plan, input_from)`. Each stage is a
  normal single-adapter `WosoolProgram` run by the **unchanged** `LocalExecutor` against *its own*
  adapter — no kernel changes, so P1/P2 and the 345 prior tests are untouched.
- **6.1 dispatch** — solved by per-stage adapter binding (the `run_stage` the caller supplies picks
  the client per stage); the registry already holds multiple adapters per workspace.
- **6.2 handoff** — `input_from` threads a prior stage's output (`$.stage_1.step_2.output.id`) into
  the next stage's `$.input.*`. **Honest boundary:** the mapping is *author-declared, not inferred* —
  we don't pretend A's "customer" is B's "account"; B's own Choice Gate still resolves the handed
  value to a verified id. `validate_composed` checks each stage against its adapter's skeleton and
  rejects a handoff that references a non-prior stage.
- **6.3 authority** — *per-stage by construction*: each stage runs with its own adapter's
  credentials; the handoff carries data values, never authority — so a composed plan cannot escalate
  across a boundary (confused-deputy-safe).

**Composed SSOT + endpoints — wired + tested** (`tests/test_automation_compose_api.py`, 5 tests). An
additive `kind` column (`single`|`composed`) on the `automations` table keeps P1's typed
`AutomationDefinition` path untouched; composed plans flow through the same registry as the dispatcher
already consumes them (dicts).

| Endpoint | Auth | Effect |
|---|---|---|
| `POST /automations/compose/draft` | registry token | validate each stage against **its own** adapter's live skeleton (`adapter_skeleton_provider`); return verdict + content-hash. No effect. |
| `POST /automations/compose/register` | registry token | persist as `pending_approval`, `kind='composed'` |
| `POST /automations/{ws}/{id}/run` | registry token | **branches on kind** — a composed automation fires via `fire_composed` (per-stage `LocalExecutor`), recorded as one run with per-stage status in the trace |

`compose_hash` is the version lock; the same lifecycle endpoints (`/state`, `/runs`, `/runs/{id}`)
serve both kinds. Single- and composed-plan automations coexist in one registry.

**Still genuinely out of scope (honest):** (a) a *single* stage that needs two backends' authority at
once — true authority composition; (b) *inferred* ontology mapping — we require it author-declared.
Both are real research/product, not a wiring step. Everything else of the P3 vision now runs.

---

## 7. Phasing — what's launch-safe vs. what isn't

| Phase | Deliverable | New surface | Effort | Launch? |
|---|---|---|---|---|
| **P1** | `AutomationDefinition` SSOT + content-hash version-lock + `ManualTrigger` only + `automation.draft/register/run/list` + authoring loop (single adapter) | registry table, 5 verbs, hash | ~3–4 d | ✅ **shippable** — fully demonstrates "talk → validated → registered in SSOT with state" |
| **P2** | `ScheduleTrigger` (Temporal Schedules) + `EventTrigger` (tap the ledger) + `automation_runs` table + lifecycle state machine + activate/pause | scheduler/dispatcher, run table | ~1–2 wk | ⚠️ post-launch unless the timeline allows; adds the durable "timing" |
| **P3** | Cross-adapter dispatch (6.1) → handoff (6.2) → authority composition (6.3) | per-node routing, mapping registry, per-edge guards | weeks | ❌ **v2**, post-merchants/post-raise |
| **Paper** | One formal proposition: boundary guarantee generalized from single op → a *registered, re-triggerable* plan; content-hash = reproducibility lemma | docs only | ~½ d | ✅ pure leverage |

**P1 alone is a complete, honest story:** you talk to the agent, it drafts an automation, the code
validates and content-hashes it, the owner approves it, and it sits in a queryable SSOT with a
lifecycle state — runnable on demand. That is *"dynamic automation by conversation, registered in an
SSOT, with its own state"* — minus only the autonomous timing (P2) and cross-system (P3).

---

## 8. Risks / open questions

1. **Expression sandbox.** `ConditionNode.expression` and `ForeachNode.items` are strings evaluated
   over prior outputs. For stored, autonomously-firing automations the evaluator **must** be a
   sandboxed, non-Turing-complete expression language (no `eval`). Verify what
   [kernel/references.py](../src/nilscript/kernel/references.py) /
   [kernel/executor.py](../src/nilscript/kernel/executor.py) do today before P2 — a stored automation
   firing unattended raises the bar vs. an interactively-driven run.
2. **Skeleton drift between registration and fire.** A plan validated against today's skeleton may
   reference a verb a backend later drops. Re-run **V4 at fire-time**, not just registration-time;
   refuse + alert on drift rather than execute against a changed surface.
3. **Trigger storms / loops.** An `EventTrigger` whose automation emits an event matching its own
   filter is an infinite loop. Need per-automation rate limits + cycle detection across the
   *trigger graph* (automation A's effect fires automation B's trigger fires A…).
4. **Approval fatigue.** If every fire of a HIGH-tier automation re-prompts a human, autonomy is
   lost. Decide: approve the *definition once* (the recurring authority is granted at activation) vs.
   approve *each fire*. Likely: definition-level approval arms the trigger; individual fires run
   under the authority granted at activation, with per-fire audit. This is itself an authority-
   delegation decision and must be explicit.
5. **Versioning UX.** When the owner edits an automation by talking again, is it a new version of the
   same `automation_id` (supersede) or a new automation? Default: supersede, archive the old, require
   re-approval of the new version.

---

## 9.5 Honest status — what P1 ships today (built + tested)

**Built and green** (`tests/test_automation.py`, 12 tests; full suite 315 passing):

- **The SSOT record** — `AutomationDefinition` + the closed `TriggerSpec` union
  (`manual`/`schedule`/`event`), frozen and unknown-member-rejecting, in
  [src/nilscript/automation/models.py](../src/nilscript/automation/models.py). Workspace is taken
  from the validated plan so the two cannot drift.
- **The version lock** — `content_hash()`: deterministic SHA256 over canonical-JSON of the plan.
  Identical plans hash identically (idempotent registration); any arg change moves the lock.
- **The deterministic draft gate** — `draft_automation()` in
  [src/nilscript/automation/authoring.py](../src/nilscript/automation/authoring.py): runs the kernel
  validator (V1–V6) over the agent's candidate; a hallucinated verb (`V4`) or forward reference
  (`V6`) is refused with structured diagnostics and **no** definition is produced. This is the
  agent-untrusted / code-decides boundary, realized.
- **Append-only SSOT persistence** — `register_automation` / `get_automation` / `list_automations`
  / `set_automation_state` on the existing control-plane store
  ([src/nilscript/controlplane/store.py](../src/nilscript/controlplane/store.py)). Editing writes a
  new version and archives + `superseded_by`-links the prior one; re-registering an identical plan
  is an idempotent no-op; `register()` lands a new automation in `pending_approval` (never
  auto-armed); lifecycle transitions (`active`/`paused`, with `approved_by`) work.

**Agent-facing HTTP surface — wired + tested** (`tests/test_automation_api.py`, 12 tests). On the
control-plane app ([src/nilscript/controlplane/app.py](../src/nilscript/controlplane/app.py)):

| Endpoint | Auth | Effect |
|---|---|---|
| `POST /automations/draft` | registry token | lower the candidate against the **live skeleton**; return verdict + content-hash, or a structured refusal. No side effect. |
| `POST /automations/register` | registry token | persist a passing draft as `pending_approval`; a failing plan is refused (400), never stored; identical plan is idempotent |
| `GET /automations?workspace=` | public | latest version of each automation (no secrets in the record) |
| `GET /automations/{ws}/{id}` | public | one automation (optional `?version=`) |
| `POST /automations/{ws}/{id}/{version}/state` | registry token | arm/approve/pause/archive; approving records `approved_by` |

The `ValidationContext` is built from the workspace's **active adapter** `describe()` skeleton
([src/nilscript/automation/skeleton.py](../src/nilscript/automation/skeleton.py)): verbs→`SkillSpec`
whitelist, workspace granted exactly those verbs. The skeleton source is injectable
(`skeleton_provider`), so the gate is tested without a backend; production uses the live NIL
handshake. Arming is operator-gated (registry token), consistent with adapter activation.

**Manual dispatcher — wired + tested** (`tests/test_automation_dispatch.py`, 8 tests, incl. a real
end-to-end run through `LocalExecutor` against the in-memory PocketBase shim reaching `executed`).
[src/nilscript/automation/dispatch.py](../src/nilscript/automation/dispatch.py) +
`automation_runs` table:

| Endpoint | Auth | Effect |
|---|---|---|
| `POST /automations/{ws}/{id}/run` | registry token | fire the **active** automation now; requires `idempotency_key`. Only an `active` automation runs (gate); a re-fire with the same key **replays** (no double-execute); the run records its terminal state + executor trace |
| `GET /automations/{ws}/{id}/runs` | public | newest-first run history |
| `GET /runs/{run_id}` | public | one run with its full trace |

`run_id = "{automation_id}:v{version}:{idempotency_key}"` pins the exact stored version and makes
re-delivery idempotent. RunResult → run state: `completed` / `compensated` / `blocked` / `partial` /
`failed`. The runner is injectable (`runner=`), defaulting to a `LocalExecutor` over the workspace's
active adapter — so the gate/idempotency/lifecycle are tested with a fake runner and the *execution*
is proven against a live in-process adapter. Every node still emits its events to the ledger, so an
automated run shows up in the single-pane audit for free.

**Triggers — wired + tested** (`tests/test_automation_scheduler.py`, 10 tests).
[triggers.py](../src/nilscript/automation/triggers.py) (pure evaluation) +
[scheduler.py](../src/nilscript/automation/scheduler.py):

- **Event triggers** — evaluated in the ingest path: when a new event lands in the ledger,
  `dispatch_event` fires every active `EventTrigger` automation in that workspace whose
  verb/event/field-filter matches. Spawned off the request path (`asyncio.create_task`) so ingest
  stays fast. **Loop guard:** events carrying `grant="control-plane"` (a triggered run's own output)
  never re-trigger — breaking the A-fires-B-fires-A cycle (§8.3). Idempotent on the triggering
  event id.
- **Interval schedules** — `POST /automations/tick` (operator-gated) runs `run_due_schedules`: fire
  every active interval-`ScheduleTrigger` automation due as of now (gated on its last run). The
  control plane decides *which are due*; an **external clock owns the tick** (cron / Temporal
  Schedule hitting the endpoint) — no in-process durable scheduler hand-rolled.

Triggered fires reuse `fire_manual`, so they inherit the governance gate (must be `active`), version
pinning, idempotency, and recorded trace — identical to a manual run.

**Cron — now fires locally too** (`tests/test_automation_scheduler.py`, +3 tests). A self-contained
5-field matcher ([triggers.py](../src/nilscript/automation/triggers.py) `cron_matches`) supports the
common subset (`*`, `*/n`, ranges, lists, exact; day-of-week Sun=0/7). `schedule_due` fires a cron at
most once per matching minute (gated on last run); `POST /automations/tick` drives both interval and
cron. No new dependency — for full cron semantics, swap in `croniter` behind the same `cron_matches`
seam when the durable Temporal runtime lands.

---

## 9.6 The agent-facing last mile — MCP tools + live smoke (built + tested)

- **MCP automation tools** (`tests/test_mcp_automation_tools.py`, 4 tests, MCP tool → CP app → SSOT).
  [src/nilscript/mcp/automation_tools.py](../src/nilscript/mcp/automation_tools.py) +
  `_register_automation_tools` in [mcp/server.py](../src/nilscript/mcp/server.py): `nil_automation_draft`
  / `register` / `approve` / `run` / `list`. Thin authenticated relays to the control plane (reusing
  `NIL_REGISTRY_URL`/`NIL_REGISTRY_TOKEN`), bound only when a registry is configured. This is the
  literal "**by talking**" path: the agent drafts → the code validates → registers → an owner approves
  → the agent fires. Gate preserved (draft = preview-only; register = pending_approval; run = active).
- **Live smoke script** ([scripts/smoke_automation.py](../scripts/smoke_automation.py), stdlib-only):
  drives draft→register→approve→run against a *running* control plane + adapter, exercising the
  production glue the suite mocks — the real `describe()` handshake and the control-plane grant minting
  that runs `LocalExecutor` against a live backend. **Run this once on the live stack before the demo.**

## 9.7 Dashboard — automations are visible + controllable (built + tested)

`tests/test_automation_ui.py` (3 tests). The single-pane control plane
([controlplane/app.py](../src/nilscript/controlplane/app.py)) now has an **Automations** panel
alongside the existing timeline/adapters/routing:

- **View** (`GET /api/automations`, public): every automation (latest version, all workspaces) as a
  card — name, **state badge** (draft/pending/active/paused), **kind** (single/composed), **trigger**
  (manual / `cron …` / `on <verb>`), version + short content-hash, and an expandable **run history**
  (`/automations/{ws}/{id}/runs`, with per-run state). The heavy plan is summarised, not shipped.
- **Control** (token-gated, per [[nilscript-active-adapter-auth]]): Approve→active, Pause/Resume, and
  Run-now buttons. Honoring "controls need the registry token", the browser holds **no** token by
  default — the operator pastes their `NIL_REGISTRY_TOKEN` into a local field (kept in
  `localStorage`, this browser only); control calls send it as the bearer. **The server posture is
  unchanged** — the same `_registry_authed` gate; no token ⇒ view-only. This reconciles the explicit
  ask for browser control with the token-gated rule: the gate stays, the operator supplies the key.

## 9. Recommendation

Build **P1 + the paper proposition** now. It is real, launch-safe, and it lands the entire
conceptual claim ("talk → deterministic lowering → SSOT registration → state") on top of the engine
you already shipped. Defer **P2** unless the launch timeline has slack, and **P3** to v2. Resist
generalizing §6.2/§6.3 before launch — that is the separate product (*governed automation across
enterprise systems*) wearing the costume of a feature.
