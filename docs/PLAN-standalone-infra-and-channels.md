# PLAN — NIL Standalone Infra + Customer Channels (WhatsApp & Email)

**Status:** PLAN ONLY — no execution until approved.
**Date:** 2026-06-30
**Author:** handoff for next session
**Trigger:** Keycloak/os-server port-8090 war (symptom of NIL still living inside the
deprecated `wosool-saas` Docker Compose project) + user directive to migrate NIL off
wosool-saas and to connect WhatsApp (Evolution) and customer Email.

---

## 0. Why now

NIL is operational but **entangled** with the deprecated `wosool-saas` compose project.
Today's incident: recreating Keycloak collided on host port `8090` with the
host-networked `os-server` (uvicorn). Root cause = shared infra owned by the old
product. Until NIL owns its own infra, every restart risks the live login/edge.

This plan makes NIL **self-contained** so `wosool-saas` (the old Salla product) can be
deleted entirely, AND wires the two customer channels the product needs: **WhatsApp**
(via Evolution API, already half-present) and **Email** (relay already present, not yet
wired).

---

## 1. Current dependency map (grounded, 2026-06-30)

### NIL's own containers
| Container | Compose project | Networks |
|---|---|---|
| `nil-hub` | nil-os | wosool-saas_wosool-network |
| `nil-brain`, `nil-daemon` | nil-os | nilscript-net + wosool-saas_wosool-network |
| `os-server` | nil-os | **host network** (binds host :8090) |
| `nilscript-controlplane`, `nilscript-mcp`, `nilscript-web`, `nilscript-playground`, `nilscript-gateway` | nilscript-landing | both nets |
| `hermes`, `hermes-oauth2-proxy`, `hub-oauth2-proxy` | **manual `docker run`** (no compose) | both nets |

### Infra NIL borrows from `wosool-saas` (must be migrated or re-owned)
| Service | Why NIL needs it | Source |
|---|---|---|
| **Keycloak** (+`keycloak-db` Postgres) | Auth for app/os/hub/mcp; realm `wosool`, theme `wosool`, reconcile script | `wosool-saas/docker-compose.prod.yml` + `scripts/keycloak_*.sh` + `keycloak/realms/` + `packages/keycloak-theme/` |
| **Caddy** | Edge TLS + routing + `forward_auth` for all `*.wosool.ai` | `wosool-saas/Caddyfile` |
| **Redis** (`nilscript-redis`) | oauth2-proxy sessions / caches | `wosool-saas/docker-compose.prod.yml` |
| **Temporal** stack (server, postgres, ui, admin, schema, es, oauth2-proxy) | NIL durable layer (Phase 6 worker integration) | `wosool-saas/docker-compose.temporal.yml` |
| **Evolution API** (+`evolution-db`) | WhatsApp channel (server currently DOWN) | `wosool-saas/docker-compose.prod.yml` |
| **Network** `wosool-saas_wosool-network` | shared bridge all NIL containers attach to (declared `external` in nil-os) | — |

### Dead weight (old product — NIL does NOT need; delete after migration)
`backend`, `frontend`, `orchestrator`, `landing`, `mongo` (+init-rs, express, backup),
`minio`, `telegram-bot`, `langfuse`(+db), `rag-api`, `chromadb`(+backup),
monitoring (`prometheus`, `alertmanager`, `grafana`(+oauth2-proxy), `tempo`,
`node-exporter`), `autoheal`.

> Note: confirm nothing NIL uses `minio`/`chromadb`/`rag-api` before deleting — the
> brain may use chromadb for embeddings. **Verification step in Phase 0.**

---

## 2. Target architecture

A single new compose project **`nil-infra`** (dir `/root/nil-infra/`) that OWNS:

```
nil-infra/
  docker-compose.infra.yml      # caddy, keycloak(+db), redis, evolution(+db)
  docker-compose.temporal.yml   # temporal stack (moved verbatim from wosool-saas)
  Caddyfile                      # NIL routes only (auth/app/os/hub/mcp/ask + evolution webhooks)
  keycloak/realms/wosool-realm.json
  keycloak/theme/wosool/...       # the SaaS-grade login/register theme
  scripts/keycloak_entrypoint.sh, keycloak_reconcile.sh
  .env.infra                      # all secrets (migrated from .env.production, trimmed)
  networks: nil-net (external false; the ONE shared bridge)
```

Then `nil-os` and `nilscript-landing` compose files point at **`nil-net`** instead of
`wosool-saas_wosool-network`. The manual `docker run` services (hermes*, hub-oauth2-proxy)
get reproducible recreate scripts (hub-oauth2-proxy already has `/root/redeploy-hub-proxy.sh`).

**Network strategy:** create `nil-net` as a standalone external bridge. Migrate every NIL
container onto it. Keep `wosool-saas_wosool-network` alive ONLY during cutover; remove once
nothing references it.

**os-server host-networking:** keep host-net (it owns :8090) — Keycloak now on :8095, so no
more collision. Long term, consider moving os-server onto `nil-net` with a normal port to
remove the host-net special case (optional, lower priority).

---

## 3. Migration phases (each independently revertible)

### Phase 0 — Safety + verification (no changes)
- `docker commit` / volume backups of: keycloak-db, evolution-db, temporal-postgres, redis (if persisted), os_server.db, the NIL data volume.
- Snapshot all compose files + `.env.production` + Caddyfile + manual `docker run` configs.
- **Verify** whether brain/daemon use `chromadb`/`minio`/`rag-api` (grep configs + live netstat). Decide keep/drop.
- Document every `*.wosool.ai` route currently served by Caddy.

### Phase 1 — Stand up `nil-infra` alongside (no cutover)
- Create `/root/nil-infra/` with trimmed compose containing ONLY NIL-needed services, pointing at the SAME named volumes (so no data copy) and a NEW `nil-net`.
- Bring up `nil-infra` Keycloak/Redis on alternate internal aliases to validate boot against existing DBs (read-only smoke test) WITHOUT taking over routing.

### Phase 2 — Network cutover
- Attach all NIL containers to `nil-net` (additive: `docker network connect`).
- Update `nil-os` + `nilscript-landing` compose to declare `nil-net` external and recreate.
- Keep both nets attached transitionally.

### Phase 3 — Edge cutover (Caddy)
- New `nil-infra/Caddyfile` with ONLY NIL routes. Validate config (`caddy validate`).
- Stop wosool-saas Caddy; start nil-infra Caddy bound to :80/:443. TLS certs: reuse the
  existing cert volume or let Caddy re-issue (DNS already points at the host).
- **Rollback:** restart wosool-saas Caddy.

### Phase 4 — Keycloak + Temporal + Evolution ownership
- Recreate Keycloak under nil-infra (same DB volume, realm, theme). Verify login/register.
- Move temporal compose into nil-infra unchanged; verify NIL worker still connects.
- Bring Evolution API up under nil-infra (see §4).

### Phase 5 — Decommission wosool-saas
- `docker compose -p wosool-saas down` for the DEAD services only (keep nothing).
- Remove `wosool-saas_wosool-network` once unreferenced.
- Archive `/root/wosool-saas` (don't delete immediately — keep 1–2 weeks).

### Rollback posture
Every phase is additive or has an explicit revert (restart the wosool-saas counterpart).
No data volume is moved — only re-pointed — so a bad cutover is a network/edge revert, not
a data restore.

---

## 4. WhatsApp channel (Evolution API — open-source, already on the box)

**Decision (open-source only):** Use the **existing Evolution API v2.3.7 + Baileys** as THE
WhatsApp channel. Bring its container back up (only `evolution-db` runs today). Official
WhatsApp Cloud API / Meta / paid BSPs are **out of scope** (paid) — note them only as a
future "if we ever need official compliance" escape hatch, never the plan.

> Other OSS options considered (WAHA, whatsapp-web.js, Baileys-direct) — Evolution wins
> because it's already deployed, has a built-in multi-tenant instance model, Postgres+Redis
> session persistence, and a per-instance webhook system. Same Baileys engine underneath.

### 4.1 Multi-tenancy model (the isolation spine)
- **Instance = number = tenant.** Name deterministically `wa-<workspaceId>` (never by phone).
- **Two-tier auth:**
  - `EVOLUTION_GLOBAL_API_KEY` — backend/control-plane only; **never** to a tenant or browser.
  - Per-instance `hash` token — minted at instance creation, stored **encrypted in the
    per-tenant vault**, used for that tenant's ops.
- **Per-instance webhook** → `https://wa.wosool.ai/api/whatsapp/webhook/<workspaceId>` with a
  per-tenant bearer/HMAC. Handler MUST: verify token → assert payload `instance == workspace`
  → enqueue onto that tenant's durable lane (don't call Hermes synchronously — Baileys bursts).
- **Persistence:** `DATABASE_SAVE_DATA_INSTANCE=true` + `CACHE_REDIS_ENABLED=true` +
  `CACHE_REDIS_SAVE_INSTANCES=true` → instances reconnect after restart **without re-scanning
  QR**. Back up `evolution-db` + the `/evolution/instances` volume nightly (losing either =
  mass re-scan outage).
- **Scale on one host:** plan **low tens of instances/box** (each = live WebSocket + crypto
  state); shard later via `DATABASE_CONNECTION_CLIENT_NAME`. Rate-guard ~100 req/min/tenant.

### 4.2 Sharp edges (confirmed — design around these)
- **`/message/sendStatus` hangs forever on v2.3.7** ([#2377], closed "not planned") → **do NOT
  build any WhatsApp Status/broadcast feature on Evolution.** Avoid the endpoint entirely.
- **Pairing-code login delivers no webhook events** ([#2215]) → **QR-onboard only, never
  pairing code.**
- **Baileys forced-logout on cred reuse** ([Baileys #2110]) → treat reconnect failures as
  expected; ship a one-click re-pair flow.
- **Connection states:** auto-reconnect on transient `408/428/500`; on `401`/`403`/`406`
  (logged out / banned / invalid) do NOT auto-reconnect — surface "reconnect your WhatsApp" in
  the dashboard. QR expires ~45s; set `QRCODE_LIMIT=30`, stream `qrcode.updated` to the UI.
- **Ban risk** is real for any unofficial client — position WhatsApp as **inbound/support-
  oriented**, cap outbound, never bulk/market on it.

### 4.3 Per-tenant onboarding (QR)
1. Tenant clicks "Connect WhatsApp" → control-plane (global key) `POST /instance/create`
   `instanceName=wa-<workspaceId>`; capture `hash`, store encrypted.
2. Set instance webhook → `…/webhook/<workspaceId>` + per-tenant token.
3. Stream `qrcode.updated` to UI; tenant scans (WhatsApp → Linked Devices).
4. On `connection.update: open` → `whatsapp_status=connected`. PG+Redis persist sessions.

### 4.4 Channel Adapter (anti-corruption layer)
Define ONE canonical `InboundMessage`/`OutboundMessage` contract. Evolution feeds into it;
Hermes never knows the transport. This is the single choke point that enforces
`instance↔workspace` isolation AND lets us swap to Cloud API later by flipping a
`channel_provider` flag — zero agent-logic change.

### 4.5 Key env
```
EVOLUTION_GLOBAL_API_KEY=<vault, backend-only>
DATABASE_SAVE_DATA_INSTANCE=true
CACHE_REDIS_ENABLED=true
CACHE_REDIS_SAVE_INSTANCES=true
QRCODE_LIMIT=30
WEBHOOK_EVENTS_CONNECTION_UPDATE=true
WEBHOOK_EVENTS_QRCODE_UPDATED=true
WEBHOOK_EVENTS_MESSAGES_UPSERT=true
```

**Sources:** [Evolution multi-tenant](https://evolutionapi-evolution-api-90.mintlify.app/concepts/multi-tenant) ·
[Connections](https://mintlify.wiki/EvolutionAPI/evolution-api/whatsapp/connections) ·
[#2377 sendStatus](https://github.com/EvolutionAPI/evolution-api/issues/2377) ·
[#2215 pairing-code](https://github.com/EvolutionAPI/evolution-api/issues/2215) ·
[Baileys #2110](https://github.com/WhiskeySockets/Baileys/issues/2110)

---

## 5. Email channel (transactional + customer mailboxes)

Three distinct needs — keep them separate:

| Need | Tool | Notes |
|---|---|---|
| **Keycloak** verify/reset emails | Keycloak's own SMTP → mail.wosool.ai | unblocks proper signup; lets us drop the unverified-email hack |
| **App/tenant emails** from os-server (FastAPI) | **`fastapi-mail`** (sabuhish/fastapi-mail) | user's pick; async, Jinja templates, BackgroundTasks |
| **Reading customer mail** (agent read→reply) | **Gmail/M365 OAuth** (IMAP fallback) | send-only tools can't do this |

### 5.1 Wire Keycloak 24 → mail.wosool.ai (587 STARTTLS)
```bash
kcadm.sh update realms/wosool \
  -s 'smtpServer.host=mail.wosool.ai' -s 'smtpServer.port=587' \
  -s 'smtpServer.from=no-reply@wosool.ai' -s 'smtpServer.fromDisplayName=Wosool' \
  -s 'smtpServer.replyTo=support@wosool.ai' \
  -s 'smtpServer.starttls=true' -s 'smtpServer.ssl=false' \
  -s 'smtpServer.auth=true' -s 'smtpServer.user=no-reply@wosool.ai' \
  -s "smtpServer.password=$SMTP_PASSWORD"
```
`starttls=true` + `ssl=false` for 587 (never both). Inject password at runtime — never in a
realm export. Use Realm Settings → Email → "Test connection" to confirm.

### 5.2 Deliverability — 4 musts (verify each)
- **SPF**: `wosool.ai TXT "v=spf1 mx a:mail.wosool.ai -all"` → `dig +short TXT wosool.ai`
- **DKIM**: selector e.g. `s1`, publish `s1._domainkey.wosool.ai` → `dig +short TXT s1._domainkey.wosool.ai`; confirm at mail-tester.com
- **DMARC**: `_dmarc.wosool.ai TXT "v=DMARC1; p=none; rua=mailto:dmarc@wosool.ai"` → ramp none→quarantine→reject (Gmail/Yahoo bulk rules now enforced)
- **PTR/rDNS**: Hetzner reverse DNS for sending IP → `mail.wosool.ai`, forward-match → `dig -x <ip>`
- Cross-check: MXToolbox + Google Postmaster Tools. Add List-Unsubscribe.

### 5.3 Stay self-hosted (open-source only — no paid relays)
Keep using the existing self-hosted **`mail.wosool.ai`** relay for ALL transactional +
app email. No SES/Postmark/Resend (paid). The cost of self-hosting is **deliverability
discipline**, not money — so §5.2 (SPF/DKIM/DMARC/PTR) is **mandatory**, not optional:
verify 10/10 on mail-tester.com and watch Google Postmaster spam-rate `< 0.1%`.

If the relay host (`mail.wosool.ai`) ever needs replacing/hardening, the OSS pick is
**Stalwart** (single Rust binary: SMTP/IMAP/JMAP, 512MB, REST admin) — bookmark it; don't
migrate unless forced. Everything below uses OSS Python libs only.

### 5.4 `fastapi-mail` in os-server — gotchas
`ConnectionConfig(MAIL_SERVER=mail.wosool.ai, MAIL_PORT=587, MAIL_STARTTLS=True,
MAIL_SSL_TLS=False, MAIL_USERNAME=no-reply@wosool.ai, USE_CREDENTIALS=True)`.
- **No connection pool** — opens a connection per send; batch/queue bursts, don't fan out
  hundreds per request.
- Always send via `BackgroundTasks` (or Temporal) so SMTP latency never blocks the response.
- Templates in `TEMPLATE_FOLDER`, pass `template_name`.
- Coexists cleanly with Keycloak (independent SMTP clients, same relay; both auth as
  `no-reply@wosool.ai` so SPF/DKIM cover the From).
- **SEND-ONLY** — cannot read mailboxes (see 5.5).

### 5.5 Per-tenant customer-mailbox connect (OSS libs only)

App-passwords are **dead** for the big two (Google removed "less secure apps"; MS killed
Basic Auth, SMTP-AUTH retiring 2026). So **OAuth-direct** with open-source Python libs —
no paid email-API SaaS (EmailEngine/Nylas excluded: commercial). Build order by friction:

**Tier 1 — Microsoft 365 / Outlook → Graph OAuth (delegated). EASIEST, no audit.**
Multitenant Entra app, scopes `Mail.Read` + `Mail.Send` + `offline_access` (+`User.Read`).
Reply via `POST /me/messages/{id}/reply` (Graph sets threading headers for you). One-click
org admin-consent. Lib: **`msgraph-sdk`** + **`authlib`**. Make this the flagship.

**Tier 2 — Gmail / Workspace → split to dodge Google CASA (the key insight):**
- `gmail.send` is **sensitive-only → NO CASA audit**. `gmail.readonly`/`modify` are
  **restricted → CASA** (annual security audit, real cost + 2–6mo). So:
- **Send via Gmail OAuth (`gmail.send`) + RECEIVE via forwarding to our own MX** → avoids
  CASA entirely. Only take on CASA if/when we must API-read Gmail at scale.
- Ramp: ≤100 Gmail tenants on a published-but-unverified app; prefer Workspace **admin
  consent** (one approval per org). Libs: **`google-api-python-client`** + **`authlib`**.

**Tier 3 — Generic hosts (cPanel/Zoho/Fastmail/IONOS/self-hosted) → IMAP/SMTP.**
The legitimate home for app-passwords (or XOAUTH2 where supported). Libs: **`imap-tools`**
(read) + **`aiosmtplib`** (send). Encrypt the password like a refresh token.

**Tier 0 — Universal escape hatch (fully OSS): forward to our self-hosted MX.**
Tenant forwards `support@theirbiz.com` → `tenant<token>@inbound.wosool.ai`; our
`mail.wosool.ai` pipes inbound to a webhook (Postfix transport, or an **`imap-tools`**
poller) → canonical `InboundMessage`. **No paid inbound-parse SaaS** (SendGrid/Mailgun/
Postmark all paid). Sidesteps CASA + admin-consent for any tenant who won't OAuth.

**Token storage:** refresh tokens / app-passwords → AES-256-GCM envelope-encrypted, per-tenant
DEK, in the **existing controlplane vault** — never plaintext, never logged.

### 5.6 Agent email loop (read → govern → reply-in-thread)
Same shape as the WhatsApp channel — one canonical contract, one Temporal workflow per message:
- **Thin signed-webhook edge**: verify signature + check SPF/DKIM pass → ACK 200 fast → enqueue raw (no inline agent work).
- **Two-layer idempotency**: `processed_messages` UNIQUE on `(tenant_id, Message-ID)` **and** Temporal `workflow_id = inbound:{tenant}:{message_id}`.
- **Tenant routing** from the connected-account / subscription id or the per-tenant opaque inbound address — reject anything ambiguous; never infer tenant from content; tenant context resolved by backend, **never by the LLM**.
- **Threading (RFC 5322 §3.6.4)** on every reply: `In-Reply-To = parent.Message-ID`;
  `References = (parent.References or parent.In-Reply-To) + " " + parent.Message-ID`; mint &
  persist the outbound `Message-ID` **before** send (so retries reuse it). Build MIME with
  stdlib `email.message.EmailMessage`. For Outlook prefer Graph `/reply` (sets `Thread-Index`).
- **Send behind the NIL default-deny gate**: recipient must come from the inbound thread +
  per-tenant allowlist; rate-limited (existing per-tenant quotas); HITL-gated; fully audited.
- **Renewal jobs** (Gmail `watch` re-arm / Graph subscription renew / delta reconcile) = Temporal cron workflows.

**Templates:** **Jinja2** (already in stack); add **MJML→compile** only if Outlook rendering breaks. Skip react-email (Node toolchain, no gain for a Python backend).

**OSS stack:** `email.message` (MIME+threading) · `aiosmtplib`/`fastapi-mail` (send) ·
`imap-tools` (IMAP read) · `google-api-python-client` + `msgraph-sdk` (provider APIs) ·
`authlib` (OAuth + refresh) · `jinja2` (templates).

**Sources:** [Gmail OAuth scopes](https://developers.google.com/workspace/gmail/api/auth/scopes) ·
[Google CASA / restricted scopes](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification) ·
[MS Graph permissions](https://learn.microsoft.com/en-us/graph/permissions-reference) ·
[RFC 5322 §3.6.4](https://www.rfc-editor.org/rfc/rfc5322.html) ·
[imap-tools](https://github.com/ikvk/imap_tools) · [aiosmtplib](https://github.com/cole/aiosmtplib) ·
[Stalwart](https://github.com/stalwartlabs/stalwart)

### 5.7 Sequencing
1. Wire Keycloak SMTP (5.1) + verify DNS (5.2). 2. Turn on `verifyEmail=true`, **revert the
`INSECURE_OIDC_ALLOW_UNVERIFIED_EMAIL` hack**. 3. Add `fastapi-mail` to os-server for app
emails. 4. Build per-tenant mailbox connect (5.5) + agent loop (5.6) as its own feature —
M365 Graph first, then Gmail send-OAuth + forward, then IMAP/forwarding fallback.

---

## 6. REUSE from `wosool-new-saas` — don't build from zero

The repo at `/home/ubuntu/wosool-saas/wosool-new-saas` already contains a **production
multi-tenant orchestrator** (Temporal-based) with WhatsApp/Evolution, email, per-tenant
provisioning, Keycloak auth, per-tenant rate-limiting, and an encrypted token vault. NIL
should **lift these modules**, not reimplement them.

### 6.1 Backend — reuse as-is (no Salla coupling)
| Module (`packages/orchestrator/app/...`) | What it gives NIL |
|---|---|
| `services/evolution_api_service.py` → `EvolutionAPIService` | Full Evolution HTTP client (pooled, circuit-breaker, idempotent): `create_instance`, `connect_instance`, `get_connection_state`, `set_webhook`, `send_text/media/audio`, `logout/delete_instance`, QR/state extractors. **Drop-in WhatsApp channel.** |
| `services/evolution_naming.py` | Deterministic per-tenant instance name `wosool-{ws[:8]}-{ws[8:16]}` + canonical webhook route. Reversible from inbound payload. |
| `temporal/providers/email.py` (`EmailProvider`) + `providers/dispatcher.py` (`NotificationDispatcher`) | SMTP send + channel→provider registry. Pure, provider-agnostic. (Coexists with `fastapi-mail` if we prefer that for app email.) |
| `temporal/per_tenant_rate_limit.py` → `acquire_tenant_slot` | Redis token-bucket per-tenant concurrency. Add a `hermes` kind. |
| `core/keycloak_auth.py` → `_verify_jwt`, `KeycloakIdentity`, `verify_admin_or_service` | Self-contained Keycloak JWT verifier (JWKS cache). Same realm NIL already uses. |
| `core/security.py` → `encrypt_token`/`decrypt_token` (Fernet) | Same pattern as NIL's controlplane vault. |
| provisioning activities `create_keycloak_user`, `send_keycloak_invite`, `provision_evolution_instance`, `mark_pending_whatsapp` | The generic, non-Salla steps of the install saga. |

### 6.2 Backend — adapt (swap Salla/Mongo persistence for NIL's store)
| Module | Adaptation |
|---|---|
| `api/v1/wa_webhooks.py` (inbound router) | Keep the per-event demux (`MESSAGES_UPSERT`/`CONNECTION_UPDATE`/`QRCODE_UPDATED`); **rewrite the tenant-resolution prologue** (instance→workspace) to hit NIL's tenant store + dispatch to that tenant's Hermes. |
| `activities/whatsapp.py` (`send_owner_reply`, `send_confirmation_buttons`) | Keep the guard chain (circuit-breaker, readiness, dedup, sanitizer, echo markers); route by NIL tenant id instead of `store_id`. |
| `temporal/activities/notify_activity.py` (`_send_with_dedupe_and_dlq`) | Keep dedupe+DLQ+retry taxonomy; swap the Mongo `outbound_delivery` collections for NIL persistence. |
| `services/salla_token_vault.py` | Reuse the **generation + HMAC-CAS + Fernet** pattern for NIL's per-tenant secret vault; replace Salla fields with NIL credential schema. |

### 6.3 NIL's provisioning saga (≈6 steps, from the existing 14)
`validate_input → create_keycloak_user → send_keycloak_invite → provision_workspace
(NIL backend, not Salla) → write_install_audit → provision_evolution_instance →
mark_pending_whatsapp`. Salla-specific steps (webhooks, widget, twin seed, customer sync) drop.

### 6.4 Notes
- Evolution uses **one global `EVOLUTION_API_KEY`**; per-tenant isolation is by **named
  instance**, not per-tenant token. NIL keeps the same model.
- Existing email path is stdlib `smtplib` (STARTTLS:587) — fine to reuse; **or** use
  `fastapi-mail` in os-server for app email (both hit `mail.wosool.ai`). No inbound email
  handling exists yet — that's the one genuinely new build (see §5.5/§5.6).
- Config surface (`core/config.py`) already enumerates Evolution/SMTP/Keycloak/Temporal/
  Redis env — reuse the same names.

### 6.5 STRATEGY (locked): migrate INTO our stack — port, don't adopt

**Decision:** Everything moves into **our** repos/stack — `nilscript` (Python backend +
controlplane), `wosool-hub` (Vite+React UI), `nil-infra`/`nil-os` (deploy). We **port** the
proven code from `wosool-new-saas` as a reference source, then **retire** the old stacks
(`wosool-frontend` Next.js, `wosool-saas` compose). We do **not** run on someone else's stack.

**Why port, not adopt `wosool-frontend` wholesale** (from the frontend reuse map):
- It's Next.js App Router + 7-provider context tree + a 1,200-line `WorkspaceContext`
  god-object wired to Salla/Stripe/Chatwoot — adopting it imports a deprecated product's
  debt. `wosool-hub` (Vite, static build, our stack) stays lean.
- The genuinely valuable bits are **self-contained** and port cleanly.

**Frontend port targets → `wosool-hub`:**
| From `wosool-frontend` | Port effort | NIL value |
|---|---|---|
| `inbox/channels/page.jsx` → `QRCodePanel` (WhatsApp QR connect state machine) | Low (swap ~5 fetch URLs) | **High — the WhatsApp connect UI** |
| `components/ui/*` (shadcn/Radix primitives) | Zero (copy) | High |
| `settings/credentials/page.jsx` (secret-vault UI) | Low (1 API base swap) | High |
| `settings/integrations/page.js` (connector/Apps hub) | Medium | High — maps to NIL adapter registry |
| `dashboard/dev/conv-ai` (`WosoolAssistant`+`SystemOrb3D` voice/text widget) | Low (no backend coupling) | High — Hermes chat surface |
| Inbox/ConversationThread (Chatwoot-shaped), Billing (Stripe), Salla cards | skip | rebuild against NIL ledger / not needed |

The auth seam: add a small `useNILAuth()` in `wosool-hub` mirroring `fetchWithAuth(url,opts)`
(injects Keycloak Bearer + `x-workspace-id`); ported components then work unchanged.

**Backend port targets → `nilscript`** (per §6.1/§6.2): lift `EvolutionAPIService`,
`evolution_naming`, `EmailProvider`, `acquire_tenant_slot`, `keycloak_auth`,
`encrypt/decrypt_token`, and the generic provisioning activities into NIL modules; rewrite the
inbound webhook tenant-resolution against NIL's store.

**Server-side proxy seam:** the Next.js `/api/evolution/*` + `/api/temporal/*` route handlers
(which inject `WOSOOL_SERVICE_TOKEN`) don't exist in a Vite app — reimplement them as thin
routes in **os-server** (FastAPI) so the browser never sees the service token.

### 6.6 Migration execution order (into our stack)
1. **Backend modules** → `nilscript`: Evolution client + naming + email provider + tenant-slot
   + keycloak_auth + token vault (reuse-as-is set). Add os-server proxy routes for
   `/api/evolution/*`.
2. **WhatsApp connect** → `wosool-hub`: port `QRCodePanel` as `<WhatsAppConnect>`, wire to the
   os-server proxy. First end-to-end owned channel.
3. **Provisioning saga** → NIL Temporal worker: the ~6-step tenant provision (create KC user →
   invite → provision workspace → audit → provision Evolution instance → mark pending_wa).
4. **Settings/connector/vault UI** → `wosool-hub` (credentials + Apps hub).
5. **Email**: Keycloak SMTP (DONE) → verify DNS deliverability → flip `verifyEmail`, drop the
   unverified-email hack → add `fastapi-mail` to os-server.
6. **Infra**: stand up `nil-infra` (own keycloak/caddy/redis/temporal/evolution), cut over,
   retire `wosool-saas`.
7. **Retire** `wosool-frontend`.

---

## 7. Open decisions for the user
1. WhatsApp: stay on Evolution (free, unofficial, ban-risk) for MVP, or go official Cloud API now? (research recommendation incoming)
2. Email: trust self-hosted `mail.wosool.ai` for transactional, or add a managed relay (deliverability)? (research recommendation incoming)
3. Customer mailbox connect: IMAP app-passwords (fast) vs Gmail/M365 OAuth (proper, more setup)?
4. Migration execution window: when can we tolerate ~5–10 min of auth/edge churn?
