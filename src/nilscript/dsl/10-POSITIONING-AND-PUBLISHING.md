# 10 — Positioning & Publishing Strategy

> What each piece *is*, what to open-source, and how nilscript DSL becomes a standard developers
> adopt rather than a feature buried in one app. This is the go-to-market companion to the
> technical spec — written to be handed to a cofounder, advisor, or investor.

---

## 1. Three layers, three different things — name them right

The single most common confusion is collapsing these. They are distinct, and each is published
differently.

| Layer | What it is | Analogy | Home |
|---|---|---|---|
| **NIL** | A **protocol** — the wire contract between the agent plane and any business OS (`PROPOSE`/`COMMIT`/`QUERY`/`EVENT`, refusals, grants). | The **syscall ABI / HTTP** | `nilscript` (own repo) |
| **nilscript DSL** | A **language** — a graph of NIL calls + control flow, with a grammar, validator, and runtime semantics. Compiles *down to* NIL. | The **workflow language** (AWS States Language) that emits HTTP calls | `nilscript-dsl-spec` (own repo) |
| **Wosool Cloud (wosool-cloud)** | A **runtime + product** — agents (compiler frontend), the validator, the Temporal interpreter, channels, memory, Arabic intelligence. | The **compiler + VM + the app** | this repo (closed) |

They stack: **`nilscript DSL → compiles to → NIL → executed by → a business OS`.** The DSL is one
layer *above* NIL. wosool-cloud is the reference *implementation* of both — it is **not** "the language"
and **not** "the protocol."

---

## 2. The model to copy is MCP, not n8n

The instinct to "open-source wosool-cloud like n8n so it trends" is the wrong precedent. The right one is
**MCP (Model Context Protocol)** — Anthropic's own playbook:

- **MCP open-sourced the *protocol* + SDKs + reference servers; kept *Claude* closed.** It became
  *the* standard for tool-calling. The trend came from the **spec + a thing you could run**, not
  from open-sourcing the flagship product.
- **nilscript DSL : commerce automation :: MCP : tool-calling.** Open the standard, ship a runnable
  reference, keep the production runtime and the vertical intelligence as the business.

Why **not** n8n's full open-core-now:

- n8n could open-core because their moat is **400+ integrations + a visual editor + cloud ops** —
  breadth you do not have yet. Your wedge is **a standard + an Arabic commerce vertical**. Lead
  with the standard.
- The full wosool-cloud runtime is, candidly, "**Temporal + glue + channel adapters**." Open-sourcing
  *that* hands a competitor a hostable clone while giving you little defensibility — the classic
  "someone hosts it cheaper" trap.
- You can always open *more* later. You can never re-close. Start narrow.

Also disentangle two levers people merge:

- **Contribution** comes from an **open repo + clean docs + the conformance suite** — not from
  registration. Anyone can PR a new skill or a Go validator.
- **Registration** is for the **hosted product** (sign-up, gating, billing) — that is your "n8n
  Cloud," and it sits in Tier 3 below.

---

## 3. The three-tier release model — open the outside, sell the core

```
┌─────────────────────────────────────────────────────────────┐
│ TIER 1 — OPEN STANDARDS  (Apache-2.0, no registration)       │ ← the TREND engine
│   nilscript  +  nilscript-dsl-spec  +  conformance/ suite        │   (stars, contributors)
├─────────────────────────────────────────────────────────────┤
│ TIER 2 — OPEN DEMO / REFERENCE IMPL  (open, deliberately thin)│ ← the DEVELOPER hook
│   validator + 1 channel (CLI/web) + example skills,          │   ("runs in 5 minutes")
│   in-memory stores, MOCK business OS. No Arabic IP, no prod.  │
├─────────────────────────────────────────────────────────────┤
│ TIER 3 — THE PRODUCT  (closed, or fair-code later, + hosted) │ ← the MONEY + MOAT
│   full wosool-cloud: WhatsApp Business, Hejazi/Najdi intelligence,    │   (this is your n8n Cloud)
│   durable multi-tenant runtime, real business-OS connectors  │
└─────────────────────────────────────────────────────────────┘
```

| Tier | Contents | License | Registration | Purpose |
|---|---|---|---|---|
| **1 — Specs** | NIL + nilscript DSL grammar, JSON Schema, `conformance/` corpus | **Apache-2.0** | No | Become the standard; network effect |
| **2 — Demo** | Thin wosool-cloud: validator + CLI/web demo + example skills + mock OS | **Apache-2.0** (or fair-code later) | No | Developer "aha"; contributions |
| **3 — Product** | Production channels, Arabic intelligence, durable runtime, connectors | **Closed** (fair-code optional later) | Yes (hosted) | Revenue; the moat |

The trend is driven by **Tiers 1–2** (a crisp spec + a runnable demo). The business lives in
**Tier 3**. Open-sourcing the language is a **moat *amplifier*, not a giveaway**: the more agents
and tools speak nilscript DSL, the more valuable the runtime that executes it best — yours.

---

## 4. What's open vs. what's the moat

| Open source (ecosystem) | Keep closed (the moat) |
|---|---|
| **NIL spec** — any business OS can become conformant | The **durable runtime** (Temporal interpreter, reliability, scale) |
| **nilscript DSL spec + schema + conformance** — any agent/LLM can author; any tool can render | The **agents / channels / Arabic intelligence / memory** |
| A thin reference **validator + demo** (drives adoption) | The **business-OS integrations** (grants, tiers, SSOT) + the **hosted service** |

This is the OpenTelemetry / CloudEvents / MCP pattern: **own the standard, monetize the runtime
and the integrations.**

---

## 5. Recommended repo topology

```
nilscript-dsl-spec/            NEW. The LANGUAGE. Apache-2.0. Language-neutral.
├── SPEC.md                 (the nilscript-dsl/ docs in this repo become this)
├── schema/*.json           the JSON Schema — the formal grammar
├── conformance/            golden programs + expected verdicts  ← makes it a STANDARD
└── VERSIONING.md

nilscript/                   EXISTING. The PROTOCOL. The southbound contract.

wosool-cloud/  THIS repo. Closed. The Python REFERENCE IMPLEMENTATION
                              (validator + interpreter + agents + channels).

wosool-demo/                NEW (Tier 2). Thin, open, runnable. The developer hook.

nilscript-dsl-py / -ts / -go   OPTIONAL later. Per-language SDKs that pass conformance/.
```

The `nilscript-dsl/` directory in *this* repo is the **drafting ground**; when it stabilizes it is
lifted out into `nilscript-dsl-spec`, carrying [conformance/](conformance/README.md) with it.

---

## 6. Why it is *already* "open to any programming language"

nilscript DSL is an **external, declarative DSL whose carrier syntax is JSON** (Fowler — see
[01-LANGUAGE-OVERVIEW.md §6](01-LANGUAGE-OVERVIEW.md)). That choice makes it language-neutral by
construction:

- **Authored/consumed from any language** — already true. A Go service can *emit* a program; a TS
  frontend can *render* one; JSON is the universal interchange format. (Had we let the LLM write
  Python, the language would be chained to Python.)
- **Validated/executed in any language** — needs a per-language **SDK** + the **conformance
  suite** so each SDK can *prove* it implements the spec. That suite already exists in seed form:
  [conformance/](conformance/README.md).

The conformance corpus is the load-bearing piece: it is how JSON Schema, CloudEvents, OpenAPI,
and CNCF Serverless Workflow all became real cross-language standards — a shared set of
inputs + expected outputs any implementation runs to claim compliance. Without it you have a
*format*; with it you have a *standard*.

---

## 7. The demo MVP (Tier 2) — the "at least a demo" developers expect

The smallest artifact that makes a developer *get it* — and it is mostly the validator, which is
Phase 1 work anyway, so it is **near-free** (not throwaway):

1. **CLI or single-page web demo:** type Arabic/English intent → LLM emits a Wosool program →
   **the validator runs live** (schema → references → acyclicity → whitelist → reachability) →
   render the graph → **mock-execute** against a fake business OS (no real NIL endpoint needed).
2. **One-click samples** = the [conformance/valid/](conformance/) programs, *plus* an
   [invalid one](conformance/invalid/08-unknown-skill.json) — the killer moment is watching it
   **reject `commerce.delete_store` with diagnostics**, i.e. *seeing the safety*.
3. **Zero-config run:** `docker compose up` or `npx create-wosool-app`.

Crucially the demo needs **no production channels and no proprietary Arabic models** — it is the
validator + interpreter skeleton + mock skills, which is the open part of the runtime you build
regardless. A full demo spec is a follow-up roadmap doc.

---

## 8. Licensing — recommendation and the one open decision

- **Tier 1 (specs):** **Apache-2.0**, unambiguously. A standard with usage restrictions does not
  get adopted. Non-negotiable if you want the trend.
- **Tier 3 (product):** **Closed** now; consider **fair-code / BSL** only if/when you later open
  a fuller runtime and want to block hosted clones (the n8n lever).
- **Tier 2 (demo) — the genuine judgment call:**
  - **Apache-2.0** → maximum trust, contributors, "real open source" credibility. The thin demo
    is not hostable-as-a-product anyway, so little downside. **← my recommendation.**
  - **Fair-code / BSL** → keeps it open for devs but blocks a hosted clone; reserve for the
    *fuller* runtime, not a thin demo.

**The decision that is genuinely yours:** does nilscript DSL get its **own spec repo** or **fold
into `nilscript`**? Recommendation: **own repo** (`nilscript-dsl-spec`). Protocol and language version
independently — NIL can add a verb without touching the DSL grammar, and vice-versa — and the DSL
is the more brandable, novel IP ("the language for LLM-native commerce automation"). Folding them
couples two release cadences that should move apart.

---

## 9. Sequenced rollout

1. **Stabilize the spec** in `nilscript-dsl/` (done: v0.1 draft + [conformance/](conformance/)).
2. **Build the validator** (Phase 1, [08-ROADMAP.md](08-ROADMAP.md)) — it is also the demo's
   engine and the conformance harness. One build, three payoffs.
3. **Ship the Tier-2 demo** (`wosool-demo`, Apache-2.0) — the GitHub/HN moment.
4. **Extract Tier-1 specs** into `nilscript-dsl-spec` + `nilscript`, Apache-2.0, with conformance.
5. **Keep Tier-3 (wosool-cloud) closed + hosted** — the registration/billing product.
6. **Invite SDKs** (`-ts`, `-go`) once the conformance suite is the gate — community extends reach
   without you writing every implementation.

---

*See [09-REFERENCES.md](09-REFERENCES.md) for the MCP / CloudEvents / OpenTelemetry / fair-code
precedents behind this strategy, and [00-INDEX.md](00-INDEX.md) to navigate the spec.*
