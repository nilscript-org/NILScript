"""SQLite-backed NIL event store — append-only audit, deduped by (workspace, sequence).

stdlib only (no external DB). Every NIL EVENT (proposed / executed / refused / rolled_back) from any
adapter lands here via the control-plane ingest, so MCP + playground + SDK actions share one timeline.
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import threading
from typing import Any

_DDL = """
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT,
    received_at  TEXT    NOT NULL,
    workspace    TEXT    NOT NULL DEFAULT '',
    sequence     INTEGER,
    grant_id     TEXT    NOT NULL DEFAULT '',
    source       TEXT    NOT NULL DEFAULT '',
    performative TEXT    NOT NULL DEFAULT '',
    event        TEXT    NOT NULL DEFAULT '',
    proposal     TEXT,
    verb         TEXT,
    tier         TEXT,
    severity     TEXT,
    envelope     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_id ON events(id DESC);

CREATE TABLE IF NOT EXISTS approvals (
    proposal_id TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'pending',
    workspace   TEXT NOT NULL DEFAULT '',
    verb        TEXT,
    tier        TEXT,
    preview     TEXT,
    actor       TEXT,
    reason      TEXT,
    created_at  TEXT NOT NULL,
    decided_at  TEXT
);

-- Governed dependent plans (ordered, linked approval cards). A `planned_step` is a dependent step
-- that is NOT yet proposed to the adapter — its handoff reference (e.g. invoice.client_id) can't be
-- resolved until its prerequisite is committed. It carries a SYNTHETIC proposal_id so the UI can show
-- a blocked card; on the prerequisite's commit the executor resolves the handoff, proposes it for
-- real, and promotes it into `approvals` as a held plan card. Universal (kernel/CP only).
CREATE TABLE IF NOT EXISTS planned_steps (
    proposal_id TEXT    NOT NULL PRIMARY KEY,   -- synthetic id (planned:<plan_id>:<seq>)
    plan_id     TEXT    NOT NULL,
    seq         INTEGER NOT NULL,
    depends_on  TEXT,                            -- prerequisite's (real) proposal_id
    verb        TEXT    NOT NULL,
    args        TEXT    NOT NULL,                -- JSON args WITH $.step<i> handoff placeholders
    handoff     TEXT,                            -- JSON {arg_field: "$.step<i>.<field>"}
    preview     TEXT,
    tier        TEXT,
    workspace   TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'planned',  -- planned | materialized | cancelled
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_planned_plan ON planned_steps(plan_id);

-- Active-adapter registry: which backend the hosted MCP routes to per workspace. This is the ONE
-- piece of mutable state the kernel keeps; `bearer` reaches the (tenant-owned) adapter, never the
-- backend's own creds. Activating one adapter deactivates its siblings in the same workspace.
CREATE TABLE IF NOT EXISTS adapters (
    workspace   TEXT    NOT NULL DEFAULT '',
    adapter_id  TEXT    NOT NULL,
    label       TEXT    NOT NULL DEFAULT '',
    url         TEXT    NOT NULL,
    bearer      TEXT    NOT NULL DEFAULT '',
    system      TEXT    NOT NULL DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT    NOT NULL,
    PRIMARY KEY (workspace, adapter_id)
);

-- Per-tenant secret vault: a company's adapter creds + LLM key, saved ONCE at onboarding. The value
-- is ENCRYPTED at rest (Fernet, master key from NIL_VAULT_KEY) — a leaked row is ciphertext, never
-- credentials. Keyed by workspace; the control-plane decrypts only to use, never echoes to the browser.
CREATE TABLE IF NOT EXISTS tenant_secrets (
    workspace   TEXT    NOT NULL PRIMARY KEY,
    ciphertext  BLOB    NOT NULL,
    updated_at  TEXT    NOT NULL
);

-- Automation Registry (SSOT): one row per VERSION of one automation. Append-only — "editing" an
-- automation writes a new version and archives the prior one (superseded_by). `content_hash` is the
-- version lock (sha256 over the validated plan). See docs/PLAN-dynamic-automation-ssot.md.
CREATE TABLE IF NOT EXISTS automations (
    workspace     TEXT    NOT NULL DEFAULT '',
    automation_id TEXT    NOT NULL,
    version       INTEGER NOT NULL,
    content_hash  TEXT    NOT NULL,
    kind          TEXT    NOT NULL DEFAULT 'single',
    name          TEXT    NOT NULL DEFAULT '{}',
    description   TEXT,
    plan          TEXT    NOT NULL,
    source        TEXT,
    trigger       TEXT    NOT NULL,
    state         TEXT    NOT NULL DEFAULT 'draft',
    authored_by   TEXT    NOT NULL DEFAULT '',
    approved_by   TEXT,
    created_at    TEXT    NOT NULL,
    superseded_by INTEGER,
    PRIMARY KEY (workspace, automation_id, version)
);

-- Automation runs: one execution of one (pinned) automation version. `run_id` is deterministic
-- (automation:version:fire) so a re-delivered fire replays the same row, never double-executes.
CREATE TABLE IF NOT EXISTS automation_runs (
    run_id        TEXT    PRIMARY KEY,
    workspace     TEXT    NOT NULL DEFAULT '',
    automation_id TEXT    NOT NULL,
    version       INTEGER NOT NULL,
    content_hash  TEXT    NOT NULL,
    fired_by      TEXT    NOT NULL DEFAULT '',
    state         TEXT    NOT NULL DEFAULT 'running',
    trace         TEXT,
    started_at    TEXT    NOT NULL,
    ended_at      TEXT,
    business_ref  TEXT,
    correlation_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_runs_auto ON automation_runs(workspace, automation_id, started_at DESC);

-- Business-ref sequence: a monotonic, gap-free per-(workspace, automation) counter for minting the
-- human thread identity (PO-2026-00145). Replaces COUNT(*) of runs, which was racy AND reused a ref
-- after a run was deleted. `next` persists independently of the runs table (business-threads W1).
CREATE TABLE IF NOT EXISTS ref_sequences (
    workspace     TEXT    NOT NULL DEFAULT '',
    automation_id TEXT    NOT NULL,
    next          INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (workspace, automation_id)
);

-- Capability registry (SSOT): one row per VERSION of one capability — the business-contract
-- object (CAPABILITY-SHIFT plan B1). Exactly the automation-registry disciplines: content_hash is
-- the lock, re-registering the same hash is an idempotent no-op, a new hash supersedes (never
-- edits) the prior version, and every read is workspace-pinned (fail closed). Lifecycle:
-- draft -> published -> deprecated (a superseded version is deprecated by its successor).
CREATE TABLE IF NOT EXISTS capabilities (
    workspace     TEXT    NOT NULL DEFAULT '',
    capability_id TEXT    NOT NULL,
    version       INTEGER NOT NULL,
    content_hash  TEXT    NOT NULL,
    body_json     TEXT    NOT NULL,
    state         TEXT    NOT NULL DEFAULT 'draft',
    created_at    TEXT    NOT NULL,
    superseded_by INTEGER,
    PRIMARY KEY (workspace, capability_id, version)
);

-- Strategy registry (SSOT): same disciplines, for the approval-strategy objects capabilities
-- reference by id (a capability without its strategy is a dangling governance pointer).
CREATE TABLE IF NOT EXISTS strategies (
    workspace     TEXT    NOT NULL DEFAULT '',
    strategy_id   TEXT    NOT NULL,
    version       INTEGER NOT NULL,
    content_hash  TEXT    NOT NULL,
    body_json     TEXT    NOT NULL,
    state         TEXT    NOT NULL DEFAULT 'draft',
    created_at    TEXT    NOT NULL,
    superseded_by INTEGER,
    PRIMARY KEY (workspace, strategy_id, version)
);

-- Parked runs: a run that stopped mid-walk to wait for an external signal. Row-backed so a
-- decision (or a matching event / the deadline) resumes the run DETERMINISTICALLY across process
-- restarts — never an in-memory await. `kind`='approval' waits on a human decision for
-- `proposal_id`; `kind`='event' waits on a ledger event matching (`on_event`, `match`). `context`
-- is the executor context at park time; `deadline` (ISO) routes the run to its timeout branch.
CREATE TABLE IF NOT EXISTS parked_runs (
    run_id        TEXT    NOT NULL,
    node_id       TEXT    NOT NULL,
    kind          TEXT    NOT NULL DEFAULT 'approval',   -- approval | event
    workspace     TEXT    NOT NULL DEFAULT '',
    automation_id TEXT    NOT NULL DEFAULT '',
    version       INTEGER NOT NULL DEFAULT 0,
    proposal_id   TEXT,
    on_event      TEXT,
    match         TEXT,                                   -- JSON shallow field filter
    deadline      TEXT,                                   -- ISO UTC; NULL = no timeout route
    context       TEXT    NOT NULL DEFAULT '{}',          -- executor context at park time (JSON)
    status        TEXT    NOT NULL DEFAULT 'waiting',     -- waiting | resumed | rejected | timed_out
    created_at    TEXT    NOT NULL,
    settled_at    TEXT,
    PRIMARY KEY (run_id, node_id)
);
CREATE INDEX IF NOT EXISTS ix_parked_proposal ON parked_runs(proposal_id);

-- Run checkpoints (plan B5): one row per WALKED `checkpoint` step — the row-backed ledger marker
-- a per-phase rollback reverses to. `committed` is the ordered JSON list of IR node ids whose
-- writes had COMMITTED when the marker was walked (the context-snapshot ref: everything committed
-- AFTER it is the reversible segment). Idempotent by (run_id, name): a resumed segment
-- re-emitting the same marker keeps the original row.
CREATE TABLE IF NOT EXISTS run_checkpoints (
    run_id     TEXT NOT NULL,
    name       TEXT NOT NULL,
    node_id    TEXT NOT NULL DEFAULT '',
    workspace  TEXT NOT NULL DEFAULT '',
    committed  TEXT NOT NULL DEFAULT '[]',
    at         TEXT NOT NULL,
    PRIMARY KEY (run_id, name)
);

-- Strategy signature slots (plan B3): ONE approval subject, N signature slots. Each row is one
-- unit of the flattened strategy — who may sign (role/person), which Seq stage it belongs to,
-- and its lifecycle. `planned` mirrors planned_steps: a later Seq stage's slot exists but is not
-- yet actionable; it materializes to `pending` on the prior stage's approval. `superseded` is a
-- VOIDED signature (a material edit re-held the card); the row keeps actor/decided_at as the
-- audit trail and a fresh slot re-holds the unit. `deadline` follows the parked_runs pattern:
-- the /automations/tick sweep escalates or rejects due slots.
CREATE TABLE IF NOT EXISTS strategy_signatures (
    execution_id  TEXT    NOT NULL,
    unit_idx      INTEGER NOT NULL,
    unit_key      TEXT    NOT NULL DEFAULT '',
    stage         INTEGER NOT NULL DEFAULT 0,
    by_kind       TEXT    NOT NULL DEFAULT 'role',    -- role | person | policy
    role          TEXT    NOT NULL DEFAULT '',        -- the addressed role/person/policy name
    distinct_from TEXT,                                -- JSON list (SoD constraints)
    quorum_k      INTEGER NOT NULL DEFAULT 1,          -- k for this slot's stage
    quorum_distinct INTEGER NOT NULL DEFAULT 0,
    workspace     TEXT    NOT NULL DEFAULT '',
    actor         TEXT,
    decided_at    TEXT,
    status        TEXT    NOT NULL DEFAULT 'pending',  -- planned|pending|signed|rejected|superseded|cancelled|escalated|timed_out
    deadline      TEXT,                                -- ISO UTC; NULL = no timeout
    timeout_route TEXT,                                -- JSON {"kind":"escalate","to":...}|{"kind":"reject"}
    created_at    TEXT    NOT NULL,
    PRIMARY KEY (execution_id, unit_idx)
);
CREATE INDEX IF NOT EXISTS ix_sig_deadline ON strategy_signatures(status, deadline);

-- Prepared executions (plan B2): one row per prepared capability invocation — the SUBJECT the
-- strategy interpreter drives. Pins the exact registry versions (capability + strategy) at
-- prepare time so later registry edits never mutate an in-flight card; stamps the preparer for
-- SoD (invariant I6). The Permission Card is ASSEMBLED BY CODE from this row + the pinned
-- registry records + the live signature slots — never stored prose, never LLM-assembled (I5).
CREATE TABLE IF NOT EXISTS prepared_executions (
    prepared_id        TEXT    PRIMARY KEY,
    workspace          TEXT    NOT NULL,
    capability_id      TEXT    NOT NULL,
    capability_version INTEGER NOT NULL,
    content_hash       TEXT    NOT NULL,
    strategy_id        TEXT    NOT NULL DEFAULT '',
    strategy_version   INTEGER NOT NULL DEFAULT 0,
    strategy_hash      TEXT    NOT NULL DEFAULT '',
    inputs             TEXT    NOT NULL DEFAULT '{}',
    modifiable         TEXT    NOT NULL DEFAULT '[]',
    prepared_by        TEXT    NOT NULL,
    branch             TEXT,                              -- resolved Conditional branch
    risk               TEXT    NOT NULL DEFAULT 'HIGH',
    reversibility      TEXT    NOT NULL DEFAULT 'IRREVERSIBLE',
    compensation       TEXT,
    affected_systems   TEXT    NOT NULL DEFAULT '[]',
    status             TEXT    NOT NULL DEFAULT 'pending', -- pending|approved|committed|rejected
    reason             TEXT    NOT NULL DEFAULT '',          -- rejection reason (audit)
    commit_result      TEXT,
    created_at         TEXT    NOT NULL,
    decided_at         TEXT
);
CREATE INDEX IF NOT EXISTS ix_prepared_ws ON prepared_executions(workspace, created_at DESC);

-- One-shot scheduled executions (plan B7 nil_schedule): a prepared execution due to commit at/
-- after `fire_at`, swept by the same /automations/tick clock that resumes parked runs and
-- enforces signature deadlines. A row, never an in-memory timer — restarts lose nothing. The
-- fire outcome (fired | refused) is RECORDED, honest: a strategy still unsatisfied at fire time
-- settles as refused with the NOT_APPROVED answer, never silently retried.
CREATE TABLE IF NOT EXISTS scheduled_executions (
    schedule_id  TEXT    PRIMARY KEY,
    prepared_id  TEXT    NOT NULL,
    workspace    TEXT    NOT NULL,
    fire_at      TEXT    NOT NULL,                     -- ISO UTC; lexicographic compare
    status       TEXT    NOT NULL DEFAULT 'pending',   -- pending|fired|refused|cancelled
    result       TEXT,                                 -- JSON outcome recorded at fire time
    created_at   TEXT    NOT NULL,
    settled_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_sched_due ON scheduled_executions(status, fire_at);

-- Cycle compilation pipeline (Wave 4 Phase 1): one row per cycle version. Stores the compiled
-- Flow, backend bindings, and compilation errors. `domain_id` identifies the domain the cycle
-- implements; `compiled_plan` is the lowered WosoolProgram; `flow` is the Cycle AST Flow;
-- `backend_bindings` maps capabilities to adapters. Status tracks compilation lifecycle.
CREATE TABLE IF NOT EXISTS cycles (
    workspace       TEXT    NOT NULL DEFAULT '',
    cycle_id        TEXT    NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    domain_id       TEXT,                                  -- domain this cycle implements
    cycle_ast       TEXT    NOT NULL,                      -- serialized Cycle (the SSOT)
    compiled_plan   TEXT,                                  -- serialized CompiledPlan (lowered IR)
    flow            TEXT,                                  -- serialized Flow from compiled_plan
    backend_bindings TEXT    NOT NULL DEFAULT '{}',        -- JSON {capability -> adapter}
    compile_error   TEXT,                                  -- error message if compile failed
    status          TEXT    NOT NULL DEFAULT 'draft',      -- draft|published|compile_error|lower_error
    content_hash    TEXT,                                  -- SHA256 hash of cycle AST (version lock)
    created_at      TEXT    NOT NULL,
    published_at    TEXT,                                  -- when status changed to published
    PRIMARY KEY (workspace, cycle_id, version)
);
CREATE INDEX IF NOT EXISTS ix_cycles_ws ON cycles(workspace, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_cycles_status ON cycles(workspace, status);

-- Business Discovery Sessions: track multi-phase discovery conversations
CREATE TABLE IF NOT EXISTS discovery_sessions (
    session_id      TEXT    NOT NULL PRIMARY KEY,
    workspace       TEXT    NOT NULL DEFAULT '',
    domain_name     TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    phase           TEXT    NOT NULL DEFAULT 'intro',
    status          TEXT    NOT NULL DEFAULT 'in_progress',
    current_answer  TEXT,
    user_email      TEXT,
    metadata        TEXT,
    completed_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_discovery_workspace ON discovery_sessions(workspace);

-- Discovered Business Specifications: the extracted result after discovery is complete
CREATE TABLE IF NOT EXISTS specifications (
    spec_id         TEXT    NOT NULL PRIMARY KEY,
    workspace       TEXT    NOT NULL DEFAULT '',
    session_id      TEXT    NOT NULL,
    domain_name     TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    content_hash    TEXT    NOT NULL,
    specification   TEXT    NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    status          TEXT    NOT NULL DEFAULT 'draft',
    FOREIGN KEY (session_id) REFERENCES discovery_sessions(session_id)
);
CREATE INDEX IF NOT EXISTS ix_spec_workspace ON specifications(workspace);
CREATE INDEX IF NOT EXISTS ix_spec_session ON specifications(session_id);

-- Audit trail: every answer and extraction for post-hoc review
CREATE TABLE IF NOT EXISTS discovery_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,
    workspace       TEXT    NOT NULL DEFAULT '',
    phase           TEXT    NOT NULL,
    user_answer     TEXT    NOT NULL,
    extraction_result TEXT,
    extracted_count INTEGER,
    extraction_error TEXT,
    timestamp       TEXT    NOT NULL,
    FOREIGN KEY (session_id) REFERENCES discovery_sessions(session_id)
);
CREATE INDEX IF NOT EXISTS ix_audit_session ON discovery_audit(session_id);
CREATE INDEX IF NOT EXISTS ix_audit_timestamp ON discovery_audit(timestamp DESC);
"""

# Columns surfaced by the automation registry reads (JSON columns parsed back by `_automation_row`).
_AUTOMATION_COLS = (
    "workspace, automation_id, version, content_hash, kind, name, description, plan, source, "
    "trigger, state, authored_by, approved_by, created_at, superseded_by"
)

# Columns surfaced by the registry read methods (bearer included — the API layer redacts for the
# public list endpoint; `active_adapter` keeps it because the MCP needs it to reach the adapter).
_ADAPTER_COLS = "workspace, adapter_id, label, url, bearer, system, active, updated_at"


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _loads(envelope: str | None) -> dict[str, Any]:
    """Best-effort parse of a stored envelope; a corrupt row must never crash the timeline."""
    if not envelope:
        return {}
    try:
        out = json.loads(envelope)
        return out if isinstance(out, dict) else {}
    except (ValueError, TypeError):
        return {}


def _verify_status(event: str | None, result: dict[str, Any]) -> str | None:
    """Field-level truth for the VERIFIED column — derived from `claim` + `ssot.unverified_fields`,
    NOT the bare `result.verified` flag (which reported success while country_id silently dropped).
    `verified` = the SSOT read-back matched the intent; `partial` = something didn't persist;
    `failed` = the write itself failed. None when the event carries no write result (e.g. proposed)."""
    if not result:
        return None
    claim = str(result.get("claim") or "").lower()
    unverified = (result.get("ssot") or {}).get("unverified_fields") or []
    if claim == "failure":
        return "failed"
    if unverified or claim == "partial":
        return "partial"
    if claim == "success":
        return "verified"
    # An executed write with a result but no explicit claim: the verified flag is a weak last resort.
    if event in ("executed", "rolled_back"):
        return "verified" if result.get("verified") else "partial"
    return None


class EventStore:
    """Thread-safe SQLite event log. `ingest` dedups by (workspace, sequence); `recent` reads newest-first."""

    def __init__(self, path: str | None = None) -> None:
        self._path = path or os.environ.get("CP_DB_PATH", "/data/controlplane.db")
        parent = os.path.dirname(self._path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        # The secret vault is enabled only when a master key is configured; otherwise secret storage
        # fails closed (a tenant's creds are never stored in plaintext as a fallback).
        self._vault = None
        try:
            from nilscript.secrets import SecretVault

            self._vault = (
                SecretVault.from_env()
            )  # NIL_VAULT_KEY; raises if unset → stays None
        except Exception:  # noqa: BLE001 — no/invalid key ⇒ vault disabled, not crashed
            self._vault = None
        with self._lock:
            self._conn.executescript(_DDL)
            # Existing DBs (volume) predate event_id — add it idempotently.
            try:
                self._conn.execute("ALTER TABLE events ADD COLUMN event_id TEXT")
            except sqlite3.OperationalError:
                pass  # column already present
            # business_ref: a run's human thread identity (PO-2026-00145) — see business-threads-plan.
            try:
                self._conn.execute("ALTER TABLE automation_runs ADD COLUMN business_ref TEXT")
            except sqlite3.OperationalError:
                pass
            # correlation_id: the durable JOIN key every side-channel stamps so scattered events
            # (comms replies, prepared cards, docs) find their thread — see business-threads-plan §3.
            try:
                self._conn.execute("ALTER TABLE automation_runs ADD COLUMN correlation_id TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                self._conn.execute(
                    "ALTER TABLE automations ADD COLUMN kind TEXT NOT NULL DEFAULT 'single'"
                )
            except sqlite3.OperationalError:
                pass  # column already present (or table created fresh with it)
            try:
                # Cycle AST SSOT: kind='cycle' rows carry the canonical Cycle in `source` (the
                # `plan` is the derived, lowered WosoolProgram). NULL for plain automations.
                self._conn.execute("ALTER TABLE automations ADD COLUMN source TEXT")
            except sqlite3.OperationalError:
                pass  # column already present
            try:
                # SaaS isolation (root): a held proposal carries its OWN workspace (recorded by the
                # gate at hold-time), so per-tenant `pending` filters on it directly — no fragile join
                # to the ledger by proposal_id. Backfill of legacy rows is best-effort from events.
                self._conn.execute("ALTER TABLE approvals ADD COLUMN workspace TEXT NOT NULL DEFAULT ''")
                self._conn.execute(
                    "UPDATE approvals SET workspace = COALESCE((SELECT e.workspace FROM events e "
                    "WHERE e.proposal = approvals.proposal_id LIMIT 1), '') WHERE workspace = ''"
                )
            except sqlite3.OperationalError:
                pass  # column already present
            for col in ("resolved", "modifiable"):
                try:
                    # Editable decision cards: the gate records the proposal's resolved field values
                    # and which are editable, so the owner's card is a filled-in form and an
                    # approve-with-edits can re-propose exactly the tweaked args before commit.
                    self._conn.execute(f"ALTER TABLE approvals ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass  # column already present
            # Governed dependent plans: an approval MAY belong to an ordered plan. `plan_id` groups a
            # plan's cards; `seq` orders them; `depends_on` points at the prerequisite step this one
            # needs committed first. NULL for standalone proposals (unchanged behavior). `committed_id`
            # records an approved step's backend id so a dependent's handoff placeholder resolves.
            for _ddl in (
                "ALTER TABLE approvals ADD COLUMN plan_id TEXT",
                "ALTER TABLE approvals ADD COLUMN seq INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE approvals ADD COLUMN depends_on TEXT",
                "ALTER TABLE approvals ADD COLUMN committed_id TEXT",
            ):
                try:
                    self._conn.execute(_ddl)
                except sqlite3.OperationalError:
                    pass  # column already present
            self._conn.commit()

    def ingest(
        self, envelope: dict[str, Any], sequence: int | None, *, source: str = ""
    ) -> bool:
        """Store one event. Returns False (no-op) if (workspace, sequence) was already seen."""
        body = envelope.get("body") or {}
        ws = envelope.get("workspace", "") or ""
        # Dedup by the globally-unique envelope id (stable across at-least-once retries). NOT by
        # (workspace, sequence): the adapter's sequence is in-memory and resets on restart, so that
        # key collides across restarts and silently drops fresh events.
        eid = envelope.get("id")
        with self._lock:
            if eid:
                if self._conn.execute(
                    "SELECT 1 FROM events WHERE event_id = ?", (eid,)
                ).fetchone():
                    return False
            elif sequence is not None:
                if self._conn.execute(
                    "SELECT 1 FROM events WHERE workspace = ? AND sequence = ?",
                    (ws, sequence),
                ).fetchone():
                    return False
            self._conn.execute(
                "INSERT INTO events (event_id, received_at, workspace, sequence, grant_id, source, "
                "performative, event, proposal, verb, tier, severity, envelope) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    eid,
                    _now(),
                    ws,
                    sequence,
                    envelope.get("grant", "") or "",
                    source,
                    envelope.get("performative", "") or "",
                    body.get("event", "") or "",
                    body.get("proposal"),
                    body.get("verb"),
                    body.get("tier"),
                    body.get("severity"),
                    json.dumps(envelope, ensure_ascii=False),
                ),
            )
            self._conn.commit()
        return True

    def recent(
        self, limit: int = 100, workspace: str | None = None
    ) -> list[dict[str, Any]]:
        # SaaS isolation: when a workspace is given, return ONLY that tenant's events. Pass None only
        # for the operator/global timeline.
        where = "WHERE workspace = ? " if workspace is not None else ""
        params: tuple[Any, ...] = (
            (workspace, max(1, min(limit, 1000)))
            if workspace is not None
            else (max(1, min(limit, 1000)),)
        )
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, received_at, workspace, sequence, grant_id, source, performative, "
                f"event, proposal, verb, tier, severity, envelope FROM events {where}ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        # An executed/refused event omits verb/tier and the human preview (those live on the
        # proposal). Pull them from each row's matching `proposed` event in ONE query so the timeline
        # can show the real verb, the tier, and a human one-liner (with the name) — not a bare id.
        pids = [r["proposal"] for r in rows if r["proposal"]]
        proposed: dict[str, dict[str, Any]] = {}
        if pids:
            uniq = list(dict.fromkeys(pids))
            ph = ",".join("?" * len(uniq))
            with self._lock:
                prows = self._conn.execute(
                    f"SELECT proposal, verb, tier, envelope FROM events "
                    f"WHERE event = 'proposed' AND proposal IN ({ph})",
                    uniq,
                ).fetchall()
            for pr in prows:
                prev: Any = {}
                try:
                    prev = (json.loads(pr["envelope"]).get("body") or {}).get(
                        "preview"
                    ) or {}
                except (ValueError, TypeError):
                    prev = {}
                proposed[pr["proposal"]] = {
                    "verb": pr["verb"],
                    "tier": pr["tier"],
                    "summary": prev.get("en") if isinstance(prev, dict) else None,
                }
        out: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            envelope = record.pop("envelope", None)
            body: dict[str, Any] = {}
            if envelope:
                try:
                    body = json.loads(envelope).get("body") or {}
                except (ValueError, TypeError):
                    body = {}
            result = body.get("result") or {}
            entity = result.get("entity") or {}
            ssot = result.get("ssot") or {}
            comp = result.get("compensation") or {}
            # Surface the compensation handle for an executed write so the UI can offer a rollback
            # affordance on exactly the reversible rows (and nothing else).
            record["reversibility"] = comp.get("reversibility")
            record["compensation_token"] = comp.get("token")
            # Enrich the timeline with detail the envelope already carries but the indexed columns
            # miss: executed events omit `verb`/`tier` from the body (those live on the proposal),
            # so fall back to the result's entity type; and surface the backend + the affected entity
            # and a human one-liner so each row says WHAT happened, not just that something did.
            from_proposed = proposed.get(record.get("proposal") or "") or {}
            record["verb"] = (
                record.get("verb") or from_proposed.get("verb") or entity.get("type")
            )
            record["tier"] = record.get("tier") or from_proposed.get("tier")
            record["system"] = ssot.get("system")
            record["entity_id"] = entity.get("id")
            record["entity_url"] = entity.get("url")
            # Human one-liner, best→worst: this event's own preview, the proposal's preview (has the
            # name/value), else the affected entity path.
            preview = body.get("preview") or {}
            summary = (
                preview.get("en") if isinstance(preview, dict) else None
            ) or from_proposed.get("summary")
            if not summary and entity:
                eid = entity.get("id")
                summary = f"{entity.get('url') or entity.get('type') or ''}".strip(
                    "/"
                ) or (str(eid) if eid else None)
            record["summary"] = summary
            record["args"] = body.get("args") or None
            # The headline column: did the intent actually land in the SSOT, field for field?
            record["verify"] = _verify_status(record.get("event"), result)
            out.append(record)
        return out

    def detail(self, event_id: int) -> dict[str, Any] | None:
        """The full payload journey for one event — raw intent → resolved values → field-level SSOT
        verdict → effect — assembled from its own envelope plus its proposal's `proposed` event and
        every sibling event for that proposal. Everything needed to reconstruct a (failed) action
        from the log alone, without opening the backend or the logs. Returns None for an unknown id."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, received_at, workspace, grant_id, source, performative, event, proposal, "
                "verb, tier, severity, envelope FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        env = _loads(row["envelope"])
        body = env.get("body") or {}
        result = body.get("result") or {}
        proposal_id = row["proposal"]
        # The proposal carries the intent the executed event omits: raw args, resolved values,
        # preview, expiry, and which args were ignored. Walk every event on this proposal to show
        # the saga (proposed → executed/refused → rolled_back) as one ordered thread.
        proposed_body: dict[str, Any] = {}
        journey: list[dict[str, Any]] = []
        if proposal_id:
            with self._lock:
                prows = self._conn.execute(
                    "SELECT id, received_at, event, envelope FROM events WHERE proposal = ? ORDER BY id",
                    (proposal_id,),
                ).fetchall()
            for pr in prows:
                pbody = _loads(pr["envelope"]).get("body") or {}
                if pr["event"] == "proposed" and not proposed_body:
                    proposed_body = pbody
                journey.append(
                    {
                        "id": pr["id"],
                        "event": pr["event"],
                        "received_at": pr["received_at"],
                        "replayed": pbody.get("replayed"),
                    }
                )
        resolved = proposed_body.get("resolved") or {}
        ssot = result.get("ssot") or {}
        # Field-level diff: prefer the adapter's emitted before→after read-back (the real prior value,
        # the requested value, and what actually LANDED in the SSOT). `verified=False` is exactly the
        # silent drop (country_id) the green row used to hide. Older adapters emit only the dropped
        # field names — fall back to the proposal's resolved values (no before/after available).
        emitted = ssot.get("fields")
        if emitted:
            fields = [
                {
                    "field": f.get("field"),
                    "before": f.get("before"),
                    "requested": f.get("requested"),
                    "after": f.get("after"),
                    "verified": bool(f.get("verified")),
                }
                for f in emitted
            ]
        else:
            unverified = set(ssot.get("unverified_fields") or [])
            fields = [
                {"field": k, "requested": v, "verified": k not in unverified}
                for k, v in resolved.items()
            ]
        code = body.get("code")
        return {
            "id": row["id"],
            "received_at": row["received_at"],
            "workspace": row["workspace"],
            "grant_id": row["grant_id"],
            "source": row["source"],
            "event": row["event"],
            "verb": row["verb"] or proposed_body.get("verb"),
            "tier": row["tier"] or proposed_body.get("tier"),
            "verify": _verify_status(row["event"], result),
            "preview": proposed_body.get("preview") or body.get("preview") or None,
            "raw_args": body.get("args") or proposed_body.get("args") or {},
            "resolved": resolved,
            "ignored": proposed_body.get("ignored") or None,
            "expires_at": proposed_body.get("expires_at"),
            "refusal": {
                "code": code,
                "message": body.get("message"),
                "field": body.get("field"),
            }
            if code
            else None,
            "result": result or None,
            "fields": fields,
            "journey": journey,
            "raw": {"event": env, "proposed": proposed_body or None},
        }

    def count(self) -> int:
        with self._lock:
            return int(
                self._conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
            )

    def adapters(self, limit: int = 800) -> list[dict[str, Any]]:
        """The distinct adapters/backends active in the timeline, derived purely from the audit log
        (no separate registry). Keyed by the backend's `system` (from an executed event's ssot) when
        known, else by the emitting source. Each carries event counts, channels, verb namespaces,
        and last-seen — so the single pane also answers 'what's linked, and is it live?'."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT received_at, source, event, performative, verb, envelope "
                "FROM events ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 2000)),),
            ).fetchall()
        # Parse each row once; an executed event names the backend `system`, so map proposal→system
        # to fold a proposal's other events (proposed/refused) into the same adapter, not a phantom.
        parsed: list[dict[str, Any]] = []
        proposal_system: dict[str, str] = {}
        for row in rows:
            rec = dict(row)
            system, proposal = None, None
            try:
                body = json.loads(rec["envelope"]).get("body") or {}
                proposal = body.get("proposal")
                system = ((body.get("result") or {}).get("ssot") or {}).get("system")
            except (ValueError, TypeError):
                pass
            if proposal and system:
                proposal_system[proposal] = system
            parsed.append({**rec, "_system": system, "_proposal": proposal})

        agg: dict[str, dict[str, Any]] = {}
        for rec in parsed:
            system = rec["_system"] or proposal_system.get(rec["_proposal"])
            source = rec.get("source") or "?"
            key = system or source
            entry = agg.setdefault(
                key,
                {
                    "adapter": key,
                    "system": system,
                    "sources": set(),
                    "events": 0,
                    "last_seen": rec["received_at"],
                    "by_event": {},
                    "namespaces": set(),
                },
            )
            entry["events"] += 1
            entry["sources"].add(source)
            if system and not entry["system"]:
                entry["system"] = system
            ev = rec.get("event") or rec.get("performative") or ""
            entry["by_event"][ev] = entry["by_event"].get(ev, 0) + 1
            verb = rec.get("verb") or ""
            if "." in verb:
                entry["namespaces"].add(verb.split(".", 1)[0])
            if rec["received_at"] > entry["last_seen"]:
                entry["last_seen"] = rec["received_at"]
        out = [
            {
                **e,
                "sources": sorted(e["sources"]),
                "namespaces": sorted(e["namespaces"]),
            }
            for e in agg.values()
        ]
        out.sort(key=lambda e: e["last_seen"], reverse=True)
        return out

    # ── human-approval gate (Phase 2) ────────────────────────────────────────────────────────
    def _enrich(self, proposal_id: str) -> dict[str, Any]:
        """Pull verb/tier/preview from the proposal's 'proposed' event (the control plane already
        received it from the adapter), so the approval card shows the full intent."""
        row = self._conn.execute(
            "SELECT verb, tier, envelope FROM events WHERE proposal = ? AND event = 'proposed' "
            "ORDER BY id DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return {"verb": None, "tier": None, "preview": None}
        preview = None
        try:
            preview = json.dumps(
                (json.loads(row["envelope"]).get("body") or {}).get("preview")
            )
        except (ValueError, TypeError):
            preview = None
        return {"verb": row["verb"], "tier": row["tier"], "preview": preview}

    def await_approval(
        self,
        proposal_id: str,
        *,
        verb: str | None = None,
        tier: str | None = None,
        preview: Any = None,
        workspace: str = "",
        resolved: Any = None,
        modifiable: Any = None,
        plan_id: str | None = None,
        seq: int = 0,
        depends_on: str | None = None,
    ) -> dict[str, Any]:
        """Register a proposal as awaiting human approval (idempotent — keeps an existing decision).

        `verb`/`tier`/`preview` are passed by the gate at hold-time (a held proposal has no ledger
        event yet, so `_enrich` finds nothing). They win over enrichment; `preview` (a dict) is stored
        as JSON so the owner's Decisions screen can show exactly what the proposal does. `resolved`
        (the field values) + `modifiable` (which keys are editable) drive the editable decision card.
        `plan_id`/`seq`/`depends_on` link this hold into an ordered dependent plan (NULL = standalone).
        """
        with self._lock:
            existing = self._conn.execute(
                "SELECT status FROM approvals WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
            if existing is not None:
                return {"proposal_id": proposal_id, "status": existing["status"]}
            meta = self._enrich(proposal_id)
            preview_str = (
                json.dumps(preview)
                if isinstance(preview, (dict, list))
                else (preview if preview is not None else meta["preview"])
            )
            self._conn.execute(
                "INSERT INTO approvals "
                "(proposal_id, status, workspace, verb, tier, preview, resolved, modifiable, "
                " plan_id, seq, depends_on, created_at) "
                "VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    proposal_id,
                    workspace or "",
                    verb or meta["verb"],
                    tier or meta["tier"],
                    preview_str,
                    json.dumps(resolved) if resolved is not None else None,
                    json.dumps(list(modifiable)) if modifiable is not None else None,
                    plan_id,
                    int(seq),
                    depends_on,
                    _now(),
                ),
            )
            self._conn.commit()
        return {"proposal_id": proposal_id, "status": "pending"}

    def decision(self, proposal_id: str) -> str:
        """'pending' | 'approved' | 'rejected' | 'unknown' (never registered)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM approvals WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
        return row["status"] if row is not None else "unknown"

    def decide(
        self, proposal_id: str, status: str, *, actor: str = "", reason: str = ""
    ) -> bool:
        """Owner decision. Only transitions a 'pending' row; returns False otherwise (idempotent/guarded)."""
        if status not in ("approved", "rejected"):
            raise ValueError("status must be 'approved' or 'rejected'")
        with self._lock:
            cur = self._conn.execute(
                "UPDATE approvals SET status = ?, actor = ?, reason = ?, decided_at = ? "
                "WHERE proposal_id = ? AND status = 'pending'",
                (status, actor, reason, _now(), proposal_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def pending(self, workspace: str | None = None) -> list[dict[str, Any]]:
        # SaaS isolation (root fix): each held proposal carries its OWN `workspace`, recorded by the
        # gate at hold-time, so a tenant sees only its holds by a DIRECT column filter — no fragile
        # join to the ledger by proposal_id. The legacy events-join is kept ONLY as a fallback for
        # pre-migration rows whose workspace is still ''. None = operator/global view.
        #
        # Governed dependent plans: each row carries plan_id/seq/depends_on and a computed `blocked`
        # boolean (true while its prerequisite is not yet committed). Not-yet-proposed PLANNED steps
        # (a dependent whose handoff can't resolve until its prerequisite commits) are included too,
        # as blocked cards with a synthetic proposal_id — so the UI can render the whole ordered plan.
        cols = (
            "proposal_id, verb, tier, preview, resolved, modifiable, created_at, "
            "plan_id, seq, depends_on"
        )
        if workspace is None:
            sql = (
                f"SELECT {cols} FROM approvals "
                "WHERE status = 'pending' ORDER BY created_at DESC"
            )
            params: tuple[Any, ...] = ()
        else:
            sql = (
                f"SELECT {cols} FROM approvals a "
                "WHERE a.status = 'pending' AND ("
                "  a.workspace = ?"
                "  OR (a.workspace = '' AND EXISTS (SELECT 1 FROM events e "
                "      WHERE e.proposal = a.proposal_id AND e.workspace = ?))"
                ") ORDER BY a.created_at DESC"
            )
            params = (workspace, workspace)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            # A prerequisite is "done" once its own approval is committed (approved + committed_id set).
            committed = {
                r["proposal_id"]
                for r in self._conn.execute(
                    "SELECT proposal_id FROM approvals WHERE status = 'approved'"
                ).fetchall()
            }
            if workspace is None:
                planned = self._conn.execute(
                    "SELECT proposal_id, verb, tier, preview, plan_id, seq, depends_on, created_at "
                    "FROM planned_steps WHERE status = 'planned' ORDER BY created_at DESC"
                ).fetchall()
            else:
                planned = self._conn.execute(
                    "SELECT proposal_id, verb, tier, preview, plan_id, seq, depends_on, created_at "
                    "FROM planned_steps WHERE status = 'planned' AND workspace = ? "
                    "ORDER BY created_at DESC",
                    (workspace,),
                ).fetchall()
        out = [self._shape_pending(r, committed) for r in rows]
        out.extend(self._shape_pending(r, committed, planned=True) for r in planned)
        return out

    @staticmethod
    def _shape_pending(
        row: Any, committed: set[str] | None = None, *, planned: bool = False
    ) -> dict[str, Any]:
        """Decode a pending row, exposing `resolved`/`modifiable` as real JSON for the editable card,
        and compute the plan `blocked` flag (true while a step's prerequisite is not yet committed)."""
        rec = dict(row)
        for key in ("resolved", "modifiable"):
            raw = rec.get(key)
            if isinstance(raw, str) and raw:
                try:
                    rec[key] = json.loads(raw)
                except json.JSONDecodeError:
                    rec[key] = None
        if isinstance(rec.get("preview"), str) and rec["preview"]:
            try:
                rec["preview"] = json.loads(rec["preview"])
            except json.JSONDecodeError:
                pass
        dep = rec.get("depends_on")
        # A planned (not-yet-proposed) step is always blocked; a proposed step is blocked while its
        # prerequisite hasn't committed. Standalone proposals (no depends_on) are never blocked.
        if planned:
            rec["blocked"] = True
            rec["planned"] = True
        else:
            rec["blocked"] = bool(dep) and (committed is None or dep not in committed)
        return rec

    # ── active-adapter registry (multi-tenant routing) ───────────────────────────────────────
    def register_adapter(
        self,
        workspace: str,
        adapter_id: str,
        *,
        label: str = "",
        url: str,
        bearer: str = "",
        system: str = "",
    ) -> dict[str, Any]:
        """Upsert an adapter the MCP can route to. Re-registering updates its coordinates but
        PRESERVES the active flag (so refreshing a bearer doesn't silently flip routing off)."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO adapters (workspace, adapter_id, label, url, bearer, system, active, updated_at) "
                "VALUES (?,?,?,?,?,?,0,?) "
                "ON CONFLICT(workspace, adapter_id) DO UPDATE SET "
                "label=excluded.label, url=excluded.url, bearer=excluded.bearer, "
                "system=excluded.system, updated_at=excluded.updated_at",
                (workspace, adapter_id, label, url, bearer, system, _now()),
            )
            self._conn.commit()
        return self._adapter(workspace, adapter_id) or {}

    # ── per-tenant secret vault (encrypted at rest) ──────────────────────────────────────────────
    @property
    def vault_enabled(self) -> bool:
        return self._vault is not None

    def put_secrets(self, workspace: str, secrets: dict[str, Any]) -> None:
        """Save (replace) a workspace's secret bundle, ENCRYPTED. Raises if the vault is unconfigured —
        the platform never stores a tenant's creds in plaintext as a fallback."""
        if self._vault is None:
            raise RuntimeError(
                "secret vault disabled — set NIL_VAULT_KEY to store tenant secrets"
            )
        if not workspace:
            raise ValueError("workspace is required")
        blob = self._vault._fernet.encrypt(  # encrypt here, persist ciphertext (vault store is the DB)
            json.dumps(secrets, separators=(",", ":")).encode("utf-8")
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO tenant_secrets (workspace, ciphertext, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(workspace) DO UPDATE SET ciphertext=excluded.ciphertext, "
                "updated_at=excluded.updated_at",
                (workspace, blob, _now()),
            )
            self._conn.commit()

    def get_secrets(self, workspace: str) -> dict[str, Any] | None:
        """Decrypt a workspace's secret bundle (by-tenant only), or None. Raises on tamper/wrong key."""
        if self._vault is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT ciphertext FROM tenant_secrets WHERE workspace = ?",
                (workspace,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(
            self._vault._fernet.decrypt(row["ciphertext"]).decode("utf-8")
        )

    def get_secret(self, workspace: str, name: str) -> Any | None:
        bundle = self.get_secrets(workspace)
        return bundle.get(name) if bundle else None

    def delete_secrets(self, workspace: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM tenant_secrets WHERE workspace = ?", (workspace,)
            )
            self._conn.commit()

    def activate_adapter(self, workspace: str, adapter_id: str) -> bool:
        """Make `adapter_id` the active backend for `workspace`, deactivating its siblings.
        Returns False if no such adapter is registered (so the caller can 404)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM adapters WHERE workspace = ? AND adapter_id = ?",
                (workspace, adapter_id),
            ).fetchone()
            if row is None:
                return False
            self._conn.execute(
                "UPDATE adapters SET active = CASE WHEN adapter_id = ? THEN 1 ELSE 0 END, "
                "updated_at = ? WHERE workspace = ?",
                (adapter_id, _now(), workspace),
            )
            self._conn.commit()
        return True

    def set_adapter_active(
        self, workspace: str, adapter_id: str, enabled: bool
    ) -> bool:
        """Enable/disable ONE adapter without touching its siblings (non-exclusive). This is what lets
        a workspace have several adapters active at once — e.g. PocketBase + Odoo for a cross-system
        automation. Returns False if no such adapter is registered."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE adapters SET active = ?, updated_at = ? WHERE workspace = ? AND adapter_id = ?",
                (1 if enabled else 0, _now(), workspace, adapter_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def active_adapters(self, workspace: str) -> list[dict[str, Any]]:
        """EVERY active adapter for a workspace (WITH bearer), newest-first. The runner builds a
        verb→adapter route map across these so one governed run can span backends (crm.* on Odoo,
        comms.* on the comms adapter). A single row ⇒ the plain single-adapter fast path."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_ADAPTER_COLS} FROM adapters WHERE workspace = ? AND active = 1 "
                "ORDER BY updated_at DESC",
                (workspace,),
            ).fetchall()
        return [dict(r) for r in rows]

    def active_adapter(self, workspace: str) -> dict[str, Any] | None:
        """The workspace's default active adapter for single-backend MCP routing (WITH bearer), or
        None. With several active, the most-recently-updated wins — composition addresses adapters by
        id, so multi-active never makes a plain propose/commit ambiguous."""
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_ADAPTER_COLS} FROM adapters WHERE workspace = ? AND active = 1 "
                "ORDER BY updated_at DESC LIMIT 1",
                (workspace,),
            ).fetchone()
        return dict(row) if row is not None else None

    def any_active_adapter(self) -> dict[str, Any] | None:
        """The single most-recently-active adapter across the whole registry (WITH bearer). Used by the
        approval executor: in a single-workspace deployment the held proposal was proposed on whatever
        backend is active, so committing the approved proposal there is correct."""
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_ADAPTER_COLS} FROM adapters WHERE active = 1 ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row is not None else None

    def proposal_workspace(self, proposal_id: str) -> str | None:
        """Derive the workspace for a proposal_id from its 'proposed' event. Returns None when no
        matching event exists (unknown proposal or event not yet ingested)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT workspace FROM events WHERE proposal = ? AND event = 'proposed' ORDER BY id DESC LIMIT 1",
                (proposal_id,),
            ).fetchone()
        return row["workspace"] if row is not None else None

    def approval(self, proposal_id: str) -> dict[str, Any] | None:
        """The full approval row (verb/tier/preview/status) — the executor reads the verb to scope the
        control-plane grant when it commits the approved proposal. Carries the plan link so the ordered
        executor can refuse a blocked step and materialize the next steps on a prerequisite's commit."""
        with self._lock:
            row = self._conn.execute(
                "SELECT proposal_id, status, verb, tier, preview, resolved, modifiable, "
                "plan_id, seq, depends_on, committed_id "
                "FROM approvals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        return self._shape_pending(row) if row is not None else None

    # ── governed dependent plans (ordered, linked approval cards) ────────────────────────────────
    def register_planned_step(
        self,
        proposal_id: str,
        *,
        plan_id: str,
        seq: int,
        depends_on: str | None,
        verb: str,
        args: dict[str, Any],
        handoff: dict[str, Any] | None = None,
        preview: Any = None,
        tier: str | None = None,
        workspace: str = "",
    ) -> dict[str, Any]:
        """Register a dependent step that is NOT yet proposed to the adapter (its handoff ref can't
        resolve until the prerequisite commits). Idempotent by synthetic proposal_id."""
        with self._lock:
            existing = self._conn.execute(
                "SELECT status FROM planned_steps WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
            if existing is not None:
                return {"proposal_id": proposal_id, "status": existing["status"]}
            self._conn.execute(
                "INSERT INTO planned_steps (proposal_id, plan_id, seq, depends_on, verb, args, "
                "handoff, preview, tier, workspace, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?)",
                (
                    proposal_id,
                    plan_id,
                    int(seq),
                    depends_on,
                    verb,
                    json.dumps(args, ensure_ascii=False),
                    json.dumps(handoff, ensure_ascii=False) if handoff is not None else None,
                    json.dumps(preview, ensure_ascii=False)
                    if isinstance(preview, (dict, list))
                    else preview,
                    tier,
                    workspace or "",
                    _now(),
                ),
            )
            self._conn.commit()
        return {"proposal_id": proposal_id, "status": "planned"}

    def record_committed(self, proposal_id: str, committed_id: str | None) -> None:
        """Record an approved step's backend result id so its dependents' handoff placeholders can
        resolve to the real id when they are materialized."""
        with self._lock:
            self._conn.execute(
                "UPDATE approvals SET committed_id = ? WHERE proposal_id = ?",
                (committed_id, proposal_id),
            )
            self._conn.commit()

    def next_planned_steps(self, plan_id: str, depends_on: str) -> list[dict[str, Any]]:
        """The plan's planned (not-yet-proposed) steps whose prerequisite is `depends_on` — the ones to
        materialize now that `depends_on` has committed. Args/handoff decoded from JSON."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT proposal_id, plan_id, seq, depends_on, verb, args, handoff, preview, tier, "
                "workspace FROM planned_steps WHERE plan_id = ? AND depends_on = ? AND status = 'planned' "
                "ORDER BY seq",
                (plan_id, depends_on),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            rec = dict(r)
            rec["args"] = _loads(rec.get("args"))
            rec["handoff"] = _loads(rec.get("handoff")) if rec.get("handoff") else {}
            if isinstance(rec.get("preview"), str) and rec["preview"]:
                try:
                    rec["preview"] = json.loads(rec["preview"])
                except json.JSONDecodeError:
                    pass
            out.append(rec)
        return out

    def promote_planned_step(
        self,
        synthetic_id: str,
        *,
        real_proposal_id: str,
        verb: str,
        tier: str | None,
        preview: Any,
        workspace: str,
        plan_id: str,
        seq: int,
        depends_on: str | None,
        resolved: dict[str, Any] | None = None,
        modifiable: Any = None,
    ) -> dict[str, Any]:
        """A planned step has been proposed for real → mark it materialized and register the real
        proposal as a HELD plan card (unblocked once its prerequisite is committed)."""
        with self._lock:
            self._conn.execute(
                "UPDATE planned_steps SET status = 'materialized' WHERE proposal_id = ?",
                (synthetic_id,),
            )
            self._conn.commit()
        return self.await_approval(
            real_proposal_id,
            verb=verb,
            tier=tier,
            preview=preview,
            workspace=workspace,
            resolved=resolved,
            modifiable=modifiable,
            plan_id=plan_id,
            seq=seq,
            depends_on=depends_on,
        )

    def cancel_plan(self, plan_id: str, *, reason: str = "plan cancelled") -> int:
        """Reject/cancel every un-decided step of a plan — both held approvals (pending) and planned
        (not-yet-proposed) steps — so rejecting ANY step leaves no orphan. Returns the count affected."""
        with self._lock:
            cur1 = self._conn.execute(
                "UPDATE approvals SET status = 'rejected', reason = ?, decided_at = ? "
                "WHERE plan_id = ? AND status = 'pending'",
                (reason, _now(), plan_id),
            )
            cur2 = self._conn.execute(
                "UPDATE planned_steps SET status = 'cancelled' "
                "WHERE plan_id = ? AND status = 'planned'",
                (plan_id,),
            )
            self._conn.commit()
            return cur1.rowcount + cur2.rowcount

    def plan_steps(self, plan_id: str) -> list[dict[str, Any]]:
        """All steps of a plan (held approvals + planned), ordered by seq — for inspection/tests."""
        with self._lock:
            appr = self._conn.execute(
                "SELECT proposal_id, verb, tier, plan_id, seq, depends_on, status, committed_id "
                "FROM approvals WHERE plan_id = ?",
                (plan_id,),
            ).fetchall()
            plan = self._conn.execute(
                "SELECT proposal_id, verb, tier, plan_id, seq, depends_on, status "
                "FROM planned_steps WHERE plan_id = ?",
                (plan_id,),
            ).fetchall()
        steps = [{**dict(r), "planned": False} for r in appr]
        steps.extend({**dict(r), "planned": True} for r in plan)
        steps.sort(key=lambda s: s.get("seq") or 0)
        return steps

    def list_adapters(self, workspace: str) -> list[dict[str, Any]]:
        """All registered adapters for a workspace (active first, then most-recent). Carries the
        bearer — the API layer redacts it for the public list endpoint."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_ADAPTER_COLS} FROM adapters WHERE workspace = ? "
                "ORDER BY active DESC, updated_at DESC",
                (workspace,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _adapter(self, workspace: str, adapter_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"SELECT {_ADAPTER_COLS} FROM adapters WHERE workspace = ? AND adapter_id = ?",
            (workspace, adapter_id),
        ).fetchone()
        return dict(row) if row is not None else None

    # ── automation registry (SSOT, append-only versions) ─────────────────────────────────────
    @staticmethod
    def _automation_row(row: sqlite3.Row) -> dict[str, Any]:
        """Deserialize the JSON columns (name/description/plan/trigger) back into dicts."""
        rec = dict(row)
        rec["name"] = _loads(rec.get("name"))
        rec["plan"] = _loads(rec.get("plan"))
        rec["trigger"] = _loads(rec.get("trigger"))
        rec["description"] = (
            _loads(rec["description"]) if rec.get("description") else None
        )
        # `source` is the canonical Cycle AST for kind='cycle'; None for plain automations.
        rec["source"] = _loads(rec["source"]) if rec.get("source") else None
        return rec

    def register_automation(
        self,
        *,
        workspace: str,
        automation_id: str,
        content_hash: str,
        name: dict[str, Any],
        plan: dict[str, Any],
        trigger: dict[str, Any],
        state: str = "draft",
        kind: str = "single",
        authored_by: str = "",
        description: dict[str, Any] | None = None,
        approved_by: str | None = None,
        source: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a new version. Re-registering an identical plan (same `content_hash` as the latest
        version) is an idempotent no-op — returns the existing row, no new version. Otherwise the
        prior latest version is archived and marked `superseded_by` the new version."""
        with self._lock:
            latest = self._conn.execute(
                "SELECT version, content_hash FROM automations "
                "WHERE workspace = ? AND automation_id = ? ORDER BY version DESC LIMIT 1",
                (workspace, automation_id),
            ).fetchone()
            if latest is not None and latest["content_hash"] == content_hash:
                row = self._conn.execute(
                    f"SELECT {_AUTOMATION_COLS} FROM automations "
                    "WHERE workspace = ? AND automation_id = ? AND version = ?",
                    (workspace, automation_id, latest["version"]),
                ).fetchone()
                return self._automation_row(row)
            version = (latest["version"] + 1) if latest is not None else 1
            if latest is not None:
                self._conn.execute(
                    "UPDATE automations SET superseded_by = ?, state = 'archived' "
                    "WHERE workspace = ? AND automation_id = ? AND version = ?",
                    (version, workspace, automation_id, latest["version"]),
                )
            self._conn.execute(
                "INSERT INTO automations (workspace, automation_id, version, content_hash, kind, name, "
                "description, plan, source, trigger, state, authored_by, approved_by, created_at, superseded_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                (
                    workspace,
                    automation_id,
                    version,
                    content_hash,
                    kind,
                    json.dumps(name, ensure_ascii=False),
                    json.dumps(description, ensure_ascii=False)
                    if description is not None
                    else None,
                    json.dumps(plan, ensure_ascii=False),
                    json.dumps(source, ensure_ascii=False) if source is not None else None,
                    json.dumps(trigger, ensure_ascii=False),
                    state,
                    authored_by,
                    approved_by,
                    _now(),
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                f"SELECT {_AUTOMATION_COLS} FROM automations "
                "WHERE workspace = ? AND automation_id = ? AND version = ?",
                (workspace, automation_id, version),
            ).fetchone()
        return self._automation_row(row)

    def get_automation(
        self, workspace: str, automation_id: str, version: int | None = None
    ) -> dict[str, Any] | None:
        """A specific version, or the latest (highest version) when `version` is None."""
        with self._lock:
            if version is None:
                row = self._conn.execute(
                    f"SELECT {_AUTOMATION_COLS} FROM automations "
                    "WHERE workspace = ? AND automation_id = ? ORDER BY version DESC LIMIT 1",
                    (workspace, automation_id),
                ).fetchone()
            else:
                row = self._conn.execute(
                    f"SELECT {_AUTOMATION_COLS} FROM automations "
                    "WHERE workspace = ? AND automation_id = ? AND version = ?",
                    (workspace, automation_id, version),
                ).fetchone()
        return self._automation_row(row) if row is not None else None

    def list_automations(self, workspace: str) -> list[dict[str, Any]]:
        """The latest version of every automation in the workspace, by automation_id."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_AUTOMATION_COLS} FROM automations a WHERE workspace = ? AND version = "
                "(SELECT MAX(version) FROM automations b "
                " WHERE b.workspace = a.workspace AND b.automation_id = a.automation_id) "
                "ORDER BY automation_id",
                (workspace,),
            ).fetchall()
        return [self._automation_row(r) for r in rows]

    def all_automations(self) -> list[dict[str, Any]]:
        """Latest version of every automation across ALL workspaces — for the dashboard."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_AUTOMATION_COLS} FROM automations a WHERE version = "
                "(SELECT MAX(version) FROM automations b "
                " WHERE b.workspace = a.workspace AND b.automation_id = a.automation_id) "
                "ORDER BY workspace, automation_id"
            ).fetchall()
        return [self._automation_row(r) for r in rows]

    def active_automations(self) -> list[dict[str, Any]]:
        """Every armed automation across all workspaces (state='active'). The scheduler scans these.
        The supersede-on-edit invariant means the active version is always the latest one."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_AUTOMATION_COLS} FROM automations WHERE state = 'active' "
                "ORDER BY workspace, automation_id"
            ).fetchall()
        return [self._automation_row(r) for r in rows]

    def set_automation_state(
        self,
        workspace: str,
        automation_id: str,
        version: int,
        state: str,
        *,
        approved_by: str | None = None,
    ) -> bool:
        """Transition one version's lifecycle state (draft→pending_approval→active⇄paused→archived).
        Records `approved_by` when supplied. Returns False if no such version exists."""
        with self._lock:
            if approved_by is not None:
                cur = self._conn.execute(
                    "UPDATE automations SET state = ?, approved_by = ? "
                    "WHERE workspace = ? AND automation_id = ? AND version = ?",
                    (state, approved_by, workspace, automation_id, version),
                )
            else:
                cur = self._conn.execute(
                    "UPDATE automations SET state = ? "
                    "WHERE workspace = ? AND automation_id = ? AND version = ?",
                    (state, workspace, automation_id, version),
                )
            self._conn.commit()
            return cur.rowcount > 0

    # ── capability + strategy registries (SSOT, append-only versions — plan B1) ──────────────
    # One generic engine, two tables: the disciplines (idempotent same-hash register, supersede
    # never edit, workspace-pinned reads) are identical by construction, so they cannot drift.

    @staticmethod
    def _object_row(row: sqlite3.Row) -> dict[str, Any]:
        """Deserialize a registry row: `body_json` (the canonical AST) comes back as `body`."""
        rec = dict(row)
        rec["body"] = _loads(rec.pop("body_json", None))
        return rec

    def _register_object(
        self,
        table: str,
        id_col: str,
        *,
        workspace: str,
        object_id: str,
        content_hash: str,
        body: dict[str, Any],
        state: str = "draft",
    ) -> dict[str, Any]:
        """Append a new version. Re-registering an identical body (same `content_hash` as the
        latest version) is an idempotent no-op — returns the existing row, no new version.
        Otherwise the prior latest is marked `superseded_by` the new version and `deprecated`."""
        if not workspace:
            raise ValueError("workspace is required")  # fail closed: no tenant, no write
        cols = f"workspace, {id_col}, version, content_hash, body_json, state, created_at, superseded_by"
        with self._lock:
            latest = self._conn.execute(
                f"SELECT version, content_hash FROM {table} "
                f"WHERE workspace = ? AND {id_col} = ? ORDER BY version DESC LIMIT 1",
                (workspace, object_id),
            ).fetchone()
            if latest is not None and latest["content_hash"] == content_hash:
                row = self._conn.execute(
                    f"SELECT {cols} FROM {table} "
                    f"WHERE workspace = ? AND {id_col} = ? AND version = ?",
                    (workspace, object_id, latest["version"]),
                ).fetchone()
                return self._object_row(row)
            version = (latest["version"] + 1) if latest is not None else 1
            if latest is not None:
                self._conn.execute(
                    f"UPDATE {table} SET superseded_by = ?, state = 'deprecated' "
                    f"WHERE workspace = ? AND {id_col} = ? AND version = ?",
                    (version, workspace, object_id, latest["version"]),
                )
            self._conn.execute(
                f"INSERT INTO {table} (workspace, {id_col}, version, content_hash, body_json, "
                "state, created_at, superseded_by) VALUES (?,?,?,?,?,?,?,NULL)",
                (
                    workspace,
                    object_id,
                    version,
                    content_hash,
                    json.dumps(body, ensure_ascii=False),
                    state,
                    _now(),
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                f"SELECT {cols} FROM {table} WHERE workspace = ? AND {id_col} = ? AND version = ?",
                (workspace, object_id, version),
            ).fetchone()
        return self._object_row(row)

    def _get_object(
        self, table: str, id_col: str, workspace: str, object_id: str, version: int | None = None
    ) -> dict[str, Any] | None:
        """A specific version, or the latest when `version` is None. Workspace-pinned: an id that
        exists only in another tenant is None here (fail closed)."""
        cols = f"workspace, {id_col}, version, content_hash, body_json, state, created_at, superseded_by"
        with self._lock:
            if version is None:
                row = self._conn.execute(
                    f"SELECT {cols} FROM {table} "
                    f"WHERE workspace = ? AND {id_col} = ? ORDER BY version DESC LIMIT 1",
                    (workspace, object_id),
                ).fetchone()
            else:
                row = self._conn.execute(
                    f"SELECT {cols} FROM {table} "
                    f"WHERE workspace = ? AND {id_col} = ? AND version = ?",
                    (workspace, object_id, version),
                ).fetchone()
        return self._object_row(row) if row is not None else None

    def _list_objects(self, table: str, id_col: str, workspace: str) -> list[dict[str, Any]]:
        """The latest version of every object in the workspace, by id."""
        cols = f"workspace, {id_col}, version, content_hash, body_json, state, created_at, superseded_by"
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {cols} FROM {table} a WHERE workspace = ? AND version = "
                f"(SELECT MAX(version) FROM {table} b "
                f" WHERE b.workspace = a.workspace AND b.{id_col} = a.{id_col}) "
                f"ORDER BY {id_col}",
                (workspace,),
            ).fetchall()
        return [self._object_row(r) for r in rows]

    def _set_object_state(
        self, table: str, id_col: str, workspace: str, object_id: str, version: int, state: str
    ) -> bool:
        """Transition one version's lifecycle state (draft -> published -> deprecated). Returns
        False if no such version exists in THIS workspace."""
        if state not in ("draft", "published", "deprecated"):
            raise ValueError("state must be draft|published|deprecated")
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE {table} SET state = ? WHERE workspace = ? AND {id_col} = ? AND version = ?",
                (state, workspace, object_id, version),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def register_capability(
        self,
        *,
        workspace: str,
        capability_id: str,
        content_hash: str,
        body: dict[str, Any],
        state: str = "draft",
    ) -> dict[str, Any]:
        return self._register_object(
            "capabilities",
            "capability_id",
            workspace=workspace,
            object_id=capability_id,
            content_hash=content_hash,
            body=body,
            state=state,
        )

    def get_capability(
        self, workspace: str, capability_id: str, version: int | None = None
    ) -> dict[str, Any] | None:
        return self._get_object("capabilities", "capability_id", workspace, capability_id, version)

    def list_capabilities(self, workspace: str) -> list[dict[str, Any]]:
        return self._list_objects("capabilities", "capability_id", workspace)

    def set_capability_state(
        self, workspace: str, capability_id: str, version: int, state: str
    ) -> bool:
        return self._set_object_state(
            "capabilities", "capability_id", workspace, capability_id, version, state
        )

    def register_strategy(
        self,
        *,
        workspace: str,
        strategy_id: str,
        content_hash: str,
        body: dict[str, Any],
        state: str = "draft",
    ) -> dict[str, Any]:
        return self._register_object(
            "strategies",
            "strategy_id",
            workspace=workspace,
            object_id=strategy_id,
            content_hash=content_hash,
            body=body,
            state=state,
        )

    def get_strategy(
        self, workspace: str, strategy_id: str, version: int | None = None
    ) -> dict[str, Any] | None:
        return self._get_object("strategies", "strategy_id", workspace, strategy_id, version)

    def list_strategies(self, workspace: str) -> list[dict[str, Any]]:
        return self._list_objects("strategies", "strategy_id", workspace)

    def set_strategy_state(
        self, workspace: str, strategy_id: str, version: int, state: str
    ) -> bool:
        return self._set_object_state(
            "strategies", "strategy_id", workspace, strategy_id, version, state
        )

    # ── automation runs (P2 dispatcher) ──────────────────────────────────────────────────────
    def start_run(
        self,
        run_id: str,
        *,
        workspace: str,
        automation_id: str,
        version: int,
        content_hash: str,
        fired_by: str = "",
    ) -> bool:
        """Open a run row (state=running). Returns False if `run_id` already exists — the caller must
        then treat the fire as an idempotent replay and NOT re-execute (a re-delivered trigger)."""
        with self._lock:
            if self._conn.execute(
                "SELECT 1 FROM automation_runs WHERE run_id = ?", (run_id,)
            ).fetchone():
                return False
            started = _now()
            business_ref = self._mint_business_ref(workspace, automation_id, started, run_id)
            # correlation_id defaults to business_ref (business-threads-plan §4.1): the thread's
            # durable join key. Later side-channels (comms reply-token, order_ref) correlate to it;
            # the aggregator additionally reconciles against the run's context.order_ref.
            correlation_id = business_ref
            self._conn.execute(
                "INSERT INTO automation_runs (run_id, workspace, automation_id, version, "
                "content_hash, fired_by, state, started_at, business_ref, correlation_id) "
                "VALUES (?,?,?,?,?,?, 'running', ?, ?, ?)",
                (
                    run_id,
                    workspace,
                    automation_id,
                    version,
                    content_hash,
                    fired_by,
                    started,
                    business_ref,
                    correlation_id,
                ),
            )
            self._conn.commit()
        return True

    # A run's human THREAD identity — PO-2026-00145, not cyc_order:v1:… (business-threads-plan.md).
    # Prefix per automation; year from the start time; sequence = count-so-far + 1 for that automation.
    _REF_PREFIXES = {"cyc_order": "PO", "sendmessagecycle": "MSG"}

    def _mint_business_ref(
        self, workspace: str, automation_id: str, started_at: str, run_id: str
    ) -> str:
        """Deterministic, human-friendly. FAIL-SAFE: any error falls back to run_id — minting a nice
        label must NEVER block a run from starting (that would be a runtime outage for a cosmetic)."""
        try:
            # Monotonic, gap-free sequence (W1) — NOT COUNT(*) (racy under concurrency; reused a ref
            # after a run was deleted). Seed `next` on first use from the current run count so live
            # DBs continue exactly where COUNT-minting left off (no collision with existing refs),
            # then increment atomically. start_run holds self._lock, so read-then-update is atomic.
            self._conn.execute(
                "INSERT INTO ref_sequences (workspace, automation_id, next) "
                "SELECT ?, ?, (SELECT COUNT(*) FROM automation_runs "
                "              WHERE workspace = ? AND automation_id = ?) + 1 "
                "WHERE NOT EXISTS (SELECT 1 FROM ref_sequences "
                "                  WHERE workspace = ? AND automation_id = ?)",
                (workspace, automation_id, workspace, automation_id, workspace, automation_id),
            )
            seq = int(
                self._conn.execute(
                    "SELECT next FROM ref_sequences WHERE workspace = ? AND automation_id = ?",
                    (workspace, automation_id),
                ).fetchone()[0]
            )
            self._conn.execute(
                "UPDATE ref_sequences SET next = next + 1 "
                "WHERE workspace = ? AND automation_id = ?",
                (workspace, automation_id),
            )
            prefix = self._REF_PREFIXES.get(automation_id) or (
                "".join(ch for ch in automation_id.upper() if ch.isalnum())[:6] or "THR"
            )
            year = (started_at or "")[:4] or "0000"
            return f"{prefix}-{year}-{seq:05d}"
        except Exception:  # noqa: BLE001 — never let a label mint fail the run
            return run_id

    def finish_run(self, run_id: str, state: str, trace: dict[str, Any] | None) -> bool:
        """Close a run with its terminal state and the executor trace. Returns False if unknown."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE automation_runs SET state = ?, trace = ?, ended_at = ? WHERE run_id = ?",
                (
                    state,
                    json.dumps(trace, ensure_ascii=False)
                    if trace is not None
                    else None,
                    _now(),
                    run_id,
                ),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT run_id, workspace, automation_id, version, content_hash, fired_by, state, "
                "trace, started_at, ended_at, business_ref, correlation_id "
                "FROM automation_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        rec = dict(row)
        rec["trace"] = _loads(rec.get("trace")) if rec.get("trace") else None
        return rec

    def list_runs(
        self, workspace: str, automation_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Newest-first run history for one automation (trace omitted — fetch via get_run)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id, workspace, automation_id, version, content_hash, fired_by, state, "
                "started_at, ended_at, business_ref, correlation_id FROM automation_runs "
                "WHERE workspace = ? AND automation_id = ? ORDER BY started_at DESC LIMIT ?",
                (workspace, automation_id, max(1, min(limit, 500))),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── run checkpoints (B5: the rollback markers) ────────────────────────────────────────────
    def record_checkpoint(
        self,
        run_id: str,
        *,
        name: str,
        node_id: str = "",
        workspace: str = "",
        committed: list[str] | None = None,
        at: str | None = None,
    ) -> bool:
        """Persist one walked checkpoint marker. Idempotent by (run_id, name) — a re-recorded
        marker (resumed segment, re-delivered trace) keeps the original row. Returns True when
        the row is new."""
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO run_checkpoints "
                "(run_id, name, node_id, workspace, committed, at) VALUES (?,?,?,?,?,?)",
                (
                    run_id,
                    name,
                    node_id or "",
                    workspace or "",
                    json.dumps(list(committed or []), ensure_ascii=False),
                    at or _now(),
                ),
            )
            self._conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _checkpoint_row(row: sqlite3.Row) -> dict[str, Any]:
        rec = dict(row)
        try:
            parsed = json.loads(rec.get("committed") or "[]")
        except (ValueError, TypeError):
            parsed = []
        rec["committed"] = parsed if isinstance(parsed, list) else []
        return rec

    def get_checkpoint(self, run_id: str, name: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT run_id, name, node_id, workspace, committed, at FROM run_checkpoints "
                "WHERE run_id = ? AND name = ?",
                (run_id, name),
            ).fetchone()
        return self._checkpoint_row(row) if row is not None else None

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        """Every marker one run walked, in walk order."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id, name, node_id, workspace, committed, at FROM run_checkpoints "
                "WHERE run_id = ? ORDER BY at",
                (run_id,),
            ).fetchall()
        return [self._checkpoint_row(r) for r in rows]

    # ── parked runs (gates + wait_for_event resume across restarts) ──────────────────────────
    _PARK_COLS = (
        "run_id, node_id, kind, workspace, automation_id, version, proposal_id, "
        "on_event, match, deadline, context, status, created_at, settled_at"
    )

    @staticmethod
    def _park_row(row: sqlite3.Row) -> dict[str, Any]:
        rec = dict(row)
        rec["context"] = _loads(rec.get("context"))
        rec["match"] = _loads(rec.get("match")) if rec.get("match") else {}
        return rec

    def park_run(
        self,
        run_id: str,
        *,
        node_id: str,
        kind: str = "approval",
        workspace: str = "",
        automation_id: str = "",
        version: int = 0,
        proposal_id: str | None = None,
        on_event: str | None = None,
        match: dict[str, Any] | None = None,
        deadline: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one parked run (idempotent by (run_id, node_id) — a re-delivered park keeps the
        existing row and its status). The row is everything a resume needs: the pinned automation
        version to reload the plan, the node to continue after, and the context at park time."""
        with self._lock:
            existing = self._conn.execute(
                "SELECT status FROM parked_runs WHERE run_id = ? AND node_id = ?",
                (run_id, node_id),
            ).fetchone()
            if existing is not None:
                return {"run_id": run_id, "node_id": node_id, "status": existing["status"]}
            self._conn.execute(
                "INSERT INTO parked_runs (run_id, node_id, kind, workspace, automation_id, "
                "version, proposal_id, on_event, match, deadline, context, status, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?, 'waiting', ?)",
                (
                    run_id,
                    node_id,
                    kind,
                    workspace or "",
                    automation_id or "",
                    int(version),
                    proposal_id,
                    on_event,
                    json.dumps(match, ensure_ascii=False) if match is not None else None,
                    deadline,
                    json.dumps(context or {}, ensure_ascii=False),
                    _now(),
                ),
            )
            self._conn.commit()
        return {"run_id": run_id, "node_id": node_id, "status": "waiting"}

    def parked_for_proposal(self, proposal_id: str) -> list[dict[str, Any]]:
        """Every WAITING parked run gated on `proposal_id` — the rows a decision must resume."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {self._PARK_COLS} FROM parked_runs "
                "WHERE proposal_id = ? AND status = 'waiting' ORDER BY created_at",
                (proposal_id,),
            ).fetchall()
        return [self._park_row(r) for r in rows]

    def waiting_parks(
        self, *, kind: str | None = None, workspace: str | None = None
    ) -> list[dict[str, Any]]:
        """WAITING parked runs, optionally filtered by kind and/or workspace (event dispatch scopes
        to the envelope's workspace so one tenant's event never wakes another tenant's run)."""
        clauses, params = ["status = 'waiting'"], []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if workspace is not None:
            clauses.append("workspace = ?")
            params.append(workspace)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {self._PARK_COLS} FROM parked_runs WHERE {' AND '.join(clauses)} "
                "ORDER BY created_at",
                params,
            ).fetchall()
        return [self._park_row(r) for r in rows]

    def due_parks(self, now_iso: str) -> list[dict[str, Any]]:
        """WAITING parked runs whose deadline has passed as of `now_iso` — the tick resumes each at
        its timeout route. ISO-UTC strings compare lexicographically."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {self._PARK_COLS} FROM parked_runs "
                "WHERE status = 'waiting' AND deadline IS NOT NULL AND deadline <= ? "
                "ORDER BY deadline",
                (now_iso,),
            ).fetchall()
        return [self._park_row(r) for r in rows]

    def settle_park(self, run_id: str, node_id: str, status: str) -> bool:
        """CLAIM a waiting park (waiting → resumed/rejected/timed_out). Returns False when it was
        already settled — the single-resume guard, so a re-delivered decision/event never resumes
        the same run twice."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE parked_runs SET status = ?, settled_at = ? "
                "WHERE run_id = ? AND node_id = ? AND status = 'waiting'",
                (status, _now(), run_id, node_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    # ── strategy signature slots (plan B3 — one subject, N signature slots) ──────────────────
    _SIG_COLS = (
        "execution_id, unit_idx, unit_key, stage, by_kind, role, distinct_from, quorum_k, "
        "quorum_distinct, workspace, actor, decided_at, status, deadline, timeout_route, created_at"
    )

    @staticmethod
    def _sig_row(row: sqlite3.Row) -> dict[str, Any]:
        rec = dict(row)
        # NOT _loads(): that helper is dict-only, and distinct_from is a JSON LIST.
        try:
            parsed = json.loads(rec.get("distinct_from") or "[]")
        except (ValueError, TypeError):
            parsed = []
        rec["distinct_from"] = parsed if isinstance(parsed, list) else []
        rec["timeout_route"] = (
            _loads(rec.get("timeout_route")) if rec.get("timeout_route") else None
        )
        rec["quorum_distinct"] = bool(rec.get("quorum_distinct"))
        return rec

    def add_signature_slot(
        self,
        execution_id: str,
        *,
        unit_idx: int,
        unit_key: str,
        stage: int,
        by_kind: str,
        role: str,
        distinct_from: list[str] | tuple[str, ...] = (),
        quorum_k: int = 1,
        quorum_distinct: bool = False,
        workspace: str = "",
        status: str = "pending",
        actor: str | None = None,
        decided_at: str | None = None,
        deadline: str | None = None,
        timeout_route: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert one signature slot (idempotent by (execution_id, unit_idx) — a re-delivered
        materialization keeps the existing row and its status)."""
        with self._lock:
            existing = self._conn.execute(
                "SELECT status FROM strategy_signatures WHERE execution_id = ? AND unit_idx = ?",
                (execution_id, unit_idx),
            ).fetchone()
            if existing is not None:
                return {"execution_id": execution_id, "unit_idx": unit_idx, "status": existing["status"]}
            self._conn.execute(
                "INSERT INTO strategy_signatures (execution_id, unit_idx, unit_key, stage, by_kind, "
                "role, distinct_from, quorum_k, quorum_distinct, workspace, actor, decided_at, "
                "status, deadline, timeout_route, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    execution_id,
                    int(unit_idx),
                    unit_key,
                    int(stage),
                    by_kind,
                    role,
                    json.dumps(list(distinct_from), ensure_ascii=False),
                    int(quorum_k),
                    1 if quorum_distinct else 0,
                    workspace or "",
                    actor,
                    decided_at,
                    status,
                    deadline,
                    json.dumps(timeout_route, ensure_ascii=False)
                    if timeout_route is not None
                    else None,
                    _now(),
                ),
            )
            self._conn.commit()
        return {"execution_id": execution_id, "unit_idx": unit_idx, "status": status}

    def signature_slots(self, execution_id: str) -> list[dict[str, Any]]:
        """Every slot of one execution, in unit order — the full signature audit trail."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {self._SIG_COLS} FROM strategy_signatures "
                "WHERE execution_id = ? ORDER BY unit_idx",
                (execution_id,),
            ).fetchall()
        return [self._sig_row(r) for r in rows]

    def set_signature_status(
        self,
        execution_id: str,
        unit_idx: int,
        status: str,
        *,
        actor: str | None = None,
        expect: str | tuple[str, ...] = ("pending", "planned"),
    ) -> bool:
        """Guarded slot transition (only from `expect`) — the single-decision guard, so a
        re-delivered signature never double-signs a slot. Stamps actor/decided_at on a decision."""
        expected = (expect,) if isinstance(expect, str) else tuple(expect)
        ph = ",".join("?" * len(expected))
        with self._lock:
            if actor is not None:
                cur = self._conn.execute(
                    f"UPDATE strategy_signatures SET status = ?, actor = ?, decided_at = ? "
                    f"WHERE execution_id = ? AND unit_idx = ? AND status IN ({ph})",
                    (status, actor, _now(), execution_id, unit_idx, *expected),
                )
            else:
                cur = self._conn.execute(
                    f"UPDATE strategy_signatures SET status = ? "
                    f"WHERE execution_id = ? AND unit_idx = ? AND status IN ({ph})",
                    (status, execution_id, unit_idx, *expected),
                )
            self._conn.commit()
            return cur.rowcount > 0

    def activate_signature_slot(
        self, execution_id: str, unit_idx: int, *, deadline: str | None
    ) -> bool:
        """Materialize a planned slot (planned → pending), stamping its deadline NOW — a Seq
        stage's timeout clock starts when the stage becomes actionable, not at prepare time."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE strategy_signatures SET status = 'pending', deadline = ? "
                "WHERE execution_id = ? AND unit_idx = ? AND status = 'planned'",
                (deadline, execution_id, unit_idx),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def next_signature_unit_idx(self, execution_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(unit_idx) AS m FROM strategy_signatures WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        return int(row["m"]) + 1 if row is not None and row["m"] is not None else 0

    def due_signature_slots(self, now_iso: str) -> list[dict[str, Any]]:
        """PENDING slots whose deadline has passed — the /automations/tick sweep escalates or
        rejects each per its declared route (the parked_runs deadline pattern)."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {self._SIG_COLS} FROM strategy_signatures "
                "WHERE status = 'pending' AND deadline IS NOT NULL AND deadline <= ? "
                "ORDER BY deadline",
                (now_iso,),
            ).fetchall()
        return [self._sig_row(r) for r in rows]

    # ── prepared executions (plan B2 — the strategy interpreter's subject) ────────────────────
    _PREPARED_COLS = (
        "prepared_id, workspace, capability_id, capability_version, content_hash, strategy_id, "
        "strategy_version, strategy_hash, inputs, modifiable, prepared_by, branch, risk, "
        "reversibility, compensation, affected_systems, status, reason, commit_result, "
        "created_at, decided_at"
    )

    @staticmethod
    def _prepared_row(row: sqlite3.Row) -> dict[str, Any]:
        rec = dict(row)
        rec["inputs"] = _loads(rec.get("inputs"))
        rec["commit_result"] = _loads(rec.get("commit_result")) if rec.get("commit_result") else None
        for key in ("modifiable", "affected_systems"):  # JSON LISTS — _loads is dict-only
            try:
                parsed = json.loads(rec.get(key) or "[]")
            except (ValueError, TypeError):
                parsed = []
            rec[key] = parsed if isinstance(parsed, list) else []
        return rec

    def create_prepared(
        self,
        prepared_id: str,
        *,
        workspace: str,
        capability_id: str,
        capability_version: int,
        content_hash: str,
        strategy_id: str,
        strategy_version: int,
        strategy_hash: str,
        inputs: dict[str, Any],
        modifiable: list[str],
        prepared_by: str,
        branch: str | None = None,
        risk: str = "HIGH",
        reversibility: str = "IRREVERSIBLE",
        compensation: str | None = None,
        affected_systems: list[str] | None = None,
        status: str = "pending",
    ) -> dict[str, Any]:
        """Persist one prepared execution. Fail closed: no workspace or no preparer, no row —
        SoD needs a stamped preparer and every read is workspace-pinned."""
        if not workspace:
            raise ValueError("workspace is required")
        if not prepared_by:
            raise ValueError("prepared_by is required (SoD stamps the preparer at prepare time)")
        with self._lock:
            self._conn.execute(
                "INSERT INTO prepared_executions (prepared_id, workspace, capability_id, "
                "capability_version, content_hash, strategy_id, strategy_version, strategy_hash, "
                "inputs, modifiable, prepared_by, branch, risk, reversibility, compensation, "
                "affected_systems, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    prepared_id,
                    workspace,
                    capability_id,
                    int(capability_version),
                    content_hash,
                    strategy_id,
                    int(strategy_version),
                    strategy_hash,
                    json.dumps(inputs, ensure_ascii=False),
                    json.dumps(list(modifiable), ensure_ascii=False),
                    prepared_by,
                    branch,
                    risk,
                    reversibility,
                    compensation,
                    json.dumps(list(affected_systems or []), ensure_ascii=False),
                    status,
                    _now(),
                ),
            )
            self._conn.commit()
        return self.get_prepared(prepared_id, workspace) or {}

    def list_prepared(
        self, workspace: str, *, status: str | None = None
    ) -> list[dict[str, Any]]:
        """The workspace's prepared executions, newest first — the Decisions feed. Fail
        closed: no workspace, no rows. Optional status filter (pending|approved|committed|
        rejected)."""
        if not workspace:
            return []
        where = "workspace = ?" + (" AND status = ?" if status else "")
        params: tuple[Any, ...] = (workspace, status) if status else (workspace,)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {self._PREPARED_COLS} FROM prepared_executions WHERE {where} "
                "ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [self._prepared_row(r) for r in rows]

    def get_prepared(
        self, prepared_id: str, workspace: str | None = None
    ) -> dict[str, Any] | None:
        """One prepared execution — workspace-pinned when a workspace is given (fail closed:
        another tenant's prepared_id is None here)."""
        where = "prepared_id = ?" + (" AND workspace = ?" if workspace is not None else "")
        params: tuple[Any, ...] = (
            (prepared_id, workspace) if workspace is not None else (prepared_id,)
        )
        with self._lock:
            row = self._conn.execute(
                f"SELECT {self._PREPARED_COLS} FROM prepared_executions WHERE {where}", params
            ).fetchone()
        return self._prepared_row(row) if row is not None else None

    def set_prepared_status(
        self,
        prepared_id: str,
        status: str,
        *,
        expect: str | tuple[str, ...] = ("pending", "approved"),
        reason: str = "",
    ) -> bool:
        """Guarded lifecycle transition (pending → approved → committed | rejected). Stamps
        decided_at and, on rejection, the reason (audit). Returns False when the row was not in
        an expected state — the single-decision guard, mirroring `decide`/`settle_park`."""
        expected = (expect,) if isinstance(expect, str) else tuple(expect)
        ph = ",".join("?" * len(expected))
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE prepared_executions SET status = ?, decided_at = ?, "
                f"reason = CASE WHEN ? != '' THEN ? ELSE reason END "
                f"WHERE prepared_id = ? AND status IN ({ph})",
                (status, _now(), reason, reason, prepared_id, *expected),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def update_prepared_inputs(
        self, prepared_id: str, inputs: dict[str, Any], *, branch: str | None
    ) -> bool:
        """A material edit amended the subject's inputs (already validated by the caller against
        the contract + modifiable set). The signature voiding lives with the interpreter."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE prepared_executions SET inputs = ?, branch = ? "
                "WHERE prepared_id = ? AND status = 'pending'",
                (json.dumps(inputs, ensure_ascii=False), branch, prepared_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def record_prepared_commit(
        self, prepared_id: str, result: dict[str, Any], status: str
    ) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE prepared_executions SET commit_result = ?, status = ?, decided_at = ? "
                "WHERE prepared_id = ?",
                (json.dumps(result, ensure_ascii=False), status, _now(), prepared_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    # ── scheduled executions (plan B7 nil_schedule — one-shot rows, swept by the tick) ────────
    _SCHED_COLS = (
        "schedule_id, prepared_id, workspace, fire_at, status, result, created_at, settled_at"
    )

    @staticmethod
    def _sched_row(row: sqlite3.Row) -> dict[str, Any]:
        rec = dict(row)
        raw = rec.get("result")
        rec["result"] = json.loads(raw) if raw else None
        return rec

    def create_scheduled_execution(
        self, schedule_id: str, *, prepared_id: str, workspace: str, fire_at: str
    ) -> dict[str, Any]:
        """Register a one-shot schedule row. Idempotent on (prepared_id, fire_at) while pending —
        re-scheduling the same card for the same moment returns the existing row, never a
        duplicate fire."""
        if not workspace:
            raise ValueError("workspace is required")  # fail closed: no tenant, no schedule
        with self._lock:
            existing = self._conn.execute(
                f"SELECT {self._SCHED_COLS} FROM scheduled_executions "
                "WHERE prepared_id = ? AND fire_at = ? AND status = 'pending'",
                (prepared_id, fire_at),
            ).fetchone()
            if existing is not None:
                return self._sched_row(existing)
            self._conn.execute(
                "INSERT INTO scheduled_executions (schedule_id, prepared_id, workspace, fire_at, "
                "status, result, created_at, settled_at) VALUES (?,?,?,?,'pending',NULL,?,NULL)",
                (schedule_id, prepared_id, workspace, fire_at, _now()),
            )
            self._conn.commit()
            row = self._conn.execute(
                f"SELECT {self._SCHED_COLS} FROM scheduled_executions WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchone()
        return self._sched_row(row)

    def get_scheduled_execution(self, schedule_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {self._SCHED_COLS} FROM scheduled_executions WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchone()
        return self._sched_row(row) if row is not None else None

    def list_scheduled_executions(self, workspace: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {self._SCHED_COLS} FROM scheduled_executions "
                "WHERE workspace = ? ORDER BY fire_at",
                (workspace,),
            ).fetchall()
        return [self._sched_row(r) for r in rows]

    def due_scheduled_executions(self, now_iso: str) -> list[dict[str, Any]]:
        """PENDING schedule rows whose fire_at has passed as of `now_iso` — the tick fires each
        through the same execute path a human-driven /execute uses. ISO-UTC strings compare
        lexicographically (the due_parks discipline)."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {self._SCHED_COLS} FROM scheduled_executions "
                "WHERE status = 'pending' AND fire_at <= ? ORDER BY fire_at",
                (now_iso,),
            ).fetchall()
        return [self._sched_row(r) for r in rows]

    def settle_scheduled_execution(
        self, schedule_id: str, status: str, result: dict[str, Any] | None = None
    ) -> bool:
        """CLAIM a pending schedule (pending → fired/refused/cancelled), recording the outcome.
        Returns False when it was already settled — the single-fire guard (settle_park's
        discipline), so overlapping ticks never fire the same schedule twice."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE scheduled_executions SET status = ?, result = ?, settled_at = ? "
                "WHERE schedule_id = ? AND status = 'pending'",
                (
                    status,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    _now(),
                    schedule_id,
                ),
            )
            self._conn.commit()
            return cur.rowcount > 0
