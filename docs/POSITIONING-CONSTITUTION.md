# NILScript: Canonical Definition and Positioning Constitution

**Version 1.0 · Locked 2026-06-23 · Owner: ElBasheir A. M. Elkhider**

This file is the single source of truth for how NILScript is named, defined, and described
everywhere: the paper, Zenodo, arXiv, GitHub, the website, decks, social bios, and Wosool. If any
other source conflicts with this file, this file wins. The rule is one-directional: change this file
first, then propagate to every surface in section 13. Do not coin a new description in a README or a
tweet that is not derived from here.

A governing constraint sits above everything below, taken from the standard itself: no description
claims a property the running code does not earn. Where a claim has a boundary or an assumption, it
is stated, not smoothed over. This is the same earned-not-asserted discipline NILScript enforces on
agents, applied to its own marketing.

## 0. The lock (canonical identifiers)

| Field | Canonical value |
|---|---|
| Name | NILScript (the standard + reference implementation); NIL (the contract) |
| NIL expands to | Network Intent Layer (see the ratify note in section 9) |
| Standard package | `pip install nilscript` |
| SDK | `pip install nilscript[sdk]` |
| License | CC BY 4.0 |
| Concept DOI | `10.5281/zenodo.20774491` |
| ORCID | `0009-0000-6111-1685` |
| arXiv handle | `basheirkh` |
| Site / contact | `nilscript.org` · `contact@nilscript.org` |
| Commercial reference implementation | Wosool (Salla/MENA commerce; see section 11) |

## 1. One-sentence definition (locked)

> NILScript is a server-side governed-action contract for AI agents: the agent proposes intent, a
> deterministic kernel is the only component that commits, and an action a backend never declared is
> unexpressible rather than filtered.

Use this verbatim when one sentence is needed.

## 2. The category (locked)

NIL is the governed action layer that tool-integration standards leave undefined. MCP and OpenAPI
standardize what an agent can reach. NIL governs what an agent can author. NIL composes with them; it
does not replace them. The failure mode this prevents is being filed next to MCP (an integration
layer) or next to guardrails (a probabilistic filter). NIL is neither.

## 3. Taglines and slogans (locked)

- Primary tagline: Unexpressible, not filtered.
- Descriptor line: The governed action layer for AI agents.

Lead with the primary tagline where there is room for one striking line; use the descriptor line where
the reader needs the category in plain words. NILScript is an open international standard: all public
positioning and marketing surfaces are English-only. (Arabic is not banned inside product surfaces
that are themselves Arabic-market, such as Wosool, or inside technical examples of the locale-driven
bilingual preview; it is simply not used to brand the standard.)

## 4. Vision

AI agents are moving from writing text to taking actions on the systems a business already runs. The
barrier is not capability; it is trust. NILScript exists so that an organization can let an agent
operate its real systems without having to trust the agent, by moving the trust boundary to the
server and making the unauthorized action impossible to commit rather than merely discouraged. The
long-term aim is for NIL to become the default action layer between agents and backends, the way TLS
became the default for transport. The path runs through MENA and Arabic-native commerce first, then
outward.

## 5. Mission and goal

Make the unauthorized or hallucinated action structurally uncommittable on real backends, give any
backend a build-once governed adapter, and keep the NIL specification open so it spreads. The standard
stays open to win ubiquity; the commercial value lives one layer up, in the hosted control plane and
the certified-adapter network (section 11).

## 6. What NIL is (the four structural guarantees, in plain words)

1. No side effects on propose. An agent emits intent, not an action. Proposing leaves the backend
   byte-identical. Only an approved commit changes state.
2. Skeleton-bounded. An agent can only name verbs and targets the backend has declared. An undeclared
   verb or target has no representation to send. The bound covers the generic CRUD family, so
   advertised equals committable.
3. Honest, bounded reversibility. Every write declares whether it is reversible, compensable, or
   irreversible, and a rollback runs a real compensation through the same machinery. The system never
   fabricates a corrective write and never pretends an irreversible effect can be undone.
4. Earned, not asserted. A success envelope is confirmed by reading the record back; a reversibility
   tier is confirmed by a conformance run. An adapter that claims a property its run does not honour
   fails admission.

The formal core: an undeclared action has empty preimage under the binding (beta^{-1}(a) = empty).
This is strictly stronger than filtering, where the action can be named and a classifier admits it
with nonzero probability.

## 7. What NIL is NOT (anti-positioning)

- Not "OpenAPI for agent actions." OpenAPI and MCP describe a surface so a client can call it; the
  agent still authors the call. NIL removes the agent's ability to author an undeclared call at all.
- Not an "agentic firewall" or a guardrail. A firewall or guardrail inspects a namable action and
  blocks it with some probability. Under NIL the unauthorized action is not namable. If "firewall" is
  used as a hook, it must be followed immediately by "but structural, not a filter."
- Not "makes agents safe or trustworthy." NIL does not make the model correct. NIL makes the
  unauthorized action uncommittable, not the agent wise.
- Not a replacement for MCP. NIL composes with MCP as the governed action layer MCP does not define.

## 8. How NIL relates to the things people already know

- MCP / OpenAPI / function-calling: integration layers (discovery and invocation). NIL sits underneath
  the effect and governs it.
- Guardrails (classifiers, policy prompts): probabilistic per-step filters over a namable action. NIL
  is a single structural boundary; the rate is zero by construction, not small by tuning.
- OAuth / server-side authorization: the closest correct analogy. NIL is authorization for agent
  writes, enforced at the effect boundary on the server, independent of the model.
- "USB for systems": the adapter analogy; always paired with the governance point.

## 9. Naming and terminology lock

- NILScript: the project, the standard, and the reference package. One word, capital N-I-L, capital S.
- NIL: the contract itself. Acceptable on its own after first defining NILScript.
- NIL expands to Network Intent Layer. The lower layer is a wire contract; the upper, optional layer is
  a declarative orchestration language. "Layer" names the whole.
- Wosool: the commercial reference implementation, never a synonym for NILScript (section 11).

RATIFY: earlier notes recorded "Network Intent Language." The published paper, the Zenodo record, and
the DOI all use "Network Intent Layer." This file locks Layer because it matches the published,
citable artifacts. Default and recommendation: keep Layer.

## 10. The honesty clause (governing)

- The zero unauthorized-write result is by construction within the threat model, confirmed on a live
  backend, not a surprising empirical rate.
- The structural guarantee holds only while NIL is the sole effect path.
- On the kernel API path the kernel performs the confirmation and read-back; on the MCP path the
  confirmation currently rests on the agent's mechanism and the adapter envelope, gated at admission
  but not yet re-verified per request. Kernel-side re-verification on that path is future work.

Any source that drops these boundaries to sound stronger is off-constitution.

## 11. Standard versus product (open-core)

- NILScript (the standard) is open (CC BY 4.0). Ubiquity is the goal; a wide adapter ecosystem is the
  network effect.
- The commercial layer is the hosted control plane and the certified-adapter network, not the spec.
- Wosool is the first commercial reference implementation: an AI operations layer for Salla merchants
  in MENA (WhatsApp-native, Arabic-native). Wosool is built on NILScript; it is not NILScript.

## 12. Audience register (same truth, three depths)

- Developer: "An agent proposes intent over NIL; a deterministic kernel commits only declared,
  approved writes, and reads the result back. Build one adapter per backend; any agent can then operate
  it without being trusted. `pip install nilscript`."
- Enterprise / government buyer: "A server-side authorization layer for agent actions. Writes pass a
  declared propose-approve-commit lifecycle with an auditable trail; an undeclared write cannot be
  issued. Deployable on-premises; the governance boundary is enforced in code, not in a prompt."
- Investor: "The governed action layer for AI agents. MCP standardized how agents reach systems and
  left how they are governed undefined. NILScript is the open standard for that layer, monetized
  through a hosted control plane and a certified-adapter network, with a live commerce implementation
  in MENA."

## 13. Canonical text blocks

arXiv / Zenodo abstract line:
> NIL is a neutral wire contract under which an agent never issues an action; it can only propose
> intent against operations a backend has explicitly declared. An action a backend never declared is
> unexpressible, not merely blocked. NIL is the governed action layer that integration standards such
> as MCP do not define.

GitHub README opening:
> # NILScript
> The governed action layer for AI agents. An agent proposes intent; a deterministic kernel is the only
> thing that commits; an action a backend never declared is unexpressible, not filtered. Composes with
> MCP. `pip install nilscript`.

Website hero:
> Unexpressible, not filtered.
> NILScript is the governed action layer for AI agents. The agent proposes; only the kernel commits;
> the undeclared action cannot be named.

Social bio (<=160 chars):
> NILScript: the governed action layer for AI agents. Agents propose, only the kernel commits, the
> undeclared action is unexpressible. Open standard. nilscript.org

One-paragraph "about":
> NILScript is an open, server-side governed-action contract for AI agents. Instead of letting an agent
> call a system directly and catching mistakes afterward, NIL lets the agent only propose intent against
> operations a backend has declared; a deterministic kernel is the only component that commits a write,
> after an approval step and with the result read back. An action the backend never declared has no way
> to be expressed, so it cannot be issued rather than being filtered after the fact. NILScript composes
> with tool standards such as MCP as the governance layer they do not define, and is implemented
> commercially by Wosool for MENA commerce.

## 14. Approved and banned descriptors

Approved: governed action layer · governed-action contract · server-side authorization for agent
writes · unexpressible, not filtered · the agent proposes, only the kernel commits · USB for systems
(with governance) · the governed layer MCP leaves undefined.

Banned as the primary definition: OpenAPI for agents · agentic firewall (unless immediately qualified
"structural, not a filter") · guardrail · makes agents safe/trustworthy · replaces MCP · any phrasing
that drops the section 10 boundaries.

## 15. Change control

A change to the locked definition, tagline, category sentence, or the section 9 name bumps the version,
is dated, and triggers a propagation pass across every surface in section 13.

Open items: ratify section 9 (Layer vs Language); confirm every external source in section 13 carries
the section 10 boundaries; align any older bio or README still using a banned descriptor.
