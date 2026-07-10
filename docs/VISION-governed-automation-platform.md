# VISION — The Governed AI-Automation Hub

> **Status:** product vision + architecture + UI plan. Local doc (not committed).
> **One line:** *A safe hub where a business owner connects their systems and their AI agents, then
> automates by talking or by drawing — and every action the agent takes is governed by the NIL
> kernel: the agent proposes, deterministic code disposes.*
> **What we're changing:** automation stops being something you *build and maintain* and becomes
> something you *describe and forget* — without giving an LLM ungoverned write access to your business.

---

## 1. The thesis

There are two camps in automation today, and both are broken for the AI era:

1. **Deterministic-but-manual** (Zapier, Make, n8n): reliable, but *you* build every workflow by
   hand, wire every field, and maintain it forever. The "automation barrier" — most SMBs never cross
   it because building is hard and brittle.
2. **AI-but-ungoverned** (Lindy, Gumloop, Relevance, browser agents): the LLM *is* the orchestrator,
   so it's easy to start — but the model can hallucinate a write, there's no deterministic
   intent→effect boundary, no honest reversibility, no structural approval gate. Enterprises can't
   trust it on production systems.

**Our wedge sits exactly between them:** the **agent is generative** (it reads your business in plain
language and proposes the action or the workflow), but the **validator is a total, deterministic
function** — the NIL kernel — that lowers the proposal into an executable, content-hashed plan *or
rejects it with a precise reason*. A hallucinated verb has nothing to bind to. A composed workflow
that names an undeclared op is refused before any effect occurs.

> **AI proposes. Code governs and executes.** That sentence is the whole product.

This is not a feature of an automation tool. It's a different *category*: **governed AI automation** —
the safe hub that lets a company point Claude/Hermes at its real systems and say "automate this," and
get a deterministic, reversible, audited result.

---

## 2. The problem we solve

A company runs Odoo (with 10 modules), maybe Salla, maybe a custom system. The owner knows exactly
what they want — *"every morning, take yesterday's new leads, create a follow-up task, and post the
totals to accounting"* — but:

- Building that in n8n means learning n8n, mapping every field, and owning the breakage.
- Handing it to an LLM agent means trusting a probabilistic model to write to their books.
- Cross-system ("sales → marketing → accounting") multiplies both problems: schema mismatch +
  authority leakage.

**The barrier is "describe → safe running automation."** We collapse it: the owner *describes* (talks
or draws), the agent *proposes*, the kernel *governs*, and the result is a **reusable, self-triggering
automation** they can forget about — that re-runs itself reproducibly and shows every action in one
audited pane.

---

## 3. Landscape research — the three camps and the gap

| Camp | Examples | What they nail | What they lack (our opening) |
|---|---|---|---|
| **Classic iPaaS** | Zapier, Make, n8n, Workato | Reliable connectors, deterministic runs | Manual build; no AI authoring; brittle; no agent governance |
| **AI-native builders** | Lindy, Gumloop, Relevance AI, Relay, Bardeen, CrewAI | LLM-as-orchestrator, easy authoring, visual AI nodes | No deterministic write boundary; hallucination risk; no honest reversibility; governance is prompt/context-layer, not structural |
| **MCP system bridges** | mcp-server-odoo, Odoo MCP modules, Salla/ERP MCP servers | Expose a system's data/actions to Claude/ChatGPT, inherit backend ACLs | Just tools — no propose→commit determinism, no refusal taxonomy, no workflow-as-tool, no cross-system composition layer |

**The macro tailwind:** enterprise AI governance is now the headline concern of 2026 — "combine
dynamic AI execution with **deterministic guardrails** and human judgment at decision points,"
**runtime governance** ("policies on paths"), and the **EU AI Act** (high-risk enforcement Aug 2026)
mandating logging, auditability, and human oversight of AI actions. Today's tools bolt governance onto
the *context/prompt layer* (what enters the window). **NIL enforces it at the *effect* layer** — the
one place that actually matters: nothing writes unless it was declared, previewed, and (optionally)
approved. That is a structural guarantee, not a softer "the model decided not to."

**Conclusion:** the AI-native builders are racing on *capability*; the MCP bridges are racing on
*connectivity*; **nobody owns governed determinism as the product.** That's the category we take.

Sources: [Lindy — AI automation platforms 2026](https://www.lindy.ai/blog/ai-automation-platform),
[Gumloop review](https://automationatlas.io/tools/gumloop/),
[Berkeley CMR — Governing the Agentic Enterprise](https://cmr.berkeley.edu/2026/03/governing-the-agentic-enterprise-a-new-operating-model-for-autonomous-ai-at-scale/),
[Atlan — Enterprise AI Agent Guardrails](https://atlan.com/know/ai-agent/enterprise-ai-agent-guardrails-checklist/),
[Runtime Governance for AI Agents (arXiv)](https://arxiv.org/html/2603.16586),
[mcp-server-odoo](https://github.com/ivnvxd/mcp-server-odoo),
[Odoo MCP Framework](https://apps.odoo.com/apps/modules/18.0/mcp_base).

---

## 4. What the platform IS — five pillars

The hub does five things, each backed by something we already built in the kernel:

1. **Connect systems** — adapters turn any backend (Odoo, Salla, PocketBase, custom) into a
   NIL-speaking surface. *(kernel: scaffold + edge template + Choice Gate.)*
2. **Connect agents** — MCP front door binds Claude/Hermes/any MCP client to the governed tools.
   *(kernel: multi-tenant MCP server.)*
3. **Propose** — the agent emits intents/plans as data; the kernel previews them (no side effect).
   *(kernel: propose/commit, refusals, the V1–V6 validator.)*
4. **Execute & automate** — a single governed op runs now, **or** a plan is registered as a
   versioned, self-triggering automation. *(kernel: the Automation Registry + dispatcher + triggers +
   cross-system composition — shipped.)*
5. **Govern** — one audited timeline, approval gates, honest reversibility, content-hash version
   locks. *(kernel: control plane + audit store.)*

The *new product* is the **surface** over these: a native dashboard, a conversational console, and a
visual builder — multi-tenant, beautiful, and opinionated.

---

## 5. Three ways to create an automation

The same governed engine, three front doors — meet the user where they are:

### 5.1 Talk (conversational)
The owner opens the console and says: *"In my Odoo, whenever a deal moves to Won, create an invoice
and notify the finance channel."* The agent (Claude/Hermes) reads the request + the live capability
registry, **proposes** the op or the workflow, the kernel lowers-or-rejects it, the owner sees a plain
preview and approves. → a running automation.

### 5.2 Draw (visual canvas)
For people who think in boxes: a node canvas (n8n/Gumloop-familiar) where **every node is a governed
NIL op**, not a raw API call. Drag a "create lead (Odoo)" node, link it to a "create invoice (Books)"
node, draw the data handoff, set a trigger, hit save. The canvas **validates live** against the real
backend skeletons; an invalid wire is refused in the editor, not at 3am in production.

### 5.3 Direct (API / agent tool)
Power users and other agents hit the registry API or the MCP automation tools directly.

> All three converge on the **same SSOT record**: a content-hashed, versioned, validated automation.
> The mode is just ergonomics; the guarantee is identical.

---

## 6. The core loop — *create once, then forget* (automation-as-a-tool)

This is the idea that changes how business is done:

```
describe ─▶ agent proposes ─▶ kernel validates (deterministic) ─▶ human approves ─▶ REGISTERED
                                                                                       │
                              ┌────────────────────────────────────────────────────────┘
                              ▼
                  it becomes a self-running CAPABILITY:
                    • fires itself (schedule / event) — you forget it
                    • OR is invocable on demand as a NEW TOOL the agent can call
                      (no re-reasoning, no re-building — the workflow IS the tool)
```

The breakthrough: **a validated automation is promoted to a callable tool.** The next time the agent
needs "onboard a customer across Odoo + Salla," it doesn't re-derive the steps — it calls the
*existing, governed, version-locked* automation. The agent's reasoning compounds into a growing library
of safe, reusable, self-triggering capabilities. **The company's processes become living, governed
software — authored by conversation, owned by the code.**

---

## 7. Architecture — kernel intact, new platform layer on top

We do **not** touch the kernel's guarantees. We build a product tier above it.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  PLATFORM (new)                                                                │
│  Console (chat)   │  Canvas (visual node editor)  │  Dashboard / Tools library │
│  Systems hub      │  Agents hub                   │  Governance & audit pane   │
├──────────────────────────────────────────────────────────────────────────────┤
│  PLATFORM SERVICES (new, thin)                                                 │
│  workspace/identity · tenancy · billing · adapter catalog · tool-promotion ·   │
│  canvas↔DSL compiler · presence/realtime · notifications                       │
├──────────────────────────────────────────────────────────────────────────────┤
│  NIL KERNEL (exists — unchanged)                                               │
│  Automation Registry (SSOT, versions, content-hash) · dispatcher (manual/      │
│  event/cron) · cross-system composition · validator V1–V6 · propose/commit ·   │
│  refusals · reversibility · MCP front door · adapters · control-plane audit    │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Reuse map (what already exists → what the platform wraps):**

| Platform surface | Backed by (shipped kernel piece) |
|---|---|
| Conversational authoring | MCP automation tools (`nil_automation_draft/register/run/...` + compose) |
| Visual canvas → automation | Wosool DSL AST + V1–V6 validator + `validate_composed` |
| Automations dashboard | Automation Registry tables + `/api/automations` + run history |
| Self-triggering | dispatcher + triggers (event subscriber on the ledger, cron/interval tick) |
| Cross-system | per-stage composition + author-declared handoff |
| Governance pane | control-plane audit timeline + approval gate + rollback |
| Systems hub | adapter registry + multi-active adapters + live skeleton discovery |

The platform's only genuinely *new* engineering is: the **canvas↔DSL compiler** (drawing → validated
`WosoolProgram`/composed plan), **tool-promotion** (a registered automation exposed as a callable
tool), **tenancy/identity/billing**, and the **design-led UI**.

---

## 8. UI / UX & layout

### 8.1 Information architecture (left rail)

```
◐ HUB
├─ ⌘ Console        ← talk to the agent; build & run by chat
├─ ⬡ Canvas         ← visual node editor (the workflows)
├─ ⚡ Automations    ← list, state, triggers, versions, run history (the library)
├─ ◻ Systems        ← adapters: connect Odoo / Salla / PocketBase / custom
├─ ✶ Agents         ← MCP: connect Claude / Hermes / clients; scopes & grants
├─ ⚖ Governance     ← one audited timeline · approvals · rollbacks
└─ ⚙ Settings        ← workspace, members, billing, tokens
```

### 8.2 Console (the headline surface)

A split view: **chat on the left, a live "what the code decided" panel on the right.** As the agent
proposes, the right panel renders the *deterministic verdict* — the previewed plan, the
reversibility tier, or the structured refusal (which node, which verb, why). The human approves with
one click. This visual split is the product's soul: **you watch the agent generate and the code
govern, side by side.** Nothing commits without crossing that line.

```
┌─────────────────────────────┬──────────────────────────────────────┐
│  ⌘ Console                   │  ▣ Governed preview                   │
│                             │                                      │
│  you: every Won deal in     │  PLAN  lead-to-invoice  ✓ valid       │
│  Odoo → make an invoice     │  ├ stage 1 · Odoo · crm.read_deal     │
│  and ping finance           │  ├ stage 2 · Books · acc.create_inv   │
│                             │  │   handoff: deal.total → amount     │
│  agent: here's the plan →   │  trigger: on deal.stage = "won"       │
│                             │  tier: REVERSIBLE · hash a3f8…         │
│  [ Approve ]  [ Edit in     │  ─ or, if refused ─                   │
│    Canvas ]  [ Discard ]    │  ✗ V4 crm.fly: not a declared verb    │
└─────────────────────────────┴──────────────────────────────────────┘
```

### 8.3 Canvas (visual node editor)

n8n-familiar drag canvas, but governed:
- **Nodes are typed NIL ops** drawn from the closed DSL set: `action`, `query`, `condition`,
  `parallel`, `foreach`, `await_approval`, `wait`, `notify`. An unknown node type is unrepresentable.
- **Each action node carries its system** (which adapter) and its **verb** — picked from a dropdown
  populated *live* from that adapter's real skeleton. You cannot draw a verb the backend doesn't
  expose.
- **Wires are typed data handoffs** (`$.stage_1.step_2.output.id`); the editor validates the
  reference against the upstream node's output shape and **refuses a dangling/forward wire in place.**
- **Governance is visible on the node:** a reversibility badge (REVERSIBLE / COMPENSABLE /
  IRREVERSIBLE), a tier chip (LOW…CRITICAL), and an "approval gate" toggle.
- **Save = compile → validate (V1–V6) → content-hash → register.** A red node = a precise diagnostic,
  not a runtime surprise. Cross-system stages each validate against their own adapter.

### 8.4 Automations / Tools library

Cards (already prototyped in the control plane): name, **state badge** (draft → pending → active ⇄
paused), **kind** (single / composed), **trigger** (manual / `cron 0 9 * * *` / `on <verb>`),
**version + short hash**, expandable **run history** with per-run state + trace. A "**Promote to
tool**" action turns a stable automation into a callable capability listed for the agent.

### 8.5 Systems hub
Each connected backend as a live card: status, namespaces (`crm.*`, `commerce.*`), enable/disable
(multi-active so a workspace can run Odoo + PocketBase together for cross-system work), and a "link"
flow that registers it. Skeleton (verbs/targets) browsable so the user sees exactly what's governable.

### 8.6 Agents hub
Connected MCP clients (Claude, Hermes), their grants/scopes, and the live tool list each one sees —
the generic NIL tools + the dynamic `propose_<verb>` tools + the promoted automation-tools.

### 8.7 Governance pane
The control-plane timeline, productized: every proposed/executed/refused/rolled_back event across every
agent and automation, with the field-level SSOT read-back (did the intent actually land?), one-click
rollback on reversible rows, and the pending-approval queue.

### 8.8 Design direction (anti-template)
Not a generic SaaS dashboard. Direction: **"governed control room"** — a calm, dark-luxury technical
aesthetic with one decisive accent, monospace for the governed/audit surfaces (it should *read* like
infrastructure you trust), editorial scale contrast on the marketing/empty states, and motion only
where it clarifies the propose→approve→commit flow. The split-pane "generate vs govern" is the signature
visual. Light + dark both intentional. The existing control-plane UI already establishes the token
system (oklch palette, the pill/badge/card language) — the platform extends it, doesn't restart it.

---

## 9. Safety & governance model (the moat, made explicit)

Every claim maps to a structural mechanism, not a prompt:

- **No undeclared write** — V4 whitelist: a verb must be in the backend's live skeleton.
- **No silent write** — propose previews, commit executes; the two are separate performatives.
- **No double write** — deterministic content-hash idempotency; a re-fire replays.
- **Honest reversibility** — REVERSIBLE / COMPENSABLE / IRREVERSIBLE declared and tested; rollback
  refuses to fake an undo it can't do.
- **Human at the boundary** — approval gate holds HIGH/CRITICAL *at commit*, outside the model loop.
- **Reproducible** — the content-hash version lock: a scheduled run months later executes the exact
  bytes that were approved.
- **Auditable** — one append-only, HMAC-verified timeline; field-level SSOT read-back.

This is the EU-AI-Act / runtime-governance story told as a *product*, not a policy PDF. For a buyer in
2026, "the write physically could not commit without crossing a deterministic, audited boundary" is
the sentence that closes the deal.

---

## 10. Multi-tenancy, deployment, trust

- **Tenant-owned backends:** the hosted MCP/control plane never holds a tenant's backend credentials;
  the adapter the tenant runs holds the secrets. The hub relays governed intent.
- **Self-hostable:** the whole stack runs single-instance (the LocalExecutor path) or durable
  (Temporal) — enterprises that won't put books in someone's cloud can host the hub.
- **Workspace isolation:** structural per-connection tenancy; one owner's automations/approvals are
  invisible to another.

---

## 11. Why now / why us

- **MCP made agents connectable** (Anthropic's standard) — the connectivity substrate exists.
- **Governance became the buying criterion** (EU AI Act, enterprise agent risk) — the demand exists.
- **We already built the hard part** — the NIL kernel + the Automation Registry + composition +
  triggers + the audited control plane are shipped and tested. Competitors would have to *retrofit*
  determinism onto a probabilistic core; we start from it.
- **Distribution edge** (per [[nilscript-moat-not-in-spec]]): the Wosool dialect / WhatsApp graph /
  Salla / real merchants give a warm wedge into the Gulf SMB market the global tools ignore.

---

## 12. Roadmap

| Phase | Deliverable | Notes |
|---|---|---|
| **v0 — done** | Automation Registry + dispatcher + triggers (cron/event) + cross-system composition + control-plane dashboard + MCP automation tools | The engine. Live. |
| **v1 — the product shell** | Multi-tenant workspace, identity/auth, the native Console (split generate/govern), Systems & Agents hubs, the Automations/Tools library as a first-class app | Wrap the engine in a real product; design-led UI |
| **v2 — the Canvas** | Visual node editor + canvas↔DSL compiler (live validation against skeletons), drag-to-handoff, governance badges on nodes | The "draw it and forget it" surface |
| **v3 — tool promotion + marketplace** | Promote automation → callable tool; an adapter/automation marketplace; templates per vertical (Odoo modules, Salla) | Network effects; the library compounds |
| **v4 — durable scale** | Temporal-backed scheduling (full cron), authority composition for single-op dual-backend, semantic-mapping assistant (suggested handoffs) | The genuinely-hard research items, productized |

---

## 13. Risks & open questions

1. **Canvas↔DSL fidelity** — the visual editor must compile to *exactly* the validated DSL, or the
   "what you draw is what runs" trust breaks. The compiler is the load-bearing new component.
2. **Semantic mapping across systems** — cross-system handoff is author-declared today (honest, not
   inferred). A "suggested mapping" assistant (ranked field correspondences for human confirmation)
   is the right next step — never silent inference.
3. **Authority composition** — a single op needing two backends' authority at once is a real
   distributed-systems problem (2PC), deliberately out of v1–v3.
4. **Agent quality** — the proposer is only as good as the model + the capability registry it reads;
   bad proposals are *refused safely*, but UX must make refusals feel like guidance, not failure.
5. **Positioning discipline** — we are *governed automation*, not "another AI workflow tool." Every
   surface must lead with the generate-vs-govern split, or we blur into the crowded AI-builder camp.

---

## 14. Naming (placeholders — pick a direction)

The hub deserves its own name, distinct from "nilscript" (the kernel/standard underneath):

- **Conductor** / **Cadence** — orchestration + governance feel.
- **Governed** / **Warrant** — leans into the trust/authority story.
- **Hearth** / **Hub** — the "your systems, one safe place" feel.
- **Atlas** — carries the weight of your business systems.

Recommendation: keep **NILScript** as the *open standard/kernel* (credibility, the paper, the moat)
and give the *commercial hub* a warmer product name — "powered by NILScript" — so the governance
substrate stays the defensible core while the hub is the thing businesses buy and love.

---

## 15. The one sentence

> **Point your AI at your business and say what you want. It proposes, the code governs, and your
> processes run themselves — safely, reversibly, and on the record.** That is how business gets done
> next.
