# NIL-MCP Server — design & implementation plan (code-grounded)

> **Status:** Phases 0–3 **shipped in-repo** (2026-06-19); Phase 4 (hosted/remote) planned. · **Date:** 2026-06-19
> **Shipped:** `NilClient.rollback()` (+`ROLLBACK_PATH`) · `[mcp]` extra · `src/nilscript/mcp/`
> (`tools.py` MCP-SDK-free, `server.py` FastMCP wiring, `dynamic.py` skeleton-driven per-verb tools,
> `SKILL.md`) · `nilscript mcp` CLI subcommand (`--gate`, `--transport`, `--no-dynamic-tools`) ·
> tests: `test_mcp_tools.py` (8) + `test_mcp_dynamic.py` (4) + `test_mcp_e2e.py` (1 real-stdio).
> **Full suite green at 195.**
> **Premise:** Ship a single, generic **NIL-MCP server** inside the `nilscript` package so *any
> MCP-compatible agent* can connect once and drive *any* NIL adapter through governed
> propose→approve→commit→rollback — with the **skeleton itself as the tool surface**.
> **Grounded in:** `src/nilscript/sdk/{client,connect,transport,grants,bootstrap,sentences,refusals}.py`,
> `src/nilscript/cli/__init__.py`, `src/nilscript/demo/agent_demo.py`.
> **Companion docs:** [`nilscript-kernel-extraction-plan.md`](./nilscript-kernel-extraction-plan.md) ·
> [`adapter-ecosystem-strategy.md`](./adapter-ecosystem-strategy.md) · [`../RND-PROPOSAL.md`](../RND-PROPOSAL.md) (folds into **WP1**)

---

## 0. The decision (the razor)

NILScript ships **one generic MCP server** (`nilscript mcp`) that exposes the NIL operations to any
MCP-speaking agent. Behind that one front door, the SDK's `NilClient` drives whatever NIL adapter is
wired up. **One MCP front door, any NIL backend behind it** — the OpenAPI-for-agent-actions play.

```
   Agent (Claude/Cursor/…)  ──MCP──▶  nilscript mcp  ──NIL (HTTP)──▶  adapter  ──native──▶  backend
        the agent↔kernel boundary            the kernel↔backend boundary (NilTransport + NilClient)
```

- **MCP** = the contract between the **agent and the kernel**.  **NIL** = the contract between the
  **kernel and the backend** (the adapter speaks NIL over the 6 endpoints + `/describe`).
- **Rejected:** per-backend MCP servers (more surface, fragments the standard, betrays build-once).
- **"Any agent" honestly =** *any **MCP-compatible** agent* **plus** the native Python/HTTP SDK + CLI.

**Crucial framing correction (from the code):** the headless runtime is **already built**. The
`nilscript mcp` server is **not new infrastructure** — it is a **second front door onto the exact
wiring `nilscript run` already uses** (`GrantRef.from_secret` → `NilTransport` → `NilClient`, see
[`cli/__init__.py:63-73`](../src/nilscript/cli/__init__.py#L63)). `agent_demo.py` is already 90% of
the server logic, minus the MCP transport.

---

## 1. Code investigation — what exists vs. what's missing

### 1.1 Reuse **as-is** (the southbound is done)

| Capability | Symbol (file) | Signature / shape | MCP use |
| --- | --- | --- | --- |
| Propose (no side effect) | `NilClient.propose` (`sdk/client.py:92`) | `propose(verb, args, *, session_id, request_timestamp, trace=None) -> ProposalBody` | `nil_propose` tool |
| Commit (the only write) | `NilClient.commit` (`sdk/client.py:109`) | `commit(proposal_id, *, idempotency_key, ts=None, trace=None) -> StatusBody \| ProposalBody` | `nil_commit` tool |
| Query (live read) | `NilClient.query` (`sdk/client.py:135`) | `query(verb, args=None, *, ts=None, trace=None) -> dict` | `nil_query` tool |
| Status | `NilClient.status` (`sdk/client.py:159`) | `status(proposal_id) -> StatusBody` | `nil_status` tool |
| **Discovery / skeleton** | `handshake` (`sdk/connect.py:18`) | `handshake(transport) -> {reachable, conformant, system, nil, verbs[], targets{name:{exists,fields[]}}, ready[], missing[]}` | `nil_describe` tool **+ the dynamic tool list** |
| Grant + scope | `GrantRef.from_secret`, `scope_allows` (`sdk/grants.py`) | `from_secret(*, grant_id, workspace, secret, scopes: frozenset)`; `scope_allows(scopes, verb) -> bool` | server-side gate (§2) |
| Transport (retry+breaker+bearer) | `NilTransport` (`sdk/transport.py:32`) | `NilTransport(*, base_url, bearer_secret, breaker=…)` | one per server process |
| Env wiring + https guard | `client_from_env`, `grant_from_env`, `require_https` (`sdk/bootstrap.py`) | reads `NIL_BASE_URL / NIL_GRANT_ID / NIL_WORKSPACE / NIL_GRANT_SECRET / NIL_GRANT_SCOPES`; `NIL_ALLOW_INSECURE=1` for http | build the client in `_cmd_mcp` |
| Deterministic idempotency key | `nil_uuid` (`sdk/idempotency.py`) | `nil_uuid(session_id, ts_key, index) -> str` | mint commit key, replay-safe |
| Verb profiles = tool schemas | pattern in `demo/agent_demo.py:36` `load_verb_tools()` | reads `nilscript.sdk.spec/0.1/profiles/<family>-v1/*.json` → `{verb: jsonschema}` | dynamic per-verb tool `inputSchema` |
| Models | `sdk/sentences.py` | `ProposalBody{outcome, id, verb, tier, preview{locale:str}, resolved, modifiable, expires_at, code, message, field, candidates}`, `StatusBody{proposal, state, replayed, compensation, result}`, `Reversibility`, `RollbackReason`, `RollbackBody`, `Compensation` | tool returns + refusal mapping |
| Refusal codes | `RefusalCode` (`sdk/refusals.py`) | incl. `UNKNOWN_VERB`, `UPSTREAM_UNAVAILABLE`, `IRREVERSIBLE`, `COMPENSATION_EXPIRED`; `RETRIABLE_REFUSALS` | structured tool error |

### 1.2 The **one gap** — `NilClient.rollback()` does not exist

`grep` confirms: `Performative.ROLLBACK`, `RollbackBody`, `RollbackReason`, the `/nil/v0.1/rollback`
endpoint, the OpenAPI entry, the scaffold handler, and the conformance probe all exist — but
**`NilClient` has only `propose/commit/query/status`** (`sdk/client.py`). The `nil_rollback` tool
therefore needs a new client method. It mirrors `propose` exactly (ROLLBACK is answered by a
`PROPOSAL` compensation preview, then COMMITted):

```python
# sdk/client.py — NEW, add ROLLBACK_PATH = "/nil/v0.1/rollback"
async def rollback(
    self, compensation_token: str, reason: RollbackReason,
    *, idempotency_key: str | None = None, ts: datetime | None = None, trace: str | None = None,
) -> ProposalBody:
    """Request a governed reversal. Answered by a PROPOSAL (compensation preview); the
    caller then COMMITs it via the existing commit()."""
    envelope = make_envelope(
        Performative.ROLLBACK,
        RollbackBody(compensation_token=compensation_token, reason=reason,
                     idempotency_key=idempotency_key),
        sentence_id=idempotency_key or self._id_factory(),
        grant=self._grant.grant_id, workspace=self._grant.workspace,
        ts=ts if ts is not None else _utcnow(), trace=trace,
    )
    answer = await self._transport.post_sentence(ROLLBACK_PATH, envelope.to_wire())
    return self._parse_proposal(answer)
```

This is a **small, self-contained SDK addition** (≈15 lines + a test), and it also pays off the
saga-unwind path generally — not just the MCP server. **It is a prerequisite for the `nil_rollback`
tool and should land first.** *(Verify the kernel's `LocalExecutor` compensation path: if it posts
rollback inline, route it through the new method too — single source.)*

### 1.3 CLI wiring pattern (mirror `run`/`demo`)

Subcommands are `sub.add_parser(name, help=…)` + `.add_argument(…)` + `.set_defaults(func=_cmd_x)`;
`main()` dispatches `args.func(args)` (`cli/__init__.py:410-496`). `_cmd_demo` (`:382`) shows the
**lazy-import-the-extra** pattern (`import uvicorn` → `ModuleNotFoundError` → print install hint,
`return 2`). `_cmd_run` (`:63-73`) shows the **client wiring** to copy verbatim. `nilscript mcp`
slots in as a sibling using both patterns.

---

## 2. Tool surface — the skeleton *is* the tool list

`handshake()` returns the backend's `verbs[]` and `targets{}`; the server registers tools from that,
so **an agent can never be presented a verb the backend doesn't declare** (the proposal's §4.5
"skeleton-bounded" guarantee, pushed up into the MCP menu itself).

**A. Generic primitives** (always present):

| MCP tool | SDK call | Side effect | Returns |
| --- | --- | --- | --- |
| `nil_describe` | `handshake(transport)` | none | skeleton `{system, nil, verbs, targets, ready, missing}` |
| `nil_propose(verb, args)` | `client.propose(...)` | **none** | preview: `{outcome, id, verb, tier, preview, expires_at}` or refusal `{code, message, field}` |
| `nil_commit(proposal_id)` | `client.commit(proposal_id, idempotency_key=…)` | **yes** | `{state, replayed, result, compensation}` from `StatusBody` |
| `nil_query(verb, args)` | `client.query(...)` | none | `dict` (live data) |
| `nil_status(proposal_id)` | `client.status(...)` | none | `StatusBody` |
| `nil_rollback(compensation_token, reason)` | `client.rollback(...)` **(§1.2 new)** | none | compensation preview `ProposalBody` → then `nil_commit` |

**B. Dynamic per-verb propose tools** — generated at connect time from the profiles
(`load_verb_tools()` pattern) **filtered to `handshake().verbs`**: e.g.
`propose__commerce_create_product` with `inputSchema` = the verb's profile JSON Schema. Each is a
typed shortcut to `nil_propose`; it still returns a preview and still requires `nil_commit`.

**The two-step is preserved by construction:** `propose` is side-effect-free *in the SDK already*
(`client.py` only writes in `commit`). So no MCP tool can mutate except `nil_commit`. The server holds
a small in-memory map `proposal_id → {verb, session_id, ts_key, index}` so `nil_commit` can mint the
**deterministic** key `nil_uuid(session_id, ts_key, index)` — identical to `agent_demo.py:131` — making
re-commit replay-safe rather than double-writing.

---

## 3. How approval maps onto MCP (gate modes)

Gate = the separation of `propose` from `commit`; it survives any client. CLI flag `--gate`:

| Mode | Behaviour | Implementation |
| --- | --- | --- |
| `two-step` (default) | `nil_propose` returns a preview; agent must call `nil_commit`. Most MCP clients render the tool call for human confirmation. | nothing extra — it's the SDK's natural shape |
| `human` | `nil_commit` blocks on an out-of-band approval for `HIGH`/`COMPENSABLE`/`IRREVERSIBLE` tiers (read `ProposalBody.tier`); cheap tiers pass. | reuse `agent_demo.human_confirms` policy (`:74`); approval source = stdin / hosted endpoint |
| `auto` | auto-commit only when `scope_allows(grant.scopes, verb)` **and** the proposal is `REVERSIBLE`. Never `IRREVERSIBLE`. | `scope_allows` + `ProposalBody`/profile reversibility |

Authority reuses the **grant** (`scopes`, and the proposal's `tier`) — no new credential system. The
server is the trust boundary that **holds the bearer secret** (via `--grant-secret-env`, never a raw
arg); the agent never sees backend credentials. `require_https` (`bootstrap.py:28`) already blocks a
cleartext base URL unless `NIL_ALLOW_INSECURE=1`.

---

## 4. Packaging & layout

- **New extra** in `pyproject.toml`: `mcp = ["nilscript[sdk]", "mcp>=1.0"]` (the MCP Python SDK).
  Keeps the base package dependency-free, consistent with `[sdk]/[cli]/[demo]`.
- **New module** `src/nilscript/mcp/`:
  - `server.py` — builds `NilTransport`+`NilClient` (copy `_cmd_run:63-73`), registers tools, runs the MCP server (stdio).
  - `tools.py` — the six generic primitives (§2.A) as thin wrappers over `NilClient` + `handshake`.
  - `dynamic.py` — `handshake().verbs` ∩ `load_verb_tools()` → per-verb tools (§2.B); profile→`inputSchema`.
  - `gate.py` — the three modes (§3); reuses `scope_allows`.
  - `state.py` — the `proposal_id → {session_id, ts_key, index}` map for deterministic commit keys.
- **CLI subcommand** `_cmd_mcp` in `cli/__init__.py` (mirror `_cmd_demo`'s lazy import + `_cmd_run`'s args):
  ```bash
  nilscript mcp --adapter-url http://localhost:8080 \
    --grant-id <id> --workspace <ws> --grant-secret-env NIL_GRANT_SECRET \
    --scope 'commerce.*' --scope 'resource.*' \
    --gate two-step --transport stdio
  ```
- **Transport:** **stdio first** (Claude Desktop, Cursor, local IDE clients); HTTP/SSE later (§6, → cloud).

---

## 5. Ship the skill with the server (recipe + kitchen)

MCP gives *capability*, not *discipline*. Ship a **`SKILL.md`** ("Using NILScript") alongside:
propose→approve→commit→rollback; never `nil_commit` without a preview; the three reversibility tiers;
how to read a structured refusal (`UNKNOWN_VERB`/`UPSTREAM_UNAVAILABLE`/`IRREVERSIBLE`/
`COMPENSATION_EXPIRED`) and **not retry a poisoned action**; when to escalate to a human. The gate
enforces safety with or without it — the skill makes the agent *use* NIL correctly out of the box.

---

## 6. Phased execution (file-level)

### Phase 0 — Prerequisite SDK addition ✅ shipped
- [x] `NilClient.rollback()` + `ROLLBACK_PATH` (§1.2) + 2 unit tests (respx). *(Kernel compensation posts via PROPOSE→COMMIT, not `/rollback`, so no rerouting needed — the new method is purely additive.)*
- [x] `[mcp]` extra in `pyproject.toml` (`mcp>=1.2`, also added to `[dev]`).

### Phase 1 — Generic server MVP (stdio, two-step) ✅ shipped
- [x] `nilscript/mcp/{__init__,tools,server}.py`; `_cmd_mcp` + parser in `cli/__init__.py` (lazy `import mcp`, `rc=2` install hint on missing extra).
- [x] Client wired as `_cmd_run`; `nil_describe` via `handshake`; all six primitives registered on FastMCP (verified: `nil_{describe,propose,commit,query,status,rollback}`).
- [x] Deterministic commit key via `commit_idempotency_key(session, proposal_id)`; tier remembered at PROPOSE for the `human` gate. *(No separate `state.py` needed — the key derives from the proposal id; tier memory lives in `NilTools`.)*
- [x] `tools.py` is MCP-SDK-free (asserted in test) so tool logic is provable with `respx` alone.
- [x] **DoD ✅** — `tests/test_mcp_e2e.py`: a real `mcp` `ClientSession` over **stdio** spawns `nilscript mcp`, which drives the vendored PocketBase adapter on its in-memory `FakeSystem` (no live backend) through `nil_describe → nil_propose → nil_commit → nil_rollback`. Asserts: skeleton reachable+conformant, proposal preview, `committed=executed` with a compensation token, and `nil_rollback` previews `commerce.delete_product` (never a silent write). **Suite green at 191.**

### Phase 2 — Skeleton-as-tools + gates ✅ shipped
- [x] `dynamic.py`: one `propose_<verb>` tool per `handshake().verbs`, descriptions carry the profile's required/optional args. Discovery uses a throwaway transport at startup (no cross-event-loop httpx reuse); `--no-dynamic-tools` opts out. *(FastMCP derives `inputSchema` from the fn signature, so per-verb tools take `args: dict` with the profile fields surfaced in the description; an explicit per-verb JSON-Schema via the low-level `Server` API is a further refinement.)*
- [x] Gate: `human` (tier-gated block on the remembered `ProposalBody.tier`) shipped in `tools.py`; `two-step`/`auto` permit commit. *(No separate `gate.py` — the logic is small and lives in `NilTools`.)*

### Phase 3 — Skill + conformance + docs (partial)
- [x] Ship `SKILL.md` ("using-nilscript") inside the package (`src/nilscript/mcp/SKILL.md`, in wheel `package-data`).
- [x] **Conformance covered by tests:** `test_mcp_tools.py` (no side effect on propose; refusal-as-value; idempotent commit via deterministic key; `human` gate holds HIGH tier) + `test_mcp_dynamic.py` (a verb absent from the skeleton is **not registered**) + `test_mcp_e2e.py` (real stdio round-trip).
- [ ] README + protocol-site page: the one-line connect demo (§7).

### Phase 4 — Hosted/remote (optional, later)
- [ ] HTTP/SSE transport + auth + multi-tenant grants → folds into **Wosool Cloud** (proposal WP5), not the local kernel.

---

## 7. Why this is the WP1 adoption headline

The runtime already runs; the MCP server is the *thin, high-leverage* layer that makes it
plug-and-play and delivers the proposal's **<60-second loop**:

```bash
pip install "nilscript[mcp]"
export NIL_GRANT_SECRET=…           # the bearer; the server holds it, the agent never sees it
nilscript mcp --adapter-url <your-NIL-adapter>     # point Claude/Cursor at it
# → the agent connects and physically cannot make an unauthorized write
```

*"Connect your agent in one line and it physically can't make an unauthorized write"* beats any
benchmark table as a demo. **The chart (WP2) proves it; the one-line MCP connect sells it.**

---

## 8. Risks & caveats

| # | Risk | Mitigation |
| --- | --- | --- |
| 1 | **"Any agent" overclaim** | "any MCP-compatible agent + native SDK"; never bare "any agent." |
| 2 | **MCP carries capability, not discipline** | ship `SKILL.md` (§5); gate enforces safety regardless. |
| 3 | **`nil_commit` without tracking → wrong idempotency key** | `state.py` maps `proposal_id → session/ts/index`; mint via `nil_uuid` (replay-safe). |
| 4 | **Grant secret exposure** | server holds the secret via `--grant-secret-env`; `require_https` blocks cleartext. |
| 5 | **Dynamic tool list drift** | regenerate from live `handshake()` on connect; a stale verb fails skeleton check → refused. |
| 6 | **MCP SDK churn** | keep the server a thin proxy over `NilClient`; pin the SDK version. |

---

## 9. Open decisions (for sign-off)

1. **Transport default** — stdio now, HTTP/SSE later? *(Recommended: stdio first.)*
2. **Dynamic tools in Phase 1 or 2?** *(Recommended: generic primitives Phase 1, dynamic Phase 2.)*
3. **Skill home** — in-repo `SKILL.md` vs standalone drop? *(Recommended: in-repo first.)*
4. **Default gate** — `two-step` vs `human`? *(Recommended: `two-step` for the <60s demo.)*

---

*This is a plan, not an implementation. It folds into RND-PROPOSAL WP1. The runtime kernel
(`nilscript.kernel` + `nilscript run`) already exists; the only new southbound code this needs is
`NilClient.rollback()` (§1.2). Nothing is built or published from this document without sign-off.*
