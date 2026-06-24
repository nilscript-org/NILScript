# Refusal codes → recommended client/agent recovery

NIL refusals are **outcomes, not errors.** A refusal is the System answering honestly that
it will not (or cannot) commit an effect — read it and act deterministically. The canonical
codes are defined in `src/nilscript/sdk/refusals.py` (Annex A). This table is the recovery
reference for adapter and agent authors.

**Only two codes are retriable:** `RETRIABLE_REFUSALS = {RATE_LIMITED, UPSTREAM_UNAVAILABLE}`.
Everything else is a *decision*, not a transient — retrying it blindly is a bug.

| Code | Retriable | What it means | Recommended client/agent action |
|------|-----------|---------------|----------------------------------|
| `MALFORMED` | No | The proposal isn't a well-formed NIL message. | Fix the message shape; do not retry the same bytes. Re-encode against the contract. |
| `UNKNOWN_PERFORMATIVE` | No | The performative (e.g. propose/commit/query) isn't one the System speaks. | Use a valid performative; check the SDK / `nil_describe`. Don't retry. |
| `UNKNOWN_VERB` | No | The backend doesn't expose this verb. | Call `nil_describe` and pick a real verb. Don't invent verbs, don't retry. |
| `SCOPE_DENIED` | No | The caller's grant doesn't cover this verb/target. | Stop. Request the scope out-of-band; never retry into a denied scope. |
| `CAPABILITY_DENIED` | No | The capability needed for this effect isn't held. | Stop. Acquire the capability through the proper channel; don't retry. |
| `POLICY_DENIED` | No | A policy rule forbids this effect. | Treat as a hard no. Surface the reason; don't retry or reshape to evade. |
| `INVALID_ARGS` | No | Arguments fail validation (type/shape/constraint). | Correct the arguments per the schema, then propose again. |
| `UNRESOLVED` | No | A referenced field/target couldn't be resolved to a real entity. | Resolve the reference (look it up / `nil_query`), then re-propose with a concrete target. |
| `AMBIGUOUS` | No | The reference matched multiple candidates. | Pick one of the returned candidates and re-propose with the disambiguated target. |
| `BUDGET_EXHAUSTED` | No | The action budget for this session/grant is spent. | Stop. Don't retry; budget won't replenish by retrying. Request more budget if appropriate. |
| `QUOTA_EXHAUSTED` | No | A quota (per resource/period) is exhausted. | Stop and wait for the quota window to reset; do not hammer. Not a backoff-retry. |
| `SUSPENDED` | No | The grant/session is suspended. | Stop entirely. Resolve the suspension out-of-band before any further proposals. |
| `EXPIRED` | No | The grant/session/token has expired. | Re-authenticate / obtain a fresh grant, then start over. Don't retry the old one. |
| `RATE_LIMITED` | **Yes** | Too many requests in the window. | Retriable: honor any retry hint, back off (exponential + jitter), then retry. |
| `UPSTREAM_UNAVAILABLE` | **Yes** | The backend the adapter fronts is temporarily down/unreachable. | Retriable: back off and retry; escalate to a human if it persists. |
| `IRREVERSIBLE` | No | The committed effect has no compensation — it cannot be reversed. | Do not attempt rollback. Record it; recover forward, not backward. |
| `COMPENSATION_EXPIRED` | No | A reversal was possible but its compensation window has closed. | Don't retry the rollback. Recover forward or escalate; the undo path is gone. |
| `PRECONDITION_FAILED` | No | State drifted between propose and commit (TOCTOU); the bound preview no longer matches reality. | Re-propose to get a fresh preview, re-approve, then commit. **Never blind-retry the stale commit.** |

## Rules of thumb

- **Retriable means exactly two codes.** If it isn't `RATE_LIMITED` or
  `UPSTREAM_UNAVAILABLE`, retrying the identical request will get the identical refusal.
- **Don't reshape to evade a deny.** `SCOPE_DENIED` / `CAPABILITY_DENIED` / `POLICY_DENIED`
  are governance decisions; fix the grant, not the payload.
- **Drift means re-propose, not re-commit.** `PRECONDITION_FAILED` exists precisely so the
  kernel fails closed instead of writing against stale reality. Go back to `propose`.
- **Honest irreversibility.** `IRREVERSIBLE` / `COMPENSATION_EXPIRED` mean the System
  refuses to *pretend* it can undo what it cannot. Recover forward.
