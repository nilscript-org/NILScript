# NIL Governance

## The Reference Implementation Rule
**wosool is the reference implementation and the steward of NIL.** The spec is extracted from
running code, never the reverse: no normative change is released in the specification before
it is implemented, tested, and operated in wosool. ("Rough consensus and running code.")
Continuous development of wosool feeds the standard on a fixed cadence — see VERSIONING.md.

## Roles
- **Steward (the wosool project):** maintains the spec, operates the reference implementation,
  has final merge authority on normative text, publishes releases.
- **Maintainers:** named in MAINTAINERS file; review proposals; appointed by the Steward.
- **Contributors:** anyone, via the process below.
As independent conformant implementations appear, the Steward commits to forming a technical
steering group with implementer seats (the OpenAPI/TSC pattern), at the 0.x→1.0 boundary.

## Change process
1. Open an issue using the `proposal` template: problem, proposed normative text, security
   analysis against §15, and — REQUIRED — implementation experience or a plan to gain it in
   the reference implementation. Conformance is demonstrated via the checklist and
   implementation reports (versions/*-conformance-checklist.md); an assertion the reference
   implementation cannot pass blocks the non-draft release of its clause (implement or
   demote). Promotion to 1.0 additionally requires two independent interoperable
   implementations with passing reports.
2. Discussion ≥ 14 days. 3. Implementation lands in wosool behind a flag. 4. Spec PR merges to
   the development branch. 5. Ships in the next dated release.
Fast-track exists for editorial fixes only. Security disclosures: SECURITY contact, 90-day
coordinated disclosure.

## What governance protects (the invariants)
The performative set stays closed. The Six Guarantees never weaken. DECIDE never becomes
Speaker-reachable in any binding. Floors remain non-lowerable. Previews remain complete and
human-natural. Tenant isolation (NIL-H H1) never weakens — no clause may make another
Workspace's data, existence, or capacity observable. Any proposal violating an invariant is
rejected regardless of support.
