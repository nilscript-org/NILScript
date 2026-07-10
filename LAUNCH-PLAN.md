# NIL — Launch Plan (deep)

> **Status: internal launch ops doc. Do NOT commit to the public repo** (add to `.gitignore` or keep local). This is the playbook; the README is the artifact.
> Every number here is traced to a file in this repo, or explicitly tagged `⚠️ VERIFY` / `❌ CUT`. Nothing is invented.

---

## 0. The one rule this plan enforces

The drafted Show HN kit is strong on structure but contains **five claims the repo does not back**. On HN, one unbacked claim in the thread sinks the whole launch. This plan keeps every defensible claim, fills the real numbers, and quarantines the rest.

**The honest thesis (survives scrutiny):**
> Agents can't be made safe, but their *actions* can, and safety lives server-side or it doesn't exist. An undeclared action is **unexpressible** (empty preimage, `β⁻¹(a) = ∅`), not merely filtered. NIL lets an LLM only *propose*; a deterministic kernel validates each proposal against what the backend actually declared, and nothing commits without passing the gate (or a human). Across **2,108 base-setting** InjecAgent evaluations on two models, unauthorized writes admitted at the gate through NIL = **0.00%**, with **100%** authorized-call pass-through (a false-refusal rate of 0). The NIL `0` holds **by construction** (Proposition 2), not as an estimate from two models.

---

## 1. Fact ledger — what you may claim, and the receipts

### ✅ SUBSTANTIATED (claim freely, receipts in-repo)

| Claim | Real number / fact | Source |
|---|---|---|
| Published & installable | **0.3.0 on PyPI**, `pip install "nilscript[cli]"` | `pyproject.toml:7`, README |
| Headline safety | **0.00%** unauthorized writes admitted at the gate through NIL; **2,108 base-setting evals** (2 models × 1,054, base only); enhanced rows withheld (degenerate, raw ASR ≈ 0) | `bench/safety/matrix.json`, README "the numbers" |
| Raw (ungated) hijack rate | **up to 4.46%** (cerebras/zai-glm-4.7, base) — i.e. ~1 in 22 | `bench/safety/matrix.json` |
| Authorized-call pass-through | **100%** in both base rows (a false-refusal rate of 0; NOT measured task completion) | `bench/safety/matrix.json` |
| Edge axis (SRR / EL) | **SRR = 100%, EL = 0** across four corpora via a live odoo-CRM edge; earned by closing a `resource.*` target hole that previously leaked 8/8 | odoo-CRM adapter, README "the numbers" |
| Models tested | `cerebras/gpt-oss-120b`, `cerebras/zai-glm-4.7` | `matrix.json` |
| Benchmark suite | **InjecAgent** (ACL Findings 2024, arXiv 2403.02691), 1,054 cases | `docs/benchmarking-plan.md` |
| Architecture | agent only emits intent → kernel validates vs. **skeleton** → refused-not-faked | README:60-65, `/nil/v0.1/describe` |
| Two-phase + more | PROPOSE→COMMIT, QUERY, ROLLBACK, STATUS, DESCRIBE all **implemented** (6 endpoints) | `src/nilscript/sdk/`, schemas |
| Audit log | EVENT schema, 16 event types, append-only trace w/ compensation token | `src/nilscript/nil/schemas/0.1/event.schema.json` |
| Human approval | risk-tiered `DECIDE` on a separate owner plane (HIGH/CRITICAL → human) | `seqrd-pc-v0.3-design.md §2.2`, `examples/02-high-out-of-band.md` |
| Composes with MCP | MCP client = a NIL "speaker"; no NIL-specific code needed | `IMPLEMENTATIONS.md:10` |
| Conformance | **180 kernel tests** green; **PocketBase adapter 17/17** | README:177 |
| License | dual: **CC BY 4.0** (spec) **+ Apache-2.0** (schemas/SDK) | `LICENSE`, `pyproject.toml:11` |
| Fail-safe tests exist | `unknown_verb_is_refused`, `propose_has_no_side_effect`, irreversible-rollback-refused, silent-write detection | `bench/conformance/test_invariants.py`, `tests/test_rollback.py` |
| Live proof | a real customer + invoice into **live ERPNext** from the standard alone; Playground drives **live PocketBase** end-to-end | README:181 |

### ⚠️ VERIFY-BEFORE-YOU-POST (true maybe, but NOT in this repo — you own the proof)

| Claim in the kit | Problem | What to do |
|---|---|---|
| **Latency**: "Cerebras sub-500ms TTFT + O(1) kernel, p99 added latency = X" | **No latency benchmark exists.** `bench/perf/` is absent; plan marks perf "⏳ later". | **Do not state a number.** Either measure it yourself before posting, or answer honestly in-thread (see §4). The O(1) gate-check claim is fair to *describe* qualitatively; a specific ms figure is not. |
| **"Running in production on Salla WhatsApp via Wosool"** | Repo lists Salla as a **planned** adapter and Wosool Cloud as a **planned** commercial runtime. The repo's only live proof is **ERPNext + PocketBase**. | If your Wosool deployment is genuinely live, this is *your* founder claim to make and defend — but phrase it as your product's deployment, not as a property of the OSS kernel. If you can't show it, **lead with ERPNext** (which is in-repo and defensible). |
| **Founder story** ("11 months, WhatsApp agent, e-commerce") | Personal background — not repo-verifiable, and that's fine. | Keep it **only if literally true**. It's your strongest "why" — but HN will probe it, so be ready to talk specifics. |

### ❌ CUT (will actively cost you credibility)

| Claim | Why cut |
|---|---|
| **`npm i nilscript`** | The npm package is a **stub that ships only README.md** (`package.json` `"files": ["README.md"]`). Anyone who runs `npm i` and finds no code on a Show HN = instant "this is vapor." **Remove npm from the install line entirely.** Use only `pip install nilscript`. |
| **OWASP Agentic Top 10 framing as if done** | No OWASP mapping exists in repo. The kit's fallback ("say it's in progress") is correct — but don't present a mapped table you don't have. |
| Any "zero / 100% / never / unhackable / deterministic AI" as a *safety-of-the-model* claim | The model still hallucinates intent. Your guarantee is on **actions**, not understanding. The "0" is real *for unauthorized writes admitted at the gate*; always pin it to that scope + the 100% authorized-call pass-through (a false-refusal rate of 0, NOT task completion). Never let "0" float free. The harness scores gate decisions over tool names, not executed writes; the NIL `0` holds by construction (Proposition 2). |

---

## 2. Title (function-first, no hype)

**Primary:**
> **Show HN: NIL – LLM agents emit intent, never touch your API**

**Ranked alternates:**
1. `Show HN: A server-side kernel that governs what agent actions actually execute` (safest, most defensible)
2. `Show HN: An intent kernel so LLM agents can't execute hallucinated actions` (strongest problem framing; invites "prove it" — you can, with `unknown_verb_is_refused`)
3. `Show HN: Propose→commit for AI agent actions (open-source kernel)` (protocol crowd)

**Avoid:** "Network Intent Layer" as the lead noun (reads as networking gear), and every word in the CUT list.

---

## 3. The post (real numbers filled; only true placeholders remain)

> I spent the last ~11 months building an AI agent that runs store operations — orders, customers, abandoned carts — over WhatsApp for e-commerce merchants. The hard part was never the reasoning. It was that I couldn't hit the reliability bar an agent needs when it touches real money and real customers.
>
> ReAct loops, LLM-as-judge, retries with verification — the standard stack still leaves a nonzero chance the model invents an action or calls a real API with a hallucinated parameter. For a store owner, "nonzero chance of a wrong action on a live order" isn't shippable.
>
> So I stopped trying to make the *model* safe and changed what the model is allowed to **emit**.
>
> NIL treats the LLM as an understanding machine only. It never sees or calls your real API — it emits **intent**. A deterministic kernel resolves that intent, validates it against the backend's declared **skeleton** (the exact verbs and fields the backend actually exposes, discovered via a `/describe` handshake), and only then executes. If the model hallucinates an action or a parameter, it's **refused at the gate, not faked** — it never reaches your system. High/critical-risk operations route to a human approver on a separate owner plane before commit.
>
> The operation model is **propose → commit** (two-phase), plus query, rollback (with a previewed compensation, never a silent write), and an append-only audit log — every action the agent ever attempted is inspectable.
>
> **How this differs from MCP / tool-call governance:** MCP standardizes how agents *call* tools; governance layers filter those calls. In both, the agent still emits the call. In NIL the agent has no vocabulary for a raw call — it can only express intent, and the kernel owns translation → validation → execution. NIL composes *with* MCP (an MCP client is just a NIL "speaker"); it's not a replacement.
>
> **Try it:**
> ```
> pip install "nilscript[demo]"
> nilscript demo            # opens the Playground at http://127.0.0.1:8770
> ```
> Chat to a live backend and watch a write go **propose → approve → commit → rollback** in a real trace. To see a hallucination die at the gate, ask the agent for an operation the backend never declared — it comes back `UNKNOWN_VERB` refusal, nothing written. (Adapter authors: `pip install "nilscript[cli]" && nilscript scaffold-shim --name my-adapter` — you fill 3 files: `system.py`, `translate.py`, `compensation.py`.)
>
> **Benchmarks (reproducible):** I ran the InjecAgent prompt-injection suite (ACL Findings 2024) twice per case (agent calling tools directly (raw) vs. the same agent routed through NIL (gated)). Same model, same attacks, only the gate differs. Across **2,108 base-setting evaluations** (2 models × 1,054 cases): raw agents were hijacked into an unauthorized write on **up to 4.46%** of cases; through NIL, that write is **admitted at the gate 0.00%** of the time, while **no authorized call was refused** (a false-refusal rate of 0). What the harness scores is **gate decisions over tool names, not executed backend writes**; the NIL `0` holds **by construction** (Proposition 2), and the authorized pass-through is a false-refusal rate, not measured task completion (end-to-end task-success is a separate, planned τ-bench axis). The enhanced setting is withheld (degenerate; raw ASR ≈ 0). Honest caveat: my harness uses a **single-step decision, not InjecAgent's two-step ReAct**, so my raw rates (2.75–4.46%) sit *below* the paper's 24% GPT-4 baseline and are harness-specific. Separately, through a live odoo-CRM adapter's production edge I measured **Structural-Rejection Rate = 100%, Effect-Leakage = 0** across four corpora, earned by closing a `resource.*` target hole that previously leaked a real payment/employee write 8/8. Method + reproduce: `bench/` and `docs/benchmarking-plan.md`.
>
> **Honest limitations:**
> - Intent extraction can still be wrong. NIL doesn't make the model correct — it makes a wrong intent **fail safe** (refused by the contract, or sent to a human) instead of executing. Fail-safe, not fail-silent.
> - You define a skeleton/contract per integration — real upfront modeling, conceptually like an OpenAPI spec.
> - It adds a validation hop. I haven't published p99 latency yet; the gate check is O(1) against the contract and the dominant cost is the model call — proper perf numbers are on the roadmap. [⚠️ if you measured one, state it here; otherwise leave this honest]
> - **Young open standard, pre-1.0.** One completed live proof (a customer + invoice into live ERPNext) and a reference Playground driving live PocketBase. Not battle-tested at merchant scale yet — I'm launching the kernel to get it stressed by people who aren't me. [⚠️ add the Salla/Wosool production line ONLY if you can defend it]
>
> License: CC BY 4.0 (spec) + Apache-2.0 (schemas/SDK), self-hostable, no managed-service dependency. Happy to go deep on the skeleton design, the propose→commit model, or where it breaks.

---

## 4. Thread-defense kit (pre-loaded, repo-accurate)

**"This is just MCP + a policy layer."**
> MCP and policy gateways filter tool calls the agent *emits* — the agent can still author an arbitrary call; the filter says yes/no. In NIL the agent never emits a call; it emits intent, and the kernel is the only thing that can produce an API call. Different trust boundary: theirs is "block the bad call," mine is "the model can't author a call at all." And NIL runs alongside MCP — an MCP client is just a speaker.

**"The LLM still hallucinates intent, so this isn't 100% safe."**
> Correct, and I don't claim the model is correct. I claim a wrong intent can't *execute* — it fails the skeleton/contract or hits human approval first. The guarantee is on actions, not understanding.

**"Show it failing safely."**
> The repo has `unknown_verb_is_refused` and `propose_has_no_side_effect` as conformance invariants (`bench/conformance/test_invariants.py`) — a hallucinated verb gets an `UNKNOWN_VERB` refusal; PROPOSE never touches the backend. Rollback of an irreversible effect is refused honestly, never a silent write (`tests/test_rollback.py`). [link these files]

**"Why not just JSON-schema-validate the tool-call args?"**
> Schema validation catches malformed params. It doesn't catch a well-formed but unauthorized *action*, and gives you no propose→commit, no risk-tiered human approval, no rollback, no audit. And the agent can still emit any call it wants — here it can't.

**"What's the latency cost?"** ⚠️ *do not invent a number*
> Honest answer: I haven't published p99 yet — perf benchmarking is explicitly on the roadmap, not done. Structurally the gate check is O(1) against the contract and the model call dominates wall-clock. I'd rather ship a real wrk2/k6 number than a guess. If you want to stress it, the harness is in `bench/`.

**"Who writes the contracts? You just moved the work."**
> Yes — upfront modeling per integration, like an OpenAPI spec. The payoff: the model physically can't exceed the contract. One-time modeling for runtime safety you'd otherwise never get. And `nilscript scan` + the `/describe` handshake discover much of the skeleton for you.

**"Production proof?"** ⚠️ *lead with what's in-repo*
> One completed live proof in the open standard: a real customer + invoice into a live ERPNext from the standard alone, plus the reference Playground driving live PocketBase end-to-end. Being honest: early, pre-1.0, not merchant-scale yet. [Add Wosool/Salla WhatsApp ONLY if you can back it on the spot.]

**"This is intent-based networking rebranded."**
> The intent→translation concept comes from IBN, fair. NIL applies it to LLM agent actions against business APIs, with two-phase propose→commit, risk-tiered human gating, rollback, and a first-class audit log — none of which IBN gives you for this domain.

**"npm?"**
> Python-first today (`pip install nilscript`). The npm name is a reserved pointer; the spec is language-neutral JSON, so other-language implementations read the schemas directly. [Don't oversell npm.]

**"License / lock-in?"**
> CC BY 4.0 for the spec text, Apache-2.0 for schemas + SDK. Installable, self-hostable, runs in your own infra. No managed service required.

---

## 5. README pre-flight (map to actual repo state)

- [ ] **Logo + header render** — `<nil>` logomark is in (commit `1135cb9`); confirm it displays on GitHub light + dark.
- [ ] **Hook at top**: demo GIF/video → one-command install → benchmark chart (`bench/assets/injecagent_safety.svg`) → propose→commit diagram → runnable quickstart. (README currently leads with benchmarks — good.)
- [ ] **Quickstart runs as-is on a fresh venv.** Test `pip install "nilscript[demo]" && nilscript demo` on a clean machine. This is the most-clicked line in the post.
- [ ] **Fail-safe is reachable**: confirm the `UNKNOWN_VERB` refusal is easy to trigger from the Playground (or document the exact curl). Link `bench/conformance/test_invariants.py`.
- [ ] **Benchmark caveat is visible** (single-step vs ReAct) — it already is; keep it.
- [ ] **Remove/curtail npm** wherever it implies a working JS package.
- [ ] **Pin the InjecAgent dataset commit** before claiming reproducibility (`bench/README.md` flags this as not yet done).

---

## 6. Timing & sequencing

- **Post Tue–Thu, ~08:00 ET.** Block the next **4–6 hours** to answer — responsiveness is what moves a Show HN.
- **Don't cross-post to X/LinkedIn until the HN thread has legs** (~1–2 hrs, climbing). Then drive your own audience to compound.
- **Re-verify the Microsoft AGT status** the morning of, *only if* you use the roadmap-contrast (it's not in the repo; it's an external talking point — as of April 2026 their intent-declaration was roadmapped, not shipped). If you can't verify, drop the contrast.

---

## 7. Multi-channel rollout (after HN catches)

| Wave | Channel | Hook |
|---|---|---|
| T0 | **Show HN** (repo URL) | the title in §2 |
| T0 | **r/Python, r/programming, r/MachineLearning** | "I stopped making the model safe and changed what it's allowed to emit: 0.00% unauthorized writes admitted at the gate across 2,108 base-setting evals" |
| T+1–2h | **X thread** | demo video native-upload → problem → skeleton/gate → `0.00% / 2,108 base evals` chart → repo. Pin it. |
| T+1d | **Lobste.rs** (if invited), **Console.dev / TLDR / Changelog** submit | the InjecAgent A/B framing |
| T+1d | **Awesome-Python / Awesome-LLM PRs**, **PyPI trove** | sustained discovery |

X launch line: **"Agents can't be made safe. Their actions can. An undeclared action is unexpressible, not filtered: 0.00% unauthorized writes admitted at the gate across 2,108 base-setting prompt-injection evals, through NIL."**

---

## 8. Risk register (the landmines, ranked)

1. **npm stub** → remove from install line. *(certain credibility hit)*
2. **Latency number with no benchmark** → never state a figure; answer honestly. *(certain "[citation needed]")*
3. **Salla/Wosool production claim** → demote to your-product framing or cut; lead with ERPNext. *(probable probe)*
4. **OWASP mapping** → "in progress," no fabricated table. *(probable)*
5. **"0 / 100%" floating free** → always scope to *unauthorized writes admitted at the gate* + *authorized-call pass-through* (false-refusal rate, not task completion), with the single-step caveat and "by construction" framing. *(probable)*
6. **Unpinned dataset** → pin commit so "reproducible" is literally true. *(possible)*

---

## 9. Pre-submit checklist (final gate)

- [ ] Title chosen from §2 (no hype words).
- [ ] Post text has **no fabricated latency**, **no working-npm claim**, production line is defensible-or-cut.
- [ ] `pip install "nilscript[demo]" && nilscript demo` verified on a clean venv.
- [ ] Fail-safe demo (UNKNOWN_VERB) reproducible + linked.
- [ ] Benchmark chart + caveat in README; dataset commit pinned.
- [ ] 4–6 hr response window cleared.
- [ ] X thread + Reddit posts drafted but **unsent** until HN has legs.
