# 08 — Implementation Roadmap

> The build order from "spec on paper" to "LLM-authored graphs running durably." Each phase has
> a clear deliverable, a definition of done, and the existing code it reuses. Phases are
> ordered by dependency, not ambition: the validator and the confirm→commit handler come first
> because everything else needs them.

Reuses the status legend from [00-INDEX.md](00-INDEX.md). Aligns with
`docs/future-plans/multi-intent-roadmap.md`.

---

## Phase 0 — Specification (this directory) ✅

**Deliverable:** the language draft — grammar, validation, execution model, stdlib, examples,
mapping, schema. **Done:** these files exist and are internally consistent. *(You are here.)*

---

## Phase 1 — The validator (compiler frontend) 🔴 — *highest priority*

**Why first:** nothing executes un-admitted. The validator is pure, testable without an LLM or
Temporal, and de-risks the whole language. It is also the cheapest to build (no infra).

**Deliverable:** `wosool_convlayer/dsl/` —
- `models.py` — Pydantic program/node models (mirror `NilModel`: frozen, `extra="forbid"`).
- `validator.py` — the V1–V6 pipeline returning the structured `{result, diagnostics}`.
- reuse `skills/registry.py` (V4) + `grants.scope_allows` + each skill's `hint_schema` (V5).

**Definition of done (TDD):**
- Unit tests for each pass: schema reject, dangling ref, cycle (Kahn), scope-denied,
  arg-type, forward-ref, reachability. Property: a known-good graph admits; each known-bad
  graph fails with the right `code`.
- ≥80% coverage (repo gate). ruff + mypy `--strict` clean.
- Golden corpus: the five programs in [06-EXAMPLES.md](06-EXAMPLES.md) admit; the rejected one
  fails with all three expected diagnostics.

---

## Phase 2 — Chat confirm → commit handler 🔴 — *runtime prerequisite*

**Why second:** the known blocker (multi-intent roadmap Phase 5 connect-step). Without a
"merchant said yes → commit" path on chat channels, no `action`/`await_approval` graph can close
its loop. Today only MCP has `commit_proposal`.

**Deliverable:** in `wosool_convlayer` (engine) + `wosool_gateway` —
- detect a confirmation utterance (bilingual; per-channel), map it to the pending proposal
  id(s) bound for that conversation (`notifications.py::ProposalDirectory`), issue the NIL
  `COMMIT` with the deterministic idempotency key.

**Definition of done:** a single-action graph (Example 1) runs end to end on WhatsApp/web:
propose → preview → "نعم"/"yes" → idempotent commit → outcome reply. Tests for double-confirm
(idempotent), wrong/expired proposal, and a no-pending-proposal confirm.

---

## Phase 3 — The interpreter (the VM) 🔴

**Deliverable:** `wosool_worker/workflows.py::DynamicGraphExecutorWorkflow` — the deterministic
graph walk:
- append-only execution context; `$.step_k.output` reference resolver.
- dispatch `action`→`IntentTaskFlow`, `query`/`notify`→`MorningBriefing` activities,
  `parallel`→`MultiIntentFlow`, `await_approval`→`AwaitDecisionFlow`, `wait`→`sleep`.
- the **net-new** node executors: `condition` (CEL guard eval) and `foreach` (bounded map).

**Definition of done:** Examples 1–5 execute against the Temporal test server
(`WOSOOL_TEMPORAL_ENV_TESTS=1`). Crash-mid-graph resumes at the right node (replay test).
Idempotency under re-dispatch verified. The gated fan-out test the roadmap flags as unconfirmed
is run green in a clean env.

**Sub-deliverable:** a **CEL guard evaluator** (or JSONLogic) — a small, sandboxed,
side-effect-free expression engine. Prefer a vetted library over hand-rolling
([09-REFERENCES.md](09-REFERENCES.md)); no `eval`.

---

## Phase 4 — Preview rendering & approval UX 🔴

**Deliverable:** render an admitted graph to a step-by-step **bilingual** preview a merchant
approves before execution (axiom 3 made visible). Chat-first (numbered steps); a frontend
graph visualization is the richer follow-up (`wosool-frontend`).

**Definition of done:** every node type renders to a human-readable line; an un-renderable graph
is rejected (closing the axiom-3 loop). Approve/modify/reject maps to confirm→commit (Phase 2).

---

## Phase 5 — Self-healing loop 🔴

**Deliverable:** feed terminal diagnostics ([03 §8](03-VALIDATION-AND-TYPES.md),
[04 §7](04-EXECUTION-MODEL.md)) back to the Generation layer; the LLM re-compiles a corrected
program; bounded retry; `AMBIGUOUS` candidates drive disambiguation.

**Definition of done:** a graph that fails V4/V5 or a terminal NIL refusal triggers exactly one
bounded re-compile attempt path; after N, a bilingual "couldn't complete" (never silence).

---

## Phase 6 — Argument/entity resolution & observability 🔴

**Deliverable (resolution):** `normalize_arabic` first, then a recent-entities pool so
"the 6 I listed" / "قميص أسود" resolves to canonical references inside `args`/refs (multi-intent
roadmap Phase 4). New seam in `wosool_convlayer`, durable impl in `wosool_store`.

**Deliverable (observability):** per-node lifecycle events
(`started/resolving/dispatched/completed/failed`) on the telemetry tap; coalesced owner-progress
acks (roadmap Phase 6).

---

## Dependency graph of the phases

```
 Phase 1 (validator) ───┐
                        ├──▶ Phase 3 (interpreter) ──▶ Phase 4 (preview) ──▶ Phase 5 (self-heal)
 Phase 2 (confirm→commit)┘                                                        │
                                                                                  ▼
                                                          Phase 6 (resolution + observability)
```

Phases 1 and 2 are independent and can proceed in parallel. Both gate Phase 3. Everything after
is incremental.

---

## Guardrails carried into every phase

From the repo's standing constraints + the multi-intent roadmap's open risks:

- **Keep the classifier Anthropic-first** (a cheaper model silently dropped 5/6 products).
- **Price vs quantity are mutually-exclusive arg schemas** → distinct nodes, or a field is
  dropped. Encode in the generation prompt.
- **Idempotency key per node** `run_id:node_id` — never `uuid()` in an activity.
- **`normalize_arabic` into every match path** when Phase 6 lands.
- **NIL stays the only southbound contract; propose-only; zero business state; Arabic-first.**
- **TDD + code review + ≥80% coverage + ruff/mypy `--strict`** on every phase (repo gates).

---

Next: **[09-REFERENCES.md](09-REFERENCES.md)** — the prior art.
