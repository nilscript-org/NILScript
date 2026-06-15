# Vendored NIL schemas

Source: nilscript repo, version **0.2.0-draft (2026-06-15)** (was 0.1.0-draft rev 4).
Copied verbatim from `nilscript/schemas/`. Do not edit here — update from the spec.

**0.2.0 re-vendor (structural alignment, see `nilscript/versions/0.2.0.md`):** added
`profiles/commerce-v1/record_fulfillment.json` + `record_payment.json`; updated
`process_refund.json` (→ `refund_target`), `create_product.json` (→ `variants[]` oneOf),
`update_order_status.json` (deprecated); added `query-answer.schema.json` (typed QUERY response
envelope) and `profiles/services-v1/list_clients.json` + `list_clients.response.json`. Schema
`$id`s keep the `…/0.1/…` namespace segment by design (the release is tracked in `versions/`).

`decide.owner-plane.schema.json` is deliberately NOT vendored: DECIDE is owner-plane
and must never be defined or parsed in this repository (01 rule 4, blueprint 1.1).
