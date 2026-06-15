# 09 — References & Prior Art

> nilscript DSL is not invented from scratch. It borrows deliberately from declarative workflow
> languages, constrained expression languages, LLM plan-generation research, and DSL design
> theory. This file records what we borrowed, the lesson, and the source — so a reviewer (or
> investor) can verify the design rests on established engineering.

---

## 1. Declarative JSON/YAML workflow languages

| System | What we borrowed | Source |
|---|---|---|
| **AWS Step Functions / Amazon States Language** | ID-addressed named-state map (`StartAt`+`States`); explicit `Next`/`End`; `$`/Reference-Path data flow (least power for plumbing); `Retry`/`Catch` error model; `ValidateStateMachineDefinition` (validate without executing; branch on `result`, not exact codes). | <https://docs.aws.amazon.com/step-functions/latest/dg/concepts-states.html> · <https://docs.aws.amazon.com/step-functions/latest/dg/concepts-input-output-filtering.html> · <https://docs.aws.amazon.com/step-functions/latest/apireference/API_ValidateStateMachineDefinition.html> |
| **CNCF Serverless Workflow** | first-class events (`listen`/`emit`); a reusable `use.functions` registry referenced by `call` (our skill catalog); semantic reference validation (`functionRef` must resolve). | <https://github.com/serverlessworkflow/specification/blob/main/dsl.md> · <https://blog.kie.org/2023/01/serverless-workflow-validations.html> |
| **Google Cloud Workflows** | named/default retry policies over hand-tuned backoff; `${}` expression discipline. | <https://docs.cloud.google.com/workflows/docs/reference/syntax> |
| **Argo Workflows** | DAG `tasks` with `dependencies`; branching on task *status*; separating small scalar params from large artifacts. | <https://argo-workflows.readthedocs.io/en/latest/walk-through/dag/> |
| **Temporal** | the deterministic-orchestration / non-deterministic-activity split; event-history replay; signals + durable timers for human-in-the-loop. *This is our runtime.* | <https://docs.temporal.io/temporal> · <https://docs.temporal.io/activities> |

**Net lesson:** model the graph as a named node map; pass data by reference path; push every
side effect into a bounded, individually-retried activity; keep the orchestration pure and
replayable.

---

## 2. Expression / data-reference sub-languages

| Language | Role in Wosool | Property we need | Source |
|---|---|---|---|
| **CEL** (Common Expression Language) | `condition`/`foreach` guards | linear-time, mutation-free, **not Turing-complete**, host cost budgets | <https://github.com/google/cel-spec> · <https://kubernetes.io/docs/reference/using-api/cel/> |
| **JSONPath** (RFC 9535) | `$.step_k.output.f` reference paths (Reference-Path subset: no filters/functions) | pure selection, no computation | <https://www.rfc-editor.org/rfc/rfc9535.html> |
| **JSONLogic** | fallback for pure-JSON, DB-storable, LLM-assembled rules | logic-as-data, never `eval`'d | <https://jsonlogic.com/> |
| **JMESPath** | optional result reshaping | read-only query | <https://jmespath.org/specification.html> |

**Net lesson:** a constrained, total expression language buys guaranteed termination,
determinism (replayable), static analyzability, and zero injection surface. The ceiling is the
feature; real computation goes into skills.

---

## 3. LLM-generated plans / agent orchestration

| Work | What we borrowed | Source |
|---|---|---|
| **OpenAI Structured Outputs / Anthropic constrained decoding** | emit schema-valid DSL *by construction* (grammar-compiled / strict mode); closed tool `enum`; `additionalProperties:false`+all-required. | <https://openai.com/index/introducing-structured-outputs-in-the-api/> · <https://platform.claude.com/docs/en/build-with-claude/structured-outputs> |
| **LLMCompiler** (arXiv 2312.04511) | LLM Planner emits a **DAG of tasks** with dependencies via placeholder variables (`$1`); a fetch unit substitutes real outputs before execution. → our `$.step_k.output` refs. | <https://arxiv.org/abs/2312.04511> |
| **ReWOO** (arXiv 2305.18323) | whole-plan-up-front, references earlier evidence by variable substitution (`#E1`) — inspectable/approvable before any side effect. → axiom 2 + preview. | <https://arxiv.org/abs/2305.18323> |
| **LangGraph** | graph of nodes/edges over typed shared state; conditional edges where the model emits only a small routing decision; deterministic code owns transitions. → our `condition`. | <https://docs.langchain.com/oss/python/langgraph/graph-api> |
| **Semantic Kernel** | the industry deprecated bespoke plan languages in favor of provider-native, schema-constrained tool calling — validates the "closed catalog + structured output" stance. | (Semantic Kernel planner deprecation notes) |

**Net lesson — the single highest-value anti-hallucination primitive:** symbolic variable
references for inter-step data, so the LLM never fabricates a value it cannot yet know; a
deterministic engine fills the real value.

---

## 4. Static validation of generated workflows

| Technique | Where in Wosool | Source |
|---|---|---|
| JSON Schema 2020-12 (closed objects, `oneOf` discriminated variants, enums) | V1 schema gate | <https://www.learnjsonschema.com/2020-12/> |
| Reference integrity (every target resolves) | V2 | (Serverless Workflow validations, above) |
| **Kahn's topological sort** for acyclicity + run schedule | V3 | <https://usaco.guide/gold/toposort> |
| Tool allowlist as `enum` + per-tool arg schema from one registry | V4/V5 | (structured outputs, above) |
| Validate-without-execute, structured diagnostics with `severity`/`location` | V-result contract | <https://docs.aws.amazon.com/step-functions/latest/apireference/API_ValidateStateMachineDefinition.html> |

**Net lesson:** a layered, deterministic, side-effect-free validator — schema → references →
acyclicity → whitelist → arg typing → reachability — with structured diagnostics serving both
engineers and the LLM repair loop.

---

## 5. Human-in-the-loop & exactly-once

| Pattern | Where in Wosool | Source |
|---|---|---|
| signal-sets-flag → `wait_condition` → durable-timer timeout race | `await_approval` | <https://docs.temporal.io/sending-messages> · <https://docs.temporal.io/workflow-execution/timers-delays> |
| activities are at-least-once → wrap side effects in idempotent activities; derive keys deterministically (never `uuid()` in the activity) | §5 of [04](04-EXECUTION-MODEL.md) | <https://docs.stripe.com/api/idempotent_requests> |
| AWS human-approval task pattern (`.waitForTaskToken`) | `await_approval` semantics | <https://docs.aws.amazon.com/step-functions/latest/dg/tutorial-human-approval.html> |

---

## 6. DSL design theory

| Idea | Where in Wosool | Source |
|---|---|---|
| **Semantic Model** — parse/validate into a separate typed model; execute *that*, not raw JSON | [03 §1](03-VALIDATION-AND-TYPES.md) | <https://martinfowler.com/bliki/SemanticModel.html> |
| **Limited expressiveness** distinguishes a DSL from a general-purpose language | axiom 5 / [01 §6](01-LANGUAGE-OVERVIEW.md) | <https://martinfowler.com/bliki/DomainSpecificLanguage.html> |
| **Totality → safety** — a non-Turing-complete total language can safely import/evaluate untrusted code; LLM output *is* untrusted code | axiom 5 | <https://docs.dhall-lang.org/discussions/Safety-guarantees.html> |
| **Configuration Complexity Clock** — keep the DSL deliberately incomplete; the moment it needs Turing-completeness you've lost the guarantees | axiom 5 / [01 §6](01-LANGUAGE-OVERVIEW.md) | <http://mikehadlow.blogspot.com/2012/05/configuration-complexity-clock.html> |
| **Make illegal states unrepresentable** — tagged unions per node kind | [02](02-GRAMMAR-AND-PRIMITIVES.md), [03 §2](03-VALIDATION-AND-TYPES.md) | <https://fsharpforfunandprofit.com/posts/designing-with-types-making-illegal-states-unrepresentable/> |

---

## 7. This repository's own grounding

The DSL is layered on this layer's existing contracts and design docs — the *primary* sources
for everything Wosool reuses:

- `plan-docs/01-IDENTITY-AND-BOUNDARIES.md` — propose-only, zero business state, hard rules.
- `plan-docs/02-NIL-CLIENT.md` — performatives, grants, idempotency, events.
- `plan-docs/03-ARCHITECTURE.md` — agents, skills, channels, workers.
- `packages/nilscript/sdk/src/nilscript/sdk/sentences.py` — the NIL sentence models (the syscall ABI).
- `packages/wosool_convlayer/src/wosool_convlayer/skills/` — the standard library.
- `packages/wosool_worker/src/wosool_worker/workflows.py` — the runtime primitives.
- `docs/future-plans/multi-intent-roadmap.md` — the fan-out roadmap the DSL continues.

---

*End of the nilscript DSL v0.1 specification set. See [00-INDEX.md](00-INDEX.md) to navigate.*
