# NILScript — messaging spine

> The single source of narrative truth. The README, PyPI blurb, docs hero, and landing all draw
> from this file so they never contradict each other. If a sentence about "what NIL is" appears on
> two surfaces, it traces back here.

## One-liner

**NILScript is the governed action layer for AI agents: the agent proposes intent, a deterministic
kernel is the only component that commits, and an action a backend never declared is unexpressible
rather than filtered.**

> Canonical descriptor: *the governed action layer for AI agents.* Primary tagline:
> *Unexpressible, not filtered.* NIL expands to **Network Intent Layer** (never "Language"). NIL
> composes with MCP as the governed layer MCP leaves undefined; it does not replace it.

## The problem

Every "agent + your system" integration is rebuilt from scratch. Two frictions dominate:

- **Discovery** — a backend's real requirements are hidden and undocumented (required fields,
  prerequisite entities, transport quirks). You learn them by collision.
- **Safety** — an agent must not write blindly. There is no neutral contract that guarantees
  "propose first, commit only on confirmation."

## The insight

Separate the neutral **intent layer** (verbs, envelopes, confirmation, the endpoints) from
**backend reality** (captured once in a shareable manifest). Build an adapter once; scan a system
once; the world shares the result.

## The proof (honest)

A real customer + invoice executed through the conversational gateway into a **live ERPNext**, from
the standard alone. That is the completed proof. There is **no merchant adoption at scale yet** —
the story is "open standard + proven reference path," not "battle-tested in production." The zero
unauthorized-write result is **by construction** within the threat model and confirmed on a live
backend, not a surprising empirical rate; it holds only while NIL is the sole effect path. On the
kernel API path the kernel performs the read-back confirmation; on the MCP path that confirmation
currently rests on the adapter envelope, gated at admission but not yet re-verified per request
(kernel-side re-verification there is future work).

## Three pillars

1. **Governed, not glued** — an agent can only name verbs and targets the backend has declared; an
   undeclared action has no representation to send, so it is unexpressible, not filtered.
2. **Earned, not asserted** — `PROPOSE` has no side effects; nothing commits without approval; a
   success envelope is confirmed by reading the record back; `ROLLBACK` previews a real compensation,
   never a silent write, and never pretends an irreversible effect can be undone.
3. **De-frictioned by tooling** — `scan` once, generate an adapter, share the manifest.

## What it is, precisely (two layers, both specs)

| Layer | Name | What it is |
| --- | --- | --- |
| **Operations** | **NIL** (Network Intent Layer) | The wire contract: how an agent proposes an action, how a backend answers, the envelope, grants, refusals, rollback, and per-domain profiles. Seven performatives (**SEQRD-PC**: STATUS · EVENT · QUERY · ROLLBACK · DECIDE · PROPOSE · COMMIT). |
| **Orchestration** | **nilscript DSL** | A declarative, JSON-based, LLM-native language one layer above NIL: an agent writes a program, a static validator admits it, a durable runtime executes it. |

Both are specs, not software. A reference implementation obeys them; it never defines them.

## Comparables to invoke

MCP and OpenAPI standardize what an agent can *reach*; NIL governs what an agent can *author*, and
composes with them as the governed action layer they leave undefined. The closest correct analogy is
**server-side authorization for agent writes** (OAuth-shaped, enforced at the effect boundary). Use
JSON Schema / Stripe-doc clarity as a *quality* reference, not as the definition. Do **not** describe
NIL as "OpenAPI for agent-actions," an "agentic firewall" (unless immediately qualified "structural,
not a filter"), a "guardrail," something that "makes agents safe/trustworthy," or a replacement for
MCP — these are banned descriptors.

## Voice

Precise, engineer-to-engineer, low-hype.

**Banned words:** revolutionary, seamless, magical, effortless, game-changing, blazing-fast.
**Avoid implying:** scale, traction, or merchant adoption that does not exist.
**Prefer:** concrete verbs, real command output, honest status ("young open standard, v0.2").

## Glossary (canonical terms)

- **NIL** — Network Intent Layer; the governed-action contract (a neutral wire contract under which an
  agent proposes intent and only a deterministic kernel commits).
- **nilscript DSL** — the orchestration language above NIL.
- **Verb** — a named action in a domain profile (e.g. `commerce.create_product`).
- **Envelope** — the request/response wrapper on the NIL wire (`nil`, `grant`, `workspace`, `body`).
- **Performative** — one of the seven SEQRD-PC message kinds.
- **PROPOSE / COMMIT** — the two-step safe-write: propose has no side effects; commit executes.
- **ROLLBACK** — previews and applies a compensation for a reversible verb; never a silent write.
- **Manifest** — `requirements-manifest.json`: a backend's discovered, shareable requirements.
- **Adapter / shim** — the translation layer making one backend speak NIL.
- **Conformance** — the three gates: offline proof, live proof, manifest honesty.
- **Reversibility tier** — `REVERSIBLE` / `COMPENSABLE` / `IRREVERSIBLE`; earned, not asserted.

## Surface-by-surface usage

| Surface | Pulls from this spine |
| --- | --- |
| README hero | one-liner + three pillars + honest status |
| PyPI blurb | one-liner + install + command tour (rendered README) |
| Docs hero | one-liner + problem + insight; links to Concepts |
| Landing hero | one-liner + live terminal demo + two CTAs |

Every reused fact has **one canonical home**; other surfaces link, never fork.
