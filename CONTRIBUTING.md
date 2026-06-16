# Contributing to NIL

> **Building an adapter** (making a backend speak NIL) is a different, lighter path that changes no
> normative text — see [docs/contributing-an-adapter.md](docs/contributing-an-adapter.md). The rules
> below govern changes to the **standard itself**.

- Discuss in an issue before normative PRs. Use the `proposal` template.
- Normative language uses RFC 2119 keywords; everything else is informative and marked so.
- Every normative proposal MUST include a §15 (Security considerations) analysis. "It's
  convenient" is not a security analysis.
- Implementation experience in the reference implementation is required before merge
  (GOVERNANCE §Change process).
- Examples and schemas are code: they run in CI (schema validation + example conformance).
- Editorial fixes: PR directly, label `editorial`.
- Be specific, be kind, assume good faith. (CODE_OF_CONDUCT.md applies.)
