# Security Policy

## Reporting a vulnerability
Email **security@nilscript.org** (subject prefix `[NIL]`). Do not open public issues for
security reports. We follow **90-day coordinated disclosure** (GOVERNANCE.md): acknowledge
within 72h, status updates at least every 14 days, credit to reporters on release.

In scope: the specification's normative guarantees (a way for a Speaker to reach DECIDE, to
lower a floor, to bypass budgets/idempotency, to execute without a valid sentence, or to
poison resolution/preview rendering) and the published schemas/bindings.

Out of scope here: operational vulnerabilities of specific implementations — report those to
the implementation's own security contact (IMPLEMENTATIONS.md).

## Design-level analysis
Every normative change requires a §15 security analysis before merge (CONTRIBUTING.md).
