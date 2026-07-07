# PLAN — `wosool-landing`: the segment-aware, animation-rich marketing site

> **Status:** deep implementation plan (not yet built). Local doc.
> **New repo:** `nilscript-org/wosool-landing`
> **One line:** *The commercial landing site for Wosool — the governed AI-automation hub built on NILScript — engineered so that every visitor segment (owner, finance, ops, developer, AI-lab, investor) reaches its own "AHA" through rich, interactive, Framer-Motion-driven storytelling, while inheriting the governance credibility of the NILScript standard.*

---

## 0. Why this repo exists (and why it is NOT either existing site)

We already have two web surfaces. This plan deliberately builds a **third, distinct** one and states exactly why neither existing site can be extended into it.

| Surface | What it is today | Audience | Why it is not enough |
|---|---|---|---|
| `nilscript-landing` (Next 14) | The **open-standard** site. "Unexpressible, not filtered." English-only, dark-first, pure-CSS/SVG animation, builder/security tone (`β⁻¹ = ∅`, ReAct, InjecAgent evals). | Technical builders, AI labs, security architects. | It sells the **protocol**, not the **product**. No Arabic/RTL, no business-owner framing, no product-surface demos, no Framer Motion. Constitution §3/§11: the standard's public surfaces stay English-only and never sell Wosool. |
| `wosool-hub` (Next 16 / React 19) | The **actual product app** — the governed-automation dashboard (`/ask`, `/canvas`, `/cycles`, `/graph`, `/governance`…). Dense, operational, bilingual, OLED. | Logged-in operators. | It is the app, not a pitch. It assumes you already bought in. No conversion narrative, no segment routing, no "why". |
| **`wosool-landing` (this plan)** | The **commercial pitch** for Wosool: "Point your AI at your business and say what you want." Bilingual (ar/en, RTL-first-class), warm-but-technical, heavy Framer Motion + interactive product demos, segment-routed AHA. | Buyers across 6 segments + press. | — |

**The load-bearing decision (Constitution §11 + VISION §14):** NILScript is the *open standard/kernel* (credibility, the paper, the moat). **Wosool is the commercial reference implementation businesses buy.** This site sells Wosool, credits NILScript, and links out to `nilscript.org` for the standard. It never claims to *be* the standard. Footer line, verbatim: *"Wosool is built on the open NILScript standard. Powered by NIL — the governed action layer. [nilscript.org →]"*

---

## 1. The core strategy — "one product, six AHAs"

The brief is *"make the user, whatever its segment, say AHA."* A single generic hero cannot do that — an owner and a security architect have opposite AHAs. So the architecture is **segment-adaptive**: one spine (the governance thesis), six branches (segment payoffs), and the interactive demos are the connective tissue that lands the same truth at three depths (VISION §12 register: developer / buyer / investor).

### 1.1 The single thesis every segment must feel (never dropped)

From VISION §1 and the Constitution §1:

> **AI proposes. Code governs and executes.**
> The agent is generative — it reads your business in plain language and proposes the action. The validator is a *deterministic function* — the NIL kernel — that lowers the proposal to an executable, content-hashed plan **or refuses it with a precise reason**. A hallucinated verb has nothing to bind to. An undeclared action is *unexpressible, not filtered*.

Every section, no matter the segment, is a different lens on that one sentence.

### 1.2 The six segments and their distinct AHA

| # | Segment | The moment they say AHA | Primary interactive proof | Copy register |
|---|---|---|---|---|
| 1 | **Business owner / operator** | "I can *talk* to my business and it just… runs itself — safely." | Live **Talk-to-automation** console demo (type a sentence → watch a governed plan assemble). | Plain, outcome-first, bilingual. |
| 2 | **Finance / accounting** | "Every write is previewed, approved, reversible, and on the record — I can't get burned." | **Governance timeline** + **rollback** demo (a bad write, then an *honest* compensation). | Trust, audit, compliance (EU AI Act framing). |
| 3 | **Operations / procurement** | "One canvas wires Odoo → Books → WhatsApp, and it refuses a broken wire *in the editor*, not at 3am." | **Cross-system canvas** demo (React-Flow-style, validates a dangling wire in place). | Concrete, cross-system, reliability. |
| 4 | **Developer / integrator** | "Build one adapter, and every agent can operate it. Here's `pip install`, here's a real propose→commit trace." | **CLI + propose→commit trace** (ported from nilscript-landing, warmed up). | Hands-on, spec-first, no waitlist. |
| 5 | **AI lab / agent builder** | "The agent is *structurally* sandboxed to propose-only — 0.00% unauthorized writes by construction." | The **O(n)→O(1) risk-collapse dials** (ported Aha Act 4) + the InjecAgent bench. | Rigorous, adversarial ("try to break it"). |
| 6 | **Investor / press / decision-maker** | "This is a *category* — governed automation — with a live MENA commerce wedge and an open-standard moat." | The **category map** (three-camps animation) + traction band. | Strategic, category-defining. |

### 1.3 How a visitor gets routed to their AHA

Three concurrent mechanisms, no forced choice:

1. **A single scrolling spine everyone sees** — the thesis, the live demo, the proof. Enough that *anyone* gets it.
2. **A "Find your path" segment selector** (evolves the markdown table in `nilscript-landing/index.md` §"Find your path") — an interactive, animated 6-card chooser near the top. Picking a card doesn't navigate away; it **re-themes and re-orders the page** (Framer `layout` animations reflow sections, swap the hero sub-headline, and promote that segment's demo to the top). URL syncs to `?for=finance` (URL-as-state, per web/patterns).
3. **Deep segment pages** (`/for/[segment]`) for anyone who wants the full argument — the six `audiences/*.md` files in `nilscript-landing`, re-authored for the *product* and animated.

---

## 2. Tech stack (decided, with rationale)

| Concern | Choice | Rationale |
|---|---|---|
| Framework | **Next.js 15 (App Router) + React 19 + TS** | Matches `wosool-hub` (React 19), one version ahead of `nilscript-landing`. SSG/ISR for marketing SEO; RSC for the static shell, client islands for demos. |
| Styling | **Tailwind CSS v4 + CSS custom-property token layer** | Same model as both repos. Tokens as CSS vars (web/coding-style). Reuse the hub's oklch palette so the site *matches the product*. |
| **Animation (the point of this repo)** | **Framer Motion (motion/react) as primary** + a small **GSAP + ScrollTrigger** layer for the scrollytelling timelines + **Lenis** for smooth scroll | Brief demands "rich animation framer + rich interactive animation A LOT". Framer for component/gesture/`layout`/`AnimatePresence`; GSAP+ScrollTrigger for pinned, scrubbed, multi-act sequences where Framer's scroll API is weaker; Lenis for the buttery scroll that makes scrubbing feel designed. |
| Interactive graph/canvas demo | **@xyflow/react (React Flow)** | Same lib the product uses (`/canvas`, `/graph`) — the landing demo is *visually identical to the real thing*, which is itself a trust signal. |
| Chat/console demo | Custom lightweight typewriter component (NOT `@assistant-ui`) | The product uses assistant-ui; the landing only needs a *scripted, deterministic* fake of it — lighter, no backend. |
| Icons | **lucide-react** | Both repos already use it. |
| i18n / RTL | **next-intl** + `dir` switching + logical CSS properties | Bilingual ar/en is a first-class requirement (the wedge is MENA). RTL is designed-in, not retrofitted. |
| 3D (optional, budgeted) | **React Three Fiber + drei**, lazy-loaded, one hero moment only | One tasteful 3D "governance boundary" object in the hero, code-split and gated behind `prefers-reduced-motion` + a low-power check. Not load-bearing. |
| Fonts | **Inter** (sans) + **JetBrains Mono** (governed/audit surfaces) + **IBM Plex Sans Arabic** (RTL) | Exactly the hub's stack — the audit/mono surfaces should *read like infrastructure you trust* (VISION §8.8). |
| Analytics | Plausible or PostHog (privacy-first), segment-tagged events | Measure which segment card → which demo → which CTA converts. |
| Deploy | Static/ISR export → the shared Hetzner Caddy (like `wosool.ai`), new host `get.wosool.ai` or `wosool.ai` apex | Consistent with existing NIL deploy topology; additive to shared Caddy. |

**Reduced-motion is a hard requirement, not a nicety.** Both existing repos already gate on `prefers-reduced-motion`; every animation in this plan ships a static/instant fallback. This is also an a11y gate (WCAG 2.3.3).

---

## 3. Information architecture / sitemap

```
/                     ← the spine: hero → thesis → live console demo → the machine →
                        canvas demo → governance+rollback → risk-collapse → proof/traction →
                        segment selector → pricing/CTA → footer
/for/owner            ← deep segment page (talk-to-run)
/for/finance          ← deep segment page (govern/audit/reverse)
/for/operations       ← deep segment page (cross-system canvas)
/for/developer        ← deep segment page (adapter-once, CLI)
/for/ai-labs          ← deep segment page (structural safety, benches)
/for/investors        ← deep segment page (category + traction)
/how-it-works         ← the tri-layer machine, expanded (propose→govern→commit→audit)
/demos                ← index of every interactive demo, playable standalone
/playground           ← link/iframe to the real product playground (propose→commit)
/pricing              ← open-core: standard is free; hosted control plane + certified adapters priced
/manifesto            ← the vision essay (VISION doc, re-authored, animated pull-quotes)
/proof                ← 18-platform calibration, ERPNext self-adopt proof, InjecAgent bench, live traction
/glossary             ← every term, defined (ported from nilscript-landing/reference/glossary.md)
/[ar|en] everything   ← locale-prefixed routes via next-intl
```

Nav is thin: **Product · How it works · For you (dropdown = 6 segments) · Proof · Pricing · [Docs↗ nilscript.org] · [Try it]** + language toggle (ع/EN) + theme toggle.

---

## 4. Section-by-section spec for the home spine (the AHA choreography)

Each section below lists: **content**, the **Framer/GSAP interaction**, and the **segment it primarily lands**. Sections are ordered so the spine tells one story top-to-bottom, but the segment selector (§1.3) can re-order via `layout` animation.

### S0 — Nav + language/theme
- Sticky, blur-backed, shrinks on scroll (Framer `useScroll` → `useTransform` on height/opacity).
- ع/EN toggle animates a full-page `dir` flip: content mirrors with a coordinated `AnimatePresence` wipe (the mirror itself is a little delight, and proves RTL is real).

### S1 — Hero: "Point your AI at your business."
- **Content:** Headline (bilingual): **"تحدّث إلى أعمالك. فهي تُنفّذ نفسها — بأمان." / "Talk to your business. It runs itself — safely."** Sub: *AI proposes. Code governs and executes.* Two CTAs: **[See it happen]** (scrolls to live demo) · **[For developers ↗]**.
- **Interaction (rich):**
  - Headline words rise + settle with a staggered spring (`staggerChildren`).
  - Behind it, the **optional R3F "governance boundary"**: a slow-rotating translucent membrane; particles (intents) drift toward it — green ones pass through and become solid "committed" cubes, red ones *dissolve at the boundary* (unexpressible). This is the whole thesis as ambient motion. Lazy-loaded; falls back to the CSS particle-stream (ported from `nilscript-landing/aha/stream.tsx`) on reduced-motion/low-power.
  - A magnetic cursor pull on the primary CTA (Framer `useMotionValue` + spring).
- **Lands:** everyone (ambient), owner (headline).

### S2 — The tension: "Two broken camps." (category set-up)
- **Content:** VISION §1/§3 three-camps table as a living diagram: *Deterministic-but-manual* (Zapier/n8n) vs *AI-but-ungoverned* (Lindy/browser agents) — and the wedge **between** them.
- **Interaction:** GSAP ScrollTrigger **pinned** scene. As you scroll, two columns slide in from left/right, collide, and a glowing seam opens between them where the Wosool wedge materializes. Scrubbed (progress-linked), not autoplay — the user *drives* the reveal.
- **Lands:** investor, owner, ops.

### S3 — Live demo #1: **Talk-to-automation console** (the headline AHA)
- **Content:** A faithful, *scripted* replica of the product `/ask` split-view (VISION §8.2): chat left, **"what the code decided"** right.
- **Interaction (the signature moment):**
  1. Pre-filled prompt types itself: *"Every Won deal in Odoo → make an invoice and ping finance."* (bilingual variants).
  2. The agent "thinks" (shimmer), then the **right panel assembles the governed plan node-by-node** with spring pop-in: `stage 1 · Odoo · crm.read_deal → stage 2 · Books · acc.create_invoice`, handoff `deal.total → amount`, trigger `on deal.stage = "won"`, **tier: REVERSIBLE · hash a3f8…**.
  3. A **[try your own]** mode: the user can pick from ~6 canned sentences; one of them intentionally names a fake verb (`crm.fly`) → the right panel throws the **structured refusal** `✗ V4 crm.fly: not a declared verb` with a red shake. *This is the "unexpressible, not filtered" AHA made tactile.*
  4. `[Approve]` button → green ripple → the plan collapses into a compact "armed automation" card that flies up into a "your tools" shelf.
- **Tech:** deterministic state machine, Framer `AnimatePresence` + `layout` for the fly-to-shelf; no real backend.
- **Lands:** owner (primary), finance (sees the tier + approval), everyone.

### S4 — The machine: **propose → govern → commit → audit**
- **Content:** The tri-layer (VISION §7): agent (generative) → NIL kernel (deterministic validator V1–V6) → backends. The four structural guarantees (Constitution §6) as four cards.
- **Interaction:** A horizontal **scroll-scrubbed conveyor**: an intent token rides left→right through four gates; each gate lights and stamps it (previewed → tier-checked → content-hashed → read-back). At the "undeclared verb" fork, a token visibly *loses its representation* and vanishes (`β⁻¹ = ∅`). GSAP timeline pinned; each guarantee card flips (Framer `rotateY`) as its gate activates.
- **Lands:** developer, ai-lab, finance.

### S5 — Live demo #2: **Cross-system canvas** (the ops AHA)
- **Content:** A real **React Flow** canvas with 3 nodes (Odoo `create_lead` → Books `create_invoice` → WhatsApp `notify`), governance badges on each node (REVERSIBLE/COMPENSABLE/IRREVERSIBLE + tier chip).
- **Interaction:** The user can **drag a new wire**. Drawing a valid handoff snaps green. Drawing a **dangling/forward wire** snaps **red and is refused in place** with an inline diagnostic — exactly the product behavior (VISION §8.3). A verb dropdown populated "live" (from a static skeleton fixture) shows you can only pick declared verbs. Minimap, draggable nodes — same feel as `/canvas`.
- **Lands:** operations (primary), developer.

### S6 — Live demo #3: **Governance timeline + honest rollback** (the finance AHA)
- **Content:** The productized control-plane timeline (VISION §8.7 / §9): an append-only, HMAC-verified log; a HIGH-tier write parks for approval; a wrong write gets **rolled back via a real compensation** (never a faked undo).
- **Interaction:** A vertical timeline where each event card slides in (`whileInView`). One CRITICAL row has a **cooling delay** countdown ring. A **[Roll back]** button on a reversible row triggers an animated compensation: the original write and its inverse are drawn as a matched pair, and an IRREVERSIBLE row's rollback button is visibly disabled with the honest tooltip *"cannot fake an undo it can't do."* This honesty is the trust AHA.
- **Lands:** finance (primary), decision-maker, owner.

### S7 — **Risk collapses: O(n) → O(1)** (the AI-lab AHA)
- **Content:** Ported and warmed-up from `nilscript-landing/aha/synthesis.tsx`: the interactive dials showing filter-risk `1 − (1−ε)^n` growing with checkpoints vs. NIL's structural `0` by construction. Plus the InjecAgent headline: **0.00% unauthorized writes across 2,108 evals** (Constitution §6 / benchmark).
- **Interaction:** Two range dials (`n` checkpoints, `ε` leak rate); an SVG risk curve re-renders in real time (Framer `useMotionValue`); at the end the whole probabilistic curve **collapses to a flat zero line** with a satisfying snap. "Try to break it" framing.
- **Lands:** ai-lab (primary), security-minded finance, developer.

### S8 — **Proof it's real** + traction band
- **Content:** Constitution §"Why it is real": 18-platform / 90-row calibration; ERPNext self-adoptable proof; running-in-production. Live MENA wedge (Salla/WhatsApp/Arabic-native) as the distribution edge.
- **Interaction:** A **counter band** (numbers count up on view — 18 platforms, 90 rows, 2,108 evals, 0.00%), an animated world-to-MENA map zoom, logo/adapter marquee (Odoo, Salla, PocketBase, ERPNext) with a subtle infinite scroll.
- **Lands:** investor, decision-maker, everyone (credibility).

### S9 — **Find your path** (the interactive segment selector)
- **Content:** Six cards (the §1.2 table). This is the re-router (§1.3).
- **Interaction:** Bento-grid of 6 cards; hover tilts (3D `rotateX/Y` on pointer). Click → the card expands (`layout` shared-element) into a mini-pitch + its demo, and the page re-orders to promote that segment (URL → `?for=`). A "reset" returns to the neutral spine.
- **Lands:** the mechanism that lands *all* of them.

### S10 — Pricing (open-core, honest)
- **Content:** Constitution §11: the **standard is free** (CC BY 4.0, `pip install nilscript`); the **commercial layer** is the hosted control plane + certified-adapter network. Three tiers: Open (self-host) · Hosted · Enterprise (on-prem, EU-AI-Act audit).
- **Interaction:** A toggle (self-host ↔ hosted) that morphs the tier cards (`layout`); feature rows check in with a stagger.

### S11 — Final CTA + footer
- **Content:** Dual CTA — **[Start free]** (playground) for builders, **[Book a walkthrough]** for buyers. Footer with the NILScript-credit line (§0), links to `nilscript.org`, GitHub, PyPI, glossary, contact.
- **Interaction:** A closing restatement of the thesis with the hero membrane returning, now calm.

---

## 5. The animation system (so it's rich but coherent, not chaotic)

"A LOT of animations" only works if they share a grammar. Define it once:

### 5.1 Motion tokens (in `lib/motion.ts`)
- **Easing:** one signature curve `cubic-bezier(0.16, 1, 0.3, 1)` (already the house curve in both repos) for entrances; a springier `{ type: "spring", stiffness: 260, damping: 26 }` for interactive/gesture.
- **Durations:** `fast 150ms · normal 300ms · slow 700ms` (VISION token set).
- **Stagger:** `0.06s` children default.
- **Reusable Framer variants:** `fadeUp`, `springPop`, `revealStagger`, `flipCard`, `magnetic`, `wipe` — imported everywhere so 40 animations feel like one designer made them.

### 5.2 Layering (what tech does what)
| Layer | Tool | Used for |
|---|---|---|
| Ambient/hero 3D | R3F (lazy) | one hero membrane only |
| Scroll scrollytelling | GSAP + ScrollTrigger + Lenis | S2, S4 pinned/scrubbed acts |
| Component/gesture/state | Framer Motion | everything else (entrances, hovers, `layout` reflow, `AnimatePresence`, dials) |
| SVG micro-animation | inline SVG + Framer `useMotionValue` | risk curve, plan-assembly connectors, particle stream fallback |
| Canvas demo | React Flow | S5 |

### 5.3 Interaction inventory (the "a lot" made concrete)
Hero word-stagger · magnetic CTA · membrane particle physics · scroll-shrink nav · RTL mirror wipe · pinned two-camps collision · typewriter prompt · node-by-node plan assembly · refusal red-shake · approve ripple · fly-to-shelf `layout` · scrubbed guarantee conveyor · card flips · draggable governed wire with in-place refusal · verb-dropdown constraint · timeline slide-ins · cooling-delay ring · compensation matched-pair draw · disabled-rollback honest tooltip · dual risk dials · curve-collapse snap · count-up counters · MENA map zoom · adapter marquee · bento tilt cards · shared-element segment expand · page re-order reflow · pricing toggle morph · closing calm membrane. **(~30 distinct interactions, each with a reduced-motion fallback.)**

### 5.4 Performance discipline (web/performance.md budgets)
- Every heavy island (`R3F`, `React Flow`, `GSAP`) is `next/dynamic` code-split, below-the-fold, `ssr:false`.
- Animate only compositor props (`transform`, `opacity`, `clip-path`, `filter`); `will-change` applied narrowly and removed after.
- LCP < 2.5s, INP < 200ms, CLS < 0.1. Landing-page JS budget target < 200kb gzip for the *initial* view; demos load on scroll.
- Lenis + ScrollTrigger reconciled (single RAF loop) to avoid scroll jank.

---

## 6. Design system

- **Inherit the hub's identity so site == product.** OKLCH palette, Inter + JetBrains Mono + IBM Plex Sans Arabic. Green = "safe to commit / approved"; the mono surfaces carry the governed/audit content (they must *read like infrastructure*).
- **Direction (anti-template, per web/design-quality):** *"governed control room, warmed for the market."* Dark-luxury technical base with editorial scale-contrast on marketing moments; one decisive green accent; depth via layered surfaces and the membrane motif; bento composition for the segment selector. Not a stock hero-with-gradient-blob. Light + dark both intentional; **do not default to dark** — pick per section (marketing sections can go light/editorial; demo sections go dark/operational to match the app).
- **Tokens** in `styles/tokens.css` as CSS custom properties (palette, type scale via `clamp()`, spacing, motion). Logical properties throughout (`margin-inline`, `padding-block`) so RTL is free.

---

## 7. Content & copy plan

- **Source of truth for every claim:** the **Positioning Constitution** (`docs/POSITIONING-CONSTITUTION.md`). Governing rule (§10 honesty clause): *no description claims a property the running code does not earn.* Marketing copy is reviewed against §14 approved/banned descriptors. Banned as primary: "OpenAPI for agents", "agentic firewall" (unless immediately qualified), "guardrail", "makes agents safe".
- **Re-author, don't copy:** the six `nilscript-landing/audiences/*.md` become the six `/for/*` pages but rewritten for the *product* (owner-outcome language), bilingual, animated pull-quotes.
- **Three depths, same truth** (Constitution §12 / VISION §12): each segment page carries the developer/buyer/investor register of the *same* guarantee.
- **Bilingual copy** authored ar + en in `messages/{ar,en}.json`; Arabic is the wedge language, not an afterthought. (Note: the *standard* stays English-only per Constitution §3 — but **Wosool, the product, is explicitly an Arabic-market surface where Arabic is expected.** This site is the product, so bilingual is correct.)
- **Content collections** in MDX so narrative pages (`/manifesto`, `/how-it-works`, `/proof`, `/glossary`) are editable without touching components; the animation wrappers (`<Reveal>`, `<PullQuote>`, `<Scrolly>`) are MDX components.

---

## 8. i18n / RTL / accessibility

- `next-intl` locale-prefixed routing (`/ar`, `/en`), `dir` from locale, logical CSS everywhere, mirrored motion (an ✕→ that points inward in RTL).
- **Accessibility (a11y-architect gate, WCAG 2.2):** every animation respects `prefers-reduced-motion` with an instant fallback (both existing repos already do this — keep the discipline); keyboard-navigable demos; ARIA on interactive SVGs and the console; focus-visible rings; color-contrast AA in both themes; the segment selector is real buttons, not div-clicks; captions on the demo video.
- Reduced-motion fallback strategy is **per-section documented** (the R3F membrane → static gradient; scrubbed acts → plain fade-in of the end state; dials → still functional, just no spring).

---

## 9. Repo structure

```
wosool-landing/
├── app/
│   ├── [locale]/
│   │   ├── page.tsx                 # the spine (composes sections)
│   │   ├── for/[segment]/page.tsx
│   │   ├── how-it-works/page.tsx
│   │   ├── demos/page.tsx
│   │   ├── pricing/page.tsx
│   │   ├── manifesto/page.tsx  proof/page.tsx  glossary/page.tsx
│   │   └── layout.tsx               # dir + theme + intl providers
│   └── globals.css
├── components/
│   ├── sections/                    # S1..S11, one file each
│   ├── demos/
│   │   ├── console/                 # talk-to-automation (S3)
│   │   ├── canvas/                  # React Flow governed canvas (S5)
│   │   ├── governance/              # timeline + rollback (S6)
│   │   └── risk-dials/              # O(n)→O(1) (S7)
│   ├── motion/                      # Reveal, Scrolly, PullQuote, Magnetic, FlipCard
│   ├── three/                       # hero membrane (lazy)
│   ├── segment/                     # selector + re-router
│   └── shell/                       # nav, footer, lang/theme toggles
├── content/                         # MDX narrative + fixtures (skeletons, canned prompts)
├── lib/                             # motion.ts, cn.ts, site.ts, segments.ts, fixtures.ts
├── messages/{ar,en}.json
├── styles/{tokens,typography,rtl}.css
└── public/                          # video, logos, adapter marks (reuse hub SVGs)
```

Mirror the hub's inline-SVG logo approach (`WosoolWordmark`/`WosoolMark`) so it never 404s.

---

## 10. Build phases (each phase ships something demoable)

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **P0 — Scaffold** | Next 15 repo under `nilscript-org`, Tailwind v4, next-intl (ar/en), token layer copied from hub, motion grammar (`lib/motion.ts` + variants), nav/footer shell, theme+lang toggles, Lenis. | ar/en routes render, RTL flips, reduced-motion honored, CI + Vercel/Caddy preview. |
| **P1 — Static spine** | All 11 sections with *entrance* animations only (Framer `whileInView`), real bilingual copy vetted vs Constitution §14. | Full scroll reads as a coherent pitch on mobile+desktop; Lighthouse ≥ 90; copy sign-off. |
| **P2 — Demo #1 (console)** | The talk-to-automation split-view incl. the refusal path + fly-to-shelf. | Owner + finance AHA verified in user test; deterministic, no backend; a11y pass. |
| **P3 — Demo #2 (canvas)** | React Flow governed canvas with in-place wire refusal + verb constraint. | Ops AHA verified; matches product look. |
| **P4 — Demo #3 (governance+rollback)** & **Demo #4 (risk dials)** | Timeline/rollback + ported/warmed risk-collapse. | Finance + ai-lab AHA verified; honest-rollback disabled-state correct. |
| **P5 — Scrollytelling + hero 3D** | GSAP pinned S2/S4 acts + R3F membrane (lazy, gated). | Scrub feels designed; membrane ≤ budget; low-power fallback works. |
| **P6 — Segment selector + re-router** | S9 bento + `layout` page re-order + `?for=` URL state + 6 `/for/*` deep pages. | Each segment reaches its AHA in ≤ 2 interactions; URL shareable. |
| **P7 — Proof/pricing/traction + polish** | Counters, MENA map, marquee, pricing toggle, MDX narrative pages, glossary. | All claims cite the Constitution; CWV green; cross-browser + RTL QA. |
| **P8 — Launch** | SEO (per-locale meta, OG, sitemap, structured data), analytics with segment funnels, deploy to `wosool.ai`/`get.wosool.ai` via shared Caddy. | Live, tracked, both locales, TLS, LCP<2.5s. |

---

## 11. What we reuse vs. build new (DRY / don't reinvent)

**Reuse (port/adapt):**
- `nilscript-landing`: the `Reveal` IntersectionObserver pattern, the `aha/synthesis` risk dials, the `stream` particle CSS, the InjecAgent benchmark assets, the glossary + comparison content, the reduced-motion discipline.
- `wosool-hub`: the token system (oklch palette), Inter/JetBrains/Plex-Arabic stack, the `WosoolLogo` components, React Flow config, adapter SVGs, the `/ask` split-view layout and `/governance` timeline as *visual references* for the scripted demos.
- `docs/`: Constitution (copy law), VISION (product story + the exact ASCII mocks for S3/S5/S6), the audiences markdown (six `/for/*` pages).

**Build new (the genuinely novel work):**
- The **segment re-router** (`layout`-animated page reflow + URL state).
- The **four scripted interactive demos** (deterministic state machines, no backend).
- The **Framer/GSAP/Lenis/R3F animation layer** and its shared grammar.
- **Bilingual RTL-first** marketing content and the mirror-motion system.

---

## 12. Risks & open questions

1. **Animation overload vs. clarity.** "A lot of animations" can tip into noise. Mitigation: the shared motion grammar (§5.1), one signature motif (the membrane) reused, and a rule — *motion only where it clarifies the propose→govern→commit flow* (VISION §8.8). Every section must justify its motion or lose it in review.
2. **Demo fidelity vs. reality.** Scripted demos must match real product behavior or the trust breaks (same risk as VISION §13.1 canvas↔DSL fidelity). Mitigation: mirror the hub's actual components/verbs/refusal codes; label demos "interactive preview".
3. **Positioning discipline.** Easy to blur into "another AI workflow tool" (VISION §13.5). Mitigation: lead every section with generate-vs-govern; Constitution §14 lint on all copy.
4. **Standard vs. product line.** The site sells Wosool but must not misrepresent itself as the standard (Constitution §11). Mitigation: the persistent NIL-credit line + `nilscript.org` handoff; English-only claims about the *standard*, bilingual claims about the *product*.
5. **Perf budget under heavy motion.** R3F + GSAP + React Flow + Lenis is a lot of JS. Mitigation: aggressive code-splitting, below-the-fold hydration, the CWV gates in §5.4 as CI checks (Lighthouse budget assertions).
6. **RTL QA is the known weak spot** (the hub's own gap list flags "RTL QA incomplete"). Mitigation: RTL is a first-class P0 concern here, logical properties from day one, dedicated RTL QA pass in P7.

---

## 13. The one sentence

> **`wosool-landing` is the site where a business owner, a CFO, an ops lead, a developer, an AI-lab engineer, and an investor each scroll into the *same* truth — AI proposes, code governs, your business runs itself safely — and each one, through a demo built for exactly them, says "AHA."**
