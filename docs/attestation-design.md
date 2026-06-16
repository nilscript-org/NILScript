# Conformance Attestation — design & roadmap

> **Status:** Roadmap / design (not built). · **Today's reality:** "certified" = the three
> conformance gates green in an adapter's CI. Do **not** advertise a signed certificate until the
> service in this doc exists.

## Problem

CI-green proves conformance *at a moment, on a runner you trust because you own it*. For a public
registry of third-party adapters that is not enough: a consumer wants a **portable, tamper-evident
proof** that *this adapter commit* conformed to *this kernel spec*, verifiable without re-running
anyone's CI or trusting their runner.

## The two pieces already in the kernel

The ledger primitives this design builds on already exist in
[`src/nilscript/cli/memory.py`](../src/nilscript/cli/memory.py):

- **`compute_spec_hash(parts)`** — a deterministic, order-independent SHA-256 over the spec parts
  (schemas + RFC text). The same spec always yields the same hash; any byte change yields a
  different one (the drift signal).
- **`MemoryStore` + `anchor_ratification(version, label, spec_hash)`** — an **append-only,
  content-addressed** JSONL ledger. Nothing is edited in place; a later change appears as a *new*
  anchor, never an in-place edit. `record_reversal(...)` already shows the pattern for immutable,
  audited records.

A conformance certificate is the same shape of record, for an adapter instead of the spec.

## The certificate (proposed record)

A new ledger entry kind, `attestation`, binding an adapter run to the spec it ran against:

```jsonc
{
  "kind": "attestation",
  "payload": {
    "adapter": "nilscript-org/pocketbase-nil-adapter",
    "adapter_commit": "<git sha>",
    "kernel_version": "0.3.0",
    "spec_hash": "<compute_spec_hash(...)>",     // the spec the gates ran against
    "gates": {
      "offline": {"passed": 16, "failed": 0},
      "live":    {"verbs": [...], "tiers": ["REVERSIBLE","COMPENSABLE","IRREVERSIBLE"]},
      "manifest": {"valid": true}
    },
    "verified_at": "<iso8601>",                  // stamped by the service, not the script
    "reviewer": "<maintainer | automated>"
  }
}
```

Because the store is append-only and content-addressed, the certificate **cannot be silently
altered** — exactly the property `anchor_ratification` relies on. A re-attestation after a kernel
bump is a *new* entry whose `spec_hash` differs, making drift visible rather than hidden.

## Signing & hosting (the part that does not exist yet)

1. A hosted **attestation service** receives an adapter's green CI run (offline + live + manifest),
   re-derives `spec_hash` for the declared `kernel_version`, and writes the `attestation` record.
2. It **signs** the canonicalized record (e.g. sigstore/cosign or an org Ed25519 key) and serves
   the signature + record at a stable URL. The badge then links to a verifiable artifact, not just
   an Actions run.
3. Verification = recompute `spec_hash` from the published spec, check the signature, confirm the
   `adapter_commit` matches. No trust in anyone's runner required.

## Staging (do not skip ahead)

| Stage | Proof of conformance | Status |
| --- | --- | --- |
| **0 — now** | Three gates green in the adapter's own CI; human security review for Official Verified. | **shipped** |
| **1** | `attestation` record written to the append-only ledger on each green run (unsigned). | design (this doc) |
| **2** | Records **signed** + served by the hosted service; badge links to the verifiable artifact. | roadmap |
| **3** | Consumer-side `nilscript verify-attestation <url>` recomputes `spec_hash` and checks the signature. | roadmap |

## Non-goals / invariants

- Attestation never replaces the gates — it *records* them. A signature over a failing run is still
  a failing run.
- The ledger stays append-only; certificates are never revoked by deletion, only **superseded** by a
  newer record (e.g. `revoked: true`), preserving the audit trail.
- No normative spec change is required to ship any stage — attestation is tooling around the
  standard, not part of it.
