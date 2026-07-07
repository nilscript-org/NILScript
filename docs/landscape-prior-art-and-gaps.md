# The agent-governance landscape vs. NILScript — differentiation, and why it isn't a moat

**Scope:** a deep read of five contemporaneous agent-governance efforts, mapped honestly against
NILScript — and then the harder second pass the first draft of this document dodged: separating what's
*different about NIL today* from what *stays different after Microsoft decides to copy it.* Those are not
the same thing, and the first draft used one word — **moat** — to pretend they were.

| # | Work | Org / author | Date | One-line |
|---|------|--------------|------|----------|
| 1 | **OAP** — Open Agent Passport | APort (Uchibeke) | Mar 2026 | Pre-action authorization: signed passport + policy packs + `before_tool_call` hook + Ed25519 audit |
| 2 | **AARM** — Autonomous Action Runtime Management | Errico (indep.) | Feb 2026 | Intercept → accumulate session context → policy + intent-alignment → allow/deny/modify/**defer**/step-up → signed receipts |
| 3 | **OPP** — OpenPort Protocol | Accentrust (Zhu et al.) | Feb 2026 | AuthZ-dependent discovery, stable `agent.*` codes, **draft-first writes**, preflight hashing, **state-witness** TOCTOU, idempotency, rate limits, conformance profiles |
| 4 | **AGT** — Agent Governance Toolkit | Microsoft | Apr 2026 | 7-component stack: <0.1ms policy engine (YAML/OPA/Cedar), DID/Ed25519 identity, execution rings, **saga orchestration**, kill switch, EU-AI-Act/HIPAA/SOC2 mapping |
| 5 | **OAGS** — Open Agent Governance Specification | Sekuire | 2026 | Local-first: content-addressed identity, declarative `sekuire.yml` policy, runtime allow/deny/warn, signed audit, 3 conformance levels |

---

## 0. The central correction (read this first)

The first draft concluded NIL holds a "triad none of them have together: unexpressibility +
reversibility + earned read-back" and called it NIL's **moat.** That word was doing dishonest work.

- **Differentiation** = what's different about you *today*.
- **Moat** = what stays different *after a better-resourced competitor decides to copy you.*

The triad is real **differentiation**. It is **not a moat**, and the rest of this document is the proof —
walked as a competitor's engineer would walk it, not as the author of NILScript. The practical stakes:
the first draft's roadmap (parametric policy limits, signed receipts, a NIST/EU-AI-Act standards
appendix) is a flawless plan for *racing Microsoft on enterprise governance-standard features* — the
exact game already established as unwinnable. A good map of the wrong territory.

---

## 1. The convergence is real — and it commoditizes NIL's headline

Five independent efforts in ~4 months state NIL's foundational claims in their own words: the model is
not a security boundary (AARM); enforce deterministically before the effect with no model inference in
the path (OAP `authorize(T,P,Π)`, OPP's fixed-order predicate, AGT's "stateless policy engine"); audit
every decision; compose with — not replace — MCP/sandboxing/alignment.

This is **validation of the category** and simultaneously **commoditization of NIL's headline.** "A
deterministic pre-action gate that yields ~0% unauthorized writes" is now claimed by ≥5 efforts. It can
no longer be the differentiator. (The 0% itself is table stakes — §5.)

---

## 2. The four guarantees, with the lineage the first draft omitted

NIL's constitution names four structural guarantees. The first draft scored who-else-has-each. The
honest version adds the column that changes the verdict: **how old is the idea, and how fast is it
copied.**

| NIL guarantee | Who else | Prior art / age | Copy cost once they read NIL's paper |
|---|---|---|---|
| **G1 — no side effect on propose** (intent ≠ action; system-computed preview) | OpenPort (draft-first + preflight) built it independently | Two-phase commit / staged-write (decades); draft-then-confirm is standard | Already exists in a sibling spec. Not NIL's. |
| **G2 — unexpressible** (β⁻¹(a)=∅; no reference → can't name it) | NIL alone *in this cohort* | **Object-capability model — Dennis & Van Horn, 1966**; KeyKOS, E, Capsicum. "You can't invoke what you hold no reference to" is the founding idea of ocaps. | The mechanism is 60 years old. A cs.CR reviewer writes "ocaps applied to tool schemas" in the margin. Bounded to *undeclared verbs* — the 224 incident proves it does nothing for wrong-but-valid params. |
| **G3 — bounded reversibility** (declared reversible/compensable/irreversible; ROLLBACK runs compensation) | **Microsoft AGT names "saga orchestration"** | **Saga pattern — Garcia-Molina & Salem, 1987.** A saga *is* a sequence of transactions each paired with a compensating transaction. Compensation is the definition, not an extra. | The best-resourced competitor already named it. NIL's residual contribution is *declaring the tier upfront and refusing honestly* — a packaging convention, a weekend to copy. |
| **G4 — earned read-back** (re-read SSOT, diff each field; verified is earned) | NIL alone *in this cohort* | Read-after-write verification (storage & DB consistency checks, long-standing) | The genuinely useful one — catches the silent-field-drop hit in Odoo. Also "read it back and diff": any of the five ships it in **a sprint** the day it matters. |

**Verdict on the triad, leg by leg:** one 60-year-old idea narrowly scoped (and not NIL's), one
40-year-old idea the strongest competitor already names, and one good-but-trivially-copyable check.

### The "holds all three together" defense, refuted
The first draft's fallback was "no competitor holds all three *together*." True, and beside the point.
**Holding three cheap, copyable things together is a checklist, not a moat.** Any of the five matches
the checklist in a sprint once they read the paper, and several have more engineers than NIL has hours.
"We combined the parts first, in the open" is the Stripe argument — and Stripe won on **distribution and
execution**, not on having assembled the parts. NIL has no distribution or execution advantage over
Microsoft or Google. The assembly does not save it.

### The one correction to bank
The first draft claimed "NIL is alone on reversibility" and dismissed Microsoft's saga as "forward-stop,
not compensation." **That was wrong** — it conflated the kill switch (forward-stop) with the saga
(compensation by definition). The blog doesn't *detail* AGT's saga, so NIL's *implementation* may still
be more complete today — but the *claim of aloneness* is retracted, and any positioning that leans on
"only NIL can reverse" is false and must not ship.

---

## 3. What the others "filled" — and why chasing it is the trap, not the fix

The first draft listed these as gaps to close. Re-read with §0 in mind: **every item is enterprise
governance-standard work, i.e., racing Microsoft on its turf.**

| Gap (others have it, NIL doesn't) | Who | What it really is |
|---|---|---|
| Parametric policy limits (`max_per_tx`, allowlists, rate caps) | OAP, OPP, Sekuire, AGT | OAP's whole CTF win. Real — *for a banking-agent product.* For Wosool it's a feature, not a frontier. |
| Cryptographic identity + signed/hash-chained receipts | OAP, AARM, AGT, Sekuire | Compliance theater NIL can copy; Microsoft ships it as a checkbox. |
| Context accumulation / intent-drift / compositional risk | AARM | A genuine NIL blind spot (per-`propose` isolation can't see read-PII→email-out). Honest to *concede*, not to chase solo. |
| TOCTOU / state-witness revalidation | OpenPort | A weekend of hardening for the approve→commit window. Worth doing *if* NIL ships; not a strategy. |
| Standards mapping (NIST, SP 800-53, OWASP, EU AI Act, SOC2, HIPAA) | OAP, AARM, AGT | **The purest trap.** See §6. |
| Admission control / rate limiting / DEFER | OpenPort, AARM, Sekuire | Operational polish. |

Each is a true statement about NIL's spec. **None of them moves ten MENA merchants closer to trusting
Wosool.** That is the tell.

---

## 4. NIL's closest sibling is OpenPort — and that's the point
OpenPort independently reproduced propose/commit (draft-first), computed-preview-binding (preflight
hash), authZ-dependent discovery (= NIL `describe`), and idempotency. A five-person team in Feb 2026
rebuilt most of NIL's lifecycle from first principles, in the open, without copying NIL. If a stranger
reconstructs your "moat" by accident, it was differentiation, not a moat.

---

## 5. The honest 0% reckoning (keep this — it's the one durable asset here)

OAP Vault CTF: **0%** across 879 highest-tier attempts. PCAS: zero violations. ceLLMate: 12/12 blocked.
NIL: **0.00%** across 2,108 evals. ~0% from deterministic pre-action enforcement is a **replicated,
expected** result — the *price of entry*, not the prize. NIL's constitution already says this
("by construction within the threat model … not a surprising empirical rate"). **Keep that honesty
exactly.** Marketing must never imply the *number* differentiates.

---

## 6. The category error, named: the roadmap is the abandoned strategy

The first draft's roadmap — parametric limits, signed receipts, state-witness, **a standards-alignment
appendix mapping NIL to NIST SP 800-53 and the EU AI Act** — is, item by item, *compete-with-Microsoft-
on-enterprise-governance-standards.* Item 4 is the purest expression of the trap: writing NIST control
mappings, solo, to contest an enterprise-standard crown against a company that ships SOC2/HIPAA/EU-AI-Act
mapping as a checkbox and cites 9,500 tests. That is not a "cheap credibility win." It is busywork that
*feels* competitive with Microsoft while producing zero retained merchants.

**The only thing in this whole analysis that's safe to use is the positioning honesty, and it's already
written:** lead with reversibility + earned read-back as *why Wosool's writes are trustworthy to a Salla
merchant*; keep 0% honest as table-stakes; concede unexpressibility's bound (undeclared verbs only)
openly. That costs nothing — it's *description of governance NIL already shipped.* Use the triad as
**marketing copy for Wosool's safety.** Do not use it to believe NIL has a defensible standard.

---

## 7. Where the moat actually is (the section the first draft never wrote)

A moat is the thing none of the five — and not Microsoft, and not Google — copies in a sprint. By
definition it is **not in the spec**, because the spec is public and the parts are decades old. It is in
the commercial layer the constitution already names as the real value (open-core §11) and that this
"NIL-vs-the-field" framing made invisible:

- **Arabic-dialect intent resolution** — Gulf/Levantine/Egyptian commerce phrasing → governed action. A
  US-based banking-agent CTF and a Microsoft toolkit do not have this and will not build it for MENA.
- **The cross-merchant WhatsApp customer-identity graph** — who the customer is across Wosool merchants,
  reconciled. This compounds with every merchant and conversation; it is a data asset, not a feature.
- **The Salla integration** — the actual, working governed adapter into the platform MENA merchants run
  on. Distribution, not spec.
- **Retained merchants who trust the automation** — ten merchants who keep Wosool because the writes are
  safe *and the dialect/identity/Salla pieces work.* That trust is the only thing in this entire
  document a competitor cannot replicate by reading a paper.

Reversibility and earned-read-back matter here — not as a standard to defend, but as the **reason a
merchant trusts Wosool to act on their store.** That is their correct job. The triad describes the
safety; the moat is the distribution, the data, and the trust the safety *earns*.

---

## 8. Answer to the two questions that prompted this: neither

> "Fold the roadmap into the Positioning Constitution, or open the standards-alignment appendix?"

**Neither.** Both are standard-race work; the standards appendix is the worst offender — maximum
effort-signaling toward an enterprise crown NIL isn't contesting, zero effect on merchant retention.

The single NIL action worth taking is **keeping the honest positioning paragraph** (triad =
differentiation; 0% = entry price; unexpressibility = bounded to undeclared verbs) as the *description of
Wosool's safety* — and that's already done, in this file. Then **close the NIL-strategy tab** and spend
the hours on Arabic intent, the WhatsApp identity graph, Salla, and the next retained merchant.

---

## 9. One-paragraph synthesis

The field ratified NIL's bet five times in four months — validation, but also commoditization of "a
deterministic gate that yields 0%." NIL's triad is genuine differentiation and zero moat: unexpressibility
is the 60-year-old object-capability model narrowly scoped (the 224 incident is its fence); bounded
reversibility is the 40-year-old Saga pattern that Microsoft already names; earned read-back is a
useful but sprint-copyable read-after-write check. Holding three copyable things together is a checklist,
and competitors with more engineers than NIL has hours match a checklist in a sprint. The roadmap that
chases the others' enterprise features — especially a NIST/EU-AI-Act standards appendix — is excellent
execution of the strategy already abandoned. Use the triad as honest *marketing copy* for why Wosool's
writes are safe; keep the 0% honest; and put the engineering hours where the actual defensible asset
lives — Arabic-dialect intent, the cross-merchant WhatsApp identity graph, the Salla integration, and
ten merchants who trust the automation. The moat was never going to be in the spec.
