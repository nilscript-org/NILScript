# PLAN — Executing the Offerings Map (reconciled with what's already built)

> **Status:** execution plan. Local doc (not committed). Governs the build backlog; governed in turn
> by the Offerings Map (§6 validation gate) and the constitution (sell governed/reversible/audited,
> never "prevents hallucination").
> **One line:** The asset is real and the ladder is right — but we have **built ahead of the ladder**
> (a near-complete Offering-C surface). This plan keeps the strategy intact by **re-casting the build
> as a validation-and-sales asset for A and B**, not as a premature C launch.

---

## 0. The reconciliation (the only thing that matters in this doc)

Two true statements that are in tension:

1. **The Offerings Map is correct.** One asset, three depths, a ladder: **Service (A) → Runtime (B) →
   Platform (C)**, each gated by validation, revenue before scale. C is lowest-readiness, gated on B,
   gated on three conversations + one paid pilot.
2. **We have already built deep into C.** Kernel + Automation Registry + dispatcher/triggers +
   cross-system composition + control-plane audit + MCP automation tools (shipped, tested) **and** a
   world-class platform UI (Wosool Hub: Console, Canvas, Templates gallery, Systems, Agents,
   Governance — "Gumloop for MENA, governed").

The wrong read of this: *"the platform is basically built, so C is the play — go to market with it."*
That is exactly the failure the Offerings Map names — building the platform before the buyer is
proven. The right read:

> **What we built is not a product launch. It is the most powerful validation-and-sales asset a
> services/runtime business has ever walked into a room with.** Use it to *sell A* and *pitch B* and
> *raise on the vision* — and do not confuse "the surface exists" with "the C buyer is validated."

The discipline holds: **§6 (validation gate) still governs §3 (the offerings).** The build changed our
*demo*, not our *sequence*.

---

## 1. Asset → rung map (what each built thing is FOR, on the ladder)

| Built asset (real, tested) | Primarily serves | How it's used *now* (not later) |
|---|---|---|
| **NIL kernel** (propose→commit, verify, reversibility, refusals) | the asset itself | the thing every offering sells |
| **Adapter contract + Choice Gate** (Odoo, Salla, PocketBase…) | A and B | the integration substrate a *service* delivery rides on |
| **Automation Registry + dispatcher + triggers + composition** | A first, B next | the "extract the repeated 80% into a runtime" engine — already exists, so A's deliveries can be *built on the runtime from day one* |
| **MCP automation tools** (`nil_automation_*`) | B | the developer-facing "your agent authors governed workflows" surface |
| **Control-plane audit + approval gate** | A, B, C | the retention/trust surface — "what ran, what it did, what would break if removed" |
| **Wosool Hub UI** (Console/Canvas/Templates/Governance) | **demo for A; vision for the raise; eventual C** | the screen you show the friend's company and the technical buyer; the fundraising artifact; *not* a self-serve signup yet |

**The key realignment:** the registry/runtime existing means Offering A is *not* throwaway services —
every A delivery is built **on the runtime**, so A's work directly hardens B. That's the ladder working
as designed (A reveals what repeats → the runtime captures it), except we front-loaded the runtime.
Good — as long as we don't skip the validation that tells us *which* repetitions are real.

---

## 2. The sequence (unchanged ladder, mapped to our actual state)

```
NOW  ── Offering A (Service)  + the §6 validation gate, in parallel
        │   • A is the revenue + reference base (buyer already pulls)
        │   • the Hub UI is the demo that closes A and powers the 3 conversations
        ▼
THEN ── Offering B (Runtime)  ── ONLY if the gate returns ≥2/3 "governance" + 1 paid pilot
        │   • SDK + adapters + governed DSL; the MCP tools are the seed
        │   • measure free→paid and next-project RE-ADOPTION, not logos
        ▼
LATER ─ Offering C (Platform) ── ONLY if B gets real adoption
            • the Hub UI graduates from demo → self-serve product
            • built from proven patterns (what A repeated, what B adopted), not guesses
```

We climb; we do not pick. A funds and teaches B; B proves and de-risks C. **The Hub UI rides along the
whole way** — as A's demo, then B's onboarding surface, then C's actual product — but it does not
*define* which rung we're on. The buyer's validation does.

---

## 3. NOW — the concrete near-term plan (next ~30 days)

Two tracks in parallel: **revenue (A)** and **validation (gate §6)**. No new platform features.

### Track 1 — Offering A as the revenue-and-learning base
- **One paid pilot, not a favor** (gate §6.2): the friend's company. Real scope, real (even small)
  price, written commitment to a reference + 2 intros if it works. Build it **on the registry/runtime**
  (governed integration of their 3–5 systems), with the **control-plane dashboard** as the "what ran /
  what it protects" retention surface.
- **Price against payroll, not software** — "a governed automation that can't corrupt your books, for
  a fraction of N salaries."
- **Use the Hub UI as the closing demo** — show the Console (talk → governed plan), the Templates
  gallery (their use-cases pre-shaped), the Governance timeline (every action, reversible). It makes
  the invisible value *visible* to exactly the financial-risk buyer who feels it.

### Track 2 — the validation gate (governs everything in §3 of the Map)
- **Three conversations** (gate §6.1): 2–3 intros to technical buyers. Open question, governance
  *unprompted*: *"when your agent writes to a production system, what stops you letting it run
  unattended?"* ≥2/3 reach governance on their own → Offering B is real. None → B is a special case;
  A stays pure services.
- **Do not build B yet.** The MCP automation tools already exist as the seed; resist hardening them
  into an SDK until the gate returns yes.

### What we explicitly do NOT do now
- No self-serve signup / billing / multi-tenant onboarding for the Hub (that's C, ungated).
- No "connect anything" generality (re-grows n8n; C's death in §7).
- No marketing of the Hub as a launched product. It's a demo and a vision artifact until B validates.

---

## 4. Where the Hub UI build genuinely pays off (so the work isn't wasted)

The platform UI we built is premature *as a launched C product* but **high-leverage right now** in
three concrete ways:

1. **It closes Offering A.** A services buyer signs faster when they can *see* the governed automation
   and its audit surface, not just hear about it. The Hub is that screen.
2. **It is the fundraising/TAQADAM artifact.** "Governed AI automation for MENA, powered by NILScript"
   with a working, beautiful surface + a shipped kernel = the most fundable version of the story
   (Vision doc §11). It de-risks the raise without committing us to a premature self-serve launch.
3. **It is B's onboarding surface in waiting.** When the gate passes, the Console/Templates become the
   developer's first-run experience — already built, already on-brand (Gumloop-for-MENA, governed).

> Rule: **the Hub is a demo and a vision until §6 says otherwise.** Every hour we'd spend turning it
> into self-serve C is an hour stolen from A's revenue and B's validation. Freeze C surface work.

---

## 5. The gates, made explicit (build-unlock conditions)

| To start… | The gate that must pass first | The number that matters |
|---|---|---|
| **Offering A delivery** | already open (buyer pulls) — start now | a *paid* pilot + reference + 2 intros |
| **Offering B (runtime/SDK)** | §6.1: ≥2/3 conversations reach governance unprompted **and** §6.2 paid pilot lands | free→paid + **next-project re-adoption** of 5 devs |
| **Offering C (self-serve platform)** | B shows real adoption (5 devs re-adopt) | self-serve activation + retention |
| **Any C surface engineering** | same as C | — (frozen until then) |

If a gate hasn't passed, the thing it unlocks is a **hypothesis**, and we do not spend build hours on
it. The one exception, per the Map: **A starts now.**

---

## 6. Discipline reminders (what kills each, kept in view)

- **A dies** as free favors / scope creep, or if we never extract the runtime. *(We already have the
  runtime — so the risk is only the pricing discipline.)*
- **B dies** on a rough first hour, thin adapter coverage, or chasing logo count over re-adoption.
- **C dies** going general ("connect anything" → n8n) or letting the agent silently build wrong
  workflows. *(Mitigation already designed: the Console's generate-vs-govern split + readable-confirm
  — the agent's plan is shown and approved, never silently committed.)*
- **All three die** selling to a buyer who can't see the value (the Salla lesson). Governance is
  invisible to a merchant, load-bearing to the technical/financial-risk buyer. **Sell to the second,
  always.** The Hub UI's job is to make governance *visible* to that buyer.

---

## 7. The one-paragraph synthesis

The Offerings Map is right and we follow it: one asset, three depths, climb A→B→C, validate before
build. We have built unusually far up the ladder — a shipped governed runtime **and** a world-class
platform surface — but that changes our *demo*, not our *sequence*. So: **start Offering A now** (paid
pilot on the friend's company, built on the runtime, closed with the Hub demo), **run the §6 validation
gate in parallel** (three conversations, governance unprompted), **freeze all self-serve C work**, and
**unlock B only when the gate says yes, C only when B is adopted.** The build wasn't premature
*spending* — it was a premature *product*; re-cast as a sales-and-validation asset, it's the strongest
position a services-to-runtime company can hold. The asset was never the question. The buyer is. Point
the beautiful surface at the financial-risk buyer, charge from day one, and earn the platform.

---

*End. §5 (gates) governs §3–§4 (what to build). §3 Track 2 (validation) governs whether B/C exist at
all. A starts now; everything else is earned.*
