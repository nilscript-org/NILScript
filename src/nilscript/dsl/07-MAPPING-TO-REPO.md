# 07 — Mapping to the Repository

> The bridge between the language draft and the running code. Every Wosool concept is mapped to
> the file/class that implements it (🟢), partly implements it (🟡), or where the net-new code
> will live (🔴). This is what makes the spec *grounded* rather than aspirational.

Paths are relative to the repo root.

---

## 1. Layer-by-layer

### Generation layer — "the compiler"

| Wosool concept | Repo location | Status |
|---|---|---|
| LLM emits the plan | `packages/wosool_convlayer/src/wosool_convlayer/agents/llm_agent.py` (`ToolCallingAgent`), `agents/intent.py` | 🟡 emits intents/batches, not yet full graphs |
| Per-skill tools / structured output | `wosool_convlayer/llm.py` | 🟡 |
| Resolved intent / batch | `ResolvedIntent`, `ResolvedBatch` (`agents/intent.py`) | 🟢 the "1 vs N" branch already exists |
| Hints (not typed values) | `ResolvedIntent.hints: dict[str, str]` | 🟢 the hint discipline is enforced |

> Today the agent emits **one or N intents**; the DSL extends that to **a graph of N typed
> nodes with control flow**. `ResolvedBatch` is the seed of `parallel`.

### Validation layer — "the compiler frontend"

| Wosool concept | Repo location | Status |
|---|---|---|
| `WosoolDSLValidator` (V1–V6 pipeline) | *net-new* — proposed `wosool_convlayer/dsl/validator.py` | 🔴 |
| Schema gate (V1) | new `nilscript-dsl/schema/*.json` + Pydantic models mirroring `NilModel` discipline | 🔴 schema drafted, code 🔴 |
| Whitelist (V4) | **`skills/registry.py::SkillRegistry.offers/for_intent`** + **`nilscript/sdk/grants.py::scope_allows`** | 🟢 reuse as-is |
| Argument typing (V5) | each skill's `hint_schema` (`skills/product.py`, …) + `skills/base.py` parsers | 🟢 schemas exist |
| Arg/preview shape | `nilscript/sdk/sentences.py` (`ProposeBody`, `ProposalBody`, frozen + `extra="forbid"`) | 🟢 |
| Refusal taxonomy for diagnostics | `nilscript/sdk/refusals.py` (`RefusalCode`, `RETRIABLE_REFUSALS`) | 🟢 |
| Tenant scopes | `wosool_convlayer/tenancy.py` (`Tenant.scopes`), `TenantProvider` | 🟢 |

### Durable runtime layer — "the virtual machine"

| Wosool node | Repo primitive (`packages/wosool_worker/src/wosool_worker/`) | Status |
|---|---|---|
| `DynamicGraphExecutorWorkflow` (the interpreter) | *net-new* — proposed `workflows.py` addition | 🔴 |
| `action` (commit + retry + idempotency) | `workflows.py::IntentTaskFlow` (key `parent_turn_id:task_id`, bounded `RetryPolicy`) | 🟢 |
| `parallel` / fan-out + ONE reply | `workflows.py::MultiIntentFlow` | 🟢 |
| `await_approval` | `workflows.py::AwaitDecisionFlow` (`POLL_STATUS`, terminal-state map) | 🟢 |
| `wait` (durable delay) | `workflows.py::FollowUpFlow` (cancel signal, `wait_condition` timeout) | 🟢 |
| `query` + `notify` | `workflows.py::MorningBriefing` (`QUERY` + `render_briefing` + `SEND_OUTBOUND`) | 🟢 |
| NIL activities | `activities.py` (`COMMIT`, `QUERY`, `POLL_STATUS`, `SEND_OUTBOUND`) | 🟢 |
| Worker registration | `worker.py`, `__main__.py` | 🟢 (add new workflow here) |

### The southbound contract — NIL

| Wosool concept | Repo location | Status |
|---|---|---|
| Performatives (`PROPOSE`/`COMMIT`/`QUERY`/`STATUS`/`EVENT`) | `nilscript/sdk/sentences.py::Performative` | 🟢 |
| Cannot speak `DECIDE` | by omission in `sentences.py` (owner-plane) | 🟢 enforced by design |
| Idempotency | `CommitBody.idempotency_key`, `nilscript/sdk/idempotency.py` | 🟢 |
| Client / transport / breaker | `nilscript/sdk/client.py`, `transport.py`, `breaker.py` | 🟢 |

---

## 2. What exists vs. what's net-new (the honest scoreboard)

```
 EXISTS TODAY (🟢)                          NET-NEW FOR THE DSL (🔴)
 ───────────────────────────────────       ─────────────────────────────────
 • whitelist + scope gating                • WosoolDSLValidator (V1–V6)
 • hint discipline (args = strings)         • JSON Schema + Pydantic program models
 • PROPOSE/COMMIT/QUERY/STATUS/EVENT         • condition / foreach interpreters
 • idempotent commit + bounded retry         • DynamicGraphExecutorWorkflow (graph walk)
 • durable fan-out (MultiIntentFlow)          • $.step_k.output reference resolver
 • approval gate (AwaitDecisionFlow)          • CEL guard evaluator
 • durable wait (FollowUpFlow)                • preview renderer for a whole graph
 • query+notify (MorningBriefing)             • self-healing diagnostic → re-compile loop
 • refusal taxonomy + retriable set           • chat-channel confirm→commit handler*
```

\* The **chat confirm → commit** handler is the known prerequisite already documented in
`docs/future-plans/multi-intent-roadmap.md` (Phase 5 "connect-step, BLOCKED"). Today only MCP
has `commit_proposal`; WhatsApp/web/Telegram have no "merchant said yes → commit" path. The DSL
runtime needs it for `action`/`await_approval` to close the loop. It is therefore **the first
runtime dependency**, ahead of the interpreter.

---

## 3. Relationship to the multi-intent roadmap

`docs/future-plans/multi-intent-roadmap.md` already phases the fan-out work. The DSL **subsumes
and generalizes** it:

| Multi-intent roadmap | nilscript DSL generalization |
|---|---|
| `ResolvedBatch` (≥2 intents, flat) | `parallel` node (≥2 branches, + join policy) |
| `_fan_out_intents` (in-engine gather) | `MultiIntentFlow` dispatched by the interpreter |
| Phase 5 durable fan-out (built) | `action`/`parallel` runtime (🟢 reuse) |
| Phase 5 connect-step (chat confirm→commit, blocked) | **shared prerequisite** for the DSL runtime |
| Phase 6 observability (per-task lifecycle events) | per-node lifecycle events on the telemetry tap |

So building the DSL does **not** fork from the roadmap — it is the roadmap's natural
continuation: once a graph can be confirmed and committed from chat, the interpreter walks
*arbitrary* graphs, not just flat batches.

---

## 4. Reference-only material (do not port)

`intent-resolver/` (the orchestrator bundle) is **reference-only** — mine it for concepts
(tiered entity resolution, `tool_catalog`, `resolve_tool`, pre-segmentation, `normalize_arabic`)
but never port its schema into `packages/`. Our schema is the source of truth. Relevant DSL-side
ideas to harvest later:

- `intent-resolver/src/app/strategic/intent_schema.py`, `tool_catalog.py` — a generic
  intent/tool catalog (informs a richer V4 routing layer, Phase 3 of the roadmap).
- `intent-resolver/src/app/services/execution_packet_builder.py`,
  `temporal/workflows/base_tool_workflow.py` — their "execution packet" is a cousin of our
  admitted graph; useful as a design reference for `DynamicGraphExecutorWorkflow`.
- `intent-resolver/src/app/tar/` — tiered entity resolution (the `$.step_k` cousin "@type_n"
  pointers + recent-entities pool); informs Phase 4 argument resolution.

---

Next: **[08-ROADMAP.md](08-ROADMAP.md)** — the build order.
