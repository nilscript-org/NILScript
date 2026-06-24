# Scope and non-goals

NILScript governs **each effect, independently, at the propose→commit boundary.**
For a single declared effect it guarantees:

- **Unexpressibility.** No undeclared verb or target is committable. The skeleton is
  the surface; what isn't in it cannot be proposed, let alone committed. This is a
  property of the contract, not a filter applied after the fact.
- **Preview before write.** Every write is previewed at `propose`, approved, and
  earned-verified before the side effect happens. No blind commit against stale state
  (see `PRECONDITION_FAILED` — the state-witness fails closed on drift).
- **Reversibility per declared tier.** Each effect is reversible to the extent its
  declared compensation tier promises — and refuses honestly (`IRREVERSIBLE`,
  `COMPENSATION_EXPIRED`) when it cannot.

These guarantees hold **per effect.** The kernel is deterministic and stateless: it
decides one proposal against the skeleton and the SSOT it previewed, then forgets.

## Out of scope by design: compositional / session-level risk

NIL does **not** track session context across multiple proposals. It therefore cannot,
by itself, detect that two **individually declared, individually approved** actions
**compose** into a breach.

The canonical example: an agent reads customer PII through a declared, in-skeleton query,
then sends that data outward through a declared, in-skeleton write. Each proposal passes
the skeleton cleanly. Each is unexpressible-safe, previewed, approved, and reversible.
The *sequence* is the leak — and a stateless per-effect kernel has no memory of the first
proposal when it admits the second. This is the AARM "context-dependent deny" /
intent-drift class: a risk that lives in the trajectory, not in any one effect.

This is a **deliberate boundary**, not a gap NIL is hiding. Per-effect governance is what
makes the kernel deterministic, auditable, and free of model inference in the decision
path. Buying that property means declining to reason about trajectories.

## The complementary layer

Compositional / intent-drift detection is real work, and it belongs **above** NIL — the
same way NIL composes above MCP. AARM (Autonomous Action Runtime Management,
arXiv:2602.09433) targets exactly this: it intercepts actions, accumulates session
context, and applies intent-alignment to allow / deny / modify / defer / step-up across a
trajectory. An AARM-style layer can sit on top of a NIL gate, using NIL's previews and
receipts as its per-effect substrate while it reasons about the sequence NIL is, by
design, blind to.

Conceding this does not weaken NIL. A per-effect contract that claims only what it can
deterministically guarantee — and names what it cannot — is stronger than one that
overclaims. The honest boundary is the point.
