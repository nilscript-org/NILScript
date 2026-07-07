# Wave 7: Communication Engine — Correlation Cascade & Thread Eventing

**Status:** Designed & Stubbed (Phase 1) · **Scope:** nilscript control-plane (comms layer)

Wave 7 completes the communication loop for Business Threads: inbound messages deterministically correlate to their originating threads, passive events resume parked thread state, ambiguous correlations escalate to a review queue, and outbound messages are governance-routed through Wosool.

---

## 0. Architecture Overview

The Communication Engine solves **thread correlation**: routing an inbound email/WhatsApp/SMS to the exact Business Thread it belongs to, even when multiple threads exist with similar metadata.

```
INBOUND MESSAGE
      ↓
  CORRELATION ENGINE (5-layer cascade)
      ↓
      ├─→ L1: Transport IDs (Message-ID, WhatsApp msg_id)         [confidence: 1.0]
      ├─→ L2: BCONV (Business Conversation ID)                   [confidence: 1.0]
      ├─→ L3: Business Keys (order_ref, ticket_id)               [confidence: 0.95]
      ├─→ L4: Participant Matching (sender role, authority)      [confidence: 0.85]
      └─→ L5: Temporal Causality (thread state, event criteria)  [confidence: 0.75]
      ↓
  [Single Match]        [Ambiguous: Multiple Threads]
      ↓                              ↓
  PASSIVE EVENT              REVIEW QUEUE
  (resume thread)            (ask human)
      ↓                              ↓
  THREAD TIMELINE         [Human picks thread]
  + THREAD RESUME              ↓
                           EVENT + RESUME
```

---

## 1. Correlation Engine: 5-Layer Cascade

**File:** `nilscript/comms/correlation_engine.py`

The CorrelationEngine routes messages through a deterministic, high-to-low-confidence cascade. Each layer is independent; if a layer matches, it returns immediately (no further layers). If ambiguous (multiple matches), it escalates.

### Layer 1: Transport IDs (confidence = 1.0)

**Match on:** Message-ID, In-Reply-To header (SMTP); WhatsApp msg_id; SMS timestamp.

**Rationale:** Transport IDs are channel-native, deduped at the gateway, and never reused within a workspace.

**Example:**
```
Inbound email with In-Reply-To: <original@example.com>
→ Lookup original in transport_index
→ Find thread_id = "thread-po-145"
→ Confidence = 0.95 (In-Reply-To is slightly weaker than Message-ID)
```

**Implementation:**
- `add_transport_marker(marker, thread_id)` — Register a marker so future replies are deduped
- `transport_index` — In-memory dict or database table mapping transport IDs → thread

### Layer 2: Conversation Identity (BCONV) (confidence = 1.0)

**Match on:** BCONV (Business Conversation ID) — the durable thread marker stamped on all outbound.

**Rationale:** BCONV is mint-once per thread, immutable, and visible to humans in subject/body. If present, it's a perfect match.

**Example:**
```
Inbound email subject: "[BCONV-ws_acme-2026-00145] RE: PO Update"
→ Extract BCONV-ws_acme-2026-00145
→ Lookup in BCONV registry
→ Find thread_id
→ Confidence = 1.0 (perfect)
```

**Implementation:**
- `_match_layer_2_conversation(conversation_dict)` — Look up BCONV in thread registry
- BCONV format: `BCONV-{workspace}-{business_ref}` (e.g., `BCONV-ws_acme-2026-00145`)

### Layer 3: Business Keys (confidence = 0.95)

**Match on:** order_ref, ticket_id, invoice_number, PO number, or custom keys embedded in message.

**Rationale:** Business keys are explicit identifiers humans mention. If found, they reliably identify the thread — but ambiguity is possible (two PO threads for the same vendor).

**Example:**
```
Inbound email body: "Regarding PO-2026-00145..."
→ Extract PO-2026-00145
→ Lookup in business_key_index[(order_ref, PO-2026-00145)]
→ Find [thread_id]
→ If 1 match: Confidence = 0.95
→ If N matches: Escalate to review queue (ambiguous)
```

**Implementation:**
- `add_business_key(key_type, value, thread_id)` — Register a business key
- `business_key_index` — Dict mapping (key_type, value) → [thread_ids]
- Handles multiple keys per thread (e.g., both order_ref and ticket_id)

### Layer 4: Participant Matching (confidence = 0.85)

**Match on:** Sender identity (email, phone, WhatsApp ID); sender's role (vendor, customer, approver).

**Rationale:** Validates the sender has a valid relationship to candidate threads from L3. Filters L3 candidates by role authority.

**Example:**
```
L3 matched: [thread_po_145, thread_po_146] (both have order_ref)
Sender: vendor@acme.com (role="vendor")
→ Check if vendor@acme.com is authorized on each thread
→ Filter to threads where vendor is the expected contact
→ Narrow to thread_po_145
→ Confidence = 0.85
```

**Implementation:**
- `_match_layer_4_participants(sender_dict, candidate_threads)` — Filter by role
- Look up sender's role in thread metadata (expected contacts, participants)

### Layer 5: Temporal Causality (confidence = 0.75)

**Match on:** Thread's current state and event-waiting criteria.

**Rationale:** Ensures the message makes sense NOW. A "vendor reply" only matches if the thread is waiting for vendor input, not if it's already completed or waiting for approval.

**Example:**
```
Inbound email: vendor reply to PO
L4 candidate: thread_po_145
Thread state: parked on wait_for_event(mail.received, on_event=vendor.reply)
→ Event type matches thread's waiting criteria
→ Confidence = 0.75
→ Resume the thread
```

**Implementation:**
- `_match_layer_5_temporal(thread_state, candidates)` — Validate thread state
- Query control-plane: is thread parked? Is it waiting for this event type?

---

## 2. Confidence Scoring & Ambiguity

| Layer | Confidence | Match Type |
|-------|------------|-----------|
| L1 (Message-ID) | 1.0 | Exact |
| L1 (In-Reply-To) | 0.95 | Strong |
| L2 (BCONV) | 1.0 | Exact |
| L3 (Business Key, single match) | 0.95 | Strong |
| L3 (Business Key, multiple matches) | < 0.9 | Ambiguous → Review Queue |
| L4 (Participant + L3) | 0.85 | Moderate |
| L5 (Temporal + L4) | 0.75 | Weak |

**Decision Rule:**
- **confidence >= 0.95:** Emit event, resume thread
- **0.75 <= confidence < 0.9:** Ambiguous, escalate to review queue
- **confidence < 0.75:** Reject, ask human

---

## 3. Passive Thread Events

**File:** `nilscript/comms/passive_events.py`

A `CommunicationReceivedEvent` is the deterministic, ledger-backed event that:
1. Records the inbound message + correlation metadata
2. Is committed to the event ledger (immutable audit)
3. Resumes any parked `wait_for_event` nodes on the thread
4. Becomes a timeline entry in the thread's case file

### Event Model

```python
class CommunicationReceivedEvent(DslModel):
    event_id: str  # UUID
    thread_id: str  # Business thread
    correlation_id: str  # From CorrelationEngine
    message: dict  # Full message {sender, body, timestamp, channel}
    matched_on: str  # Which layer? (L1_TRANSPORT, L2_CONVERSATION, ...)
    confidence: float  # 0.0-1.0
    thread_state_before: str  # State before resumption
    rendered_as: dict  # Timeline entry {type, sender, body, timestamp}
    received_at: str  # ISO timestamp
    source: Literal["email", "whatsapp", "sms"]
```

### Event Creation Flow

**Step 1:** Inbound message arrives at os-server comms bridge.

**Step 2:** Control-plane receives it, calls `CorrelationEngine.correlate()`.

**Step 3a (Confident Match):** Create event via `create_passive_resume_event()`.

```python
from nilscript.comms.correlation_engine import CorrelationEngine
from nilscript.comms.passive_events import create_passive_resume_event

engine = CorrelationEngine(...)  # Pre-seeded with transport/business key indices
result = engine.correlate(inbound_message)

if isinstance(result, CorrelationResult):
    event = create_passive_resume_event(
        message=inbound_message,
        thread_id=result.thread_id,
        correlation_result=result,
    )
    # Commit event to ledger
    ledger.add_event(event)
```

**Step 3b (Ambiguous):** Escalate to review queue (see below).

### Thread Resume

Once the event is committed to the ledger, the control-plane resumes the thread:

1. Look up the thread's parked nodes via `parked_runs(thread_id, kind=event)`
2. Find the node waiting on `mail.received` (or matching event type)
3. Check if the event matches the parked node's `match` criteria (e.g., `match: {order_ref: "PO-2026-00145"}`)
4. If match: resume the thread, execute the next node
5. Log the event + resume in the thread's audit trail

---

## 4. Review Queue: Ambiguous Correlation

**File:** `nilscript/comms/review_queue.py`

When a message matches multiple threads (ambiguous), it enters the `ReviewQueue` waiting for a human decision.

### Review Queue Item Lifecycle

```
MessageInbox (pre-correlation)
    ↓
CorrelationEngine.correlate()
    ├─→ [Confident] → Event + Resume (immediate)
    └─→ [Ambiguous] → ReviewQueueItem (pending)
    ↓
ReviewQueue.add_to_review()
    ↓
[Human reviews, picks thread]
    ↓
ReviewQueue.resolve(item_id, chosen_thread_id)
    ↓
CommunicationReceivedEvent (confidence=1.0, matched_on=HUMAN_REVIEW)
    ↓
Event + Resume (same as confident path)
```

### Review Queue API

```python
from nilscript.comms.review_queue import ReviewQueue, ReviewQueueAPI

queue = ReviewQueue(ttl_hours=72)  # 3-day expiry default

# Add an ambiguous message
item = queue.add_to_review(
    message={...},
    candidates=[
        {"thread_id": "t1", "business_ref": "PO-2026-00145", "confidence": 0.8},
        {"thread_id": "t2", "business_ref": "PO-2026-00146", "confidence": 0.8},
    ],
    correlation_id="corr-xyz",
)

# List pending for a thread or workspace
pending = queue.list_pending(workspace="ws_acme")  # → [ReviewQueueItem, ...]

# Human picks a thread
event = queue.resolve(item.id, chosen_thread_id="t1", resolved_by="user-123")

# Optional: reject (not a real message)
queue.reject(item.id)

# Cleanup expired items (run periodically)
queue.cleanup_expired()  # → count of expired items
```

### OS-Server Review Queue Endpoint

The os-server exposes the review queue via REST:

```
GET  /api/review-queue/pending?workspace=ws_acme&thread_id=t1
     → List pending reviews for filtering/display

POST /api/review-queue/{review_item_id}/resolve
     body: {chosen_thread_id: "t1"}
     → Resolve and return event

GET  /api/review-queue/stats?workspace=ws_acme
     → {pending: N, resolved: N, expired: N, oldest_pending_age_minutes: M}
```

### UI: Review Queue Inbox

The wosool-hub adds a "Review Queue" or "Pending Correlations" tab to show:

1. **From** — sender email/name
2. **Subject** — email subject or message preview
3. **Candidates** — "Which thread?"
   - PO-2026-00145 (Samsung SSD 2TB)
   - PO-2026-00146 (Intel CPU Batch)
4. **Action** — "Pick" (radio buttons) → "Confirm"

Once confirmed, the event is committed and the thread resumes.

---

## 5. Outbound Communication Governance

**File:** `nilscript/comms/outbound_governance.py`

Outbound messages from cycles/capabilities are governance-routed through Wosool before being sent.

### Governance Tiers & Actions

| Tier | Action | Example |
|------|--------|---------|
| **LOW** | `send_immediately` | Internal notification, status update |
| **MEDIUM** | `send_immediately` | Regular vendor communication |
| **HIGH** | `send_with_notification` | Legal amendment, price change |
| **CRITICAL** | `wait_for_approval` | Contract signature, large payment |

### Outbound Flow

```
Cycle emits: comms.send_email
    ↓
Capability prepares: OutboundMessage
    ├─ thread_id, recipient, subject, body
    ├─ governance_tier (LOW/MEDIUM/HIGH/CRITICAL)
    └─ bconv_id, reply_token (for correlation)
    ↓
OutboundGovernance.route_outbound()
    ├─→ LOW/MEDIUM: send_immediately → [send]
    ├─→ HIGH: send_with_notification → [notify + send]
    └─→ CRITICAL: wait_for_approval → [approval card in Decisions]
    ↓
[If CRITICAL: human approves in Decisions tab]
    ↓
OutboundGovernance.commit_outbound()
    ├─ Stamp BCONV on subject: "[BCONV-ws_acme-2026-00145] ..."
    ├─ Stamp reply token in Reply-To: "wsl-abc123@wosool.ai"
    └─ Build custom headers: X-Wosool-Conversation-ID, X-Wosool-Reply-Token
    ↓
Adapter executes (send email/WhatsApp/SMS)
    ↓
Return message stamps reply token → correlates back via L1 (In-Reply-To)
```

### Reply Token Stamping

Different channels stamp differently:

**Email:**
```
Subject: "[BCONV-ws_acme-2026-00145] PO Update"
Reply-To: "wsl-abc123xyz@wosool.ai"
X-Wosool-Conversation-ID: BCONV-ws_acme-2026-00145
X-Wosool-Reply-Token: wsl-abc123xyz
```

**WhatsApp:**
```
Message: "wsl-abc123xyz: Your shipment is ready. Click to confirm."
```

**SMS:**
```
Message: "[wsl-abc123xyz] Your payment confirmation: INV-2026-001"
```

### API

```python
from nilscript.comms.outbound_governance import OutboundGovernance, OutboundMessage

governance = OutboundGovernance()

# Create outbound message
message = OutboundMessage(
    id=str(uuid.uuid4()),
    thread_id="thread-po-145",
    cycle_id="cyc_order",
    channel="email",
    recipient="vendor@example.com",
    subject="PO-2026-00145: Update",
    body="Shipment delayed to next week.",
    governance_tier="HIGH",  # Requires notification
    bconv_id="BCONV-ws_acme-2026-00145",
)

# Route
route = governance.route_outbound(message)
# → OutboundRoute(action="send_with_notification", notify_actors=["manager"])

# Commit (after any approvals)
commit = governance.commit_outbound(message, route, approved_by=None)
# → CommitOutboundMessage (ready for adapter)

# Send via adapter
adapter.send_email(
    to=commit.recipient,
    subject=commit.subject,
    body=commit.body,
    headers=commit.custom_headers,
)
```

---

## 6. Integration Points

### Control-Plane

- **Inbound:** `/events/ingest` — Accept inbound messages
  - Call `CorrelationEngine.correlate()`
  - Create `CommunicationReceivedEvent`
  - Commit to ledger
  - Resume thread via `dispatch_event()`

- **Outbound:** `capability.send_email()` / `send_whatsapp()`
  - Call `OutboundGovernance.route_outbound()`
  - If CRITICAL: create approval card in `prepared_executions`
  - On approval: call `commit_outbound()`
  - Route to adapter via `RoutingNilClient`

- **Storage:** Pre-seed `transport_index` + `business_key_index` on startup
  - Query `automation_runs(correlation_id)` → load all transport markers
  - Query capabilities for business keys (order_ref, etc.) → load index

### OS-Server

- **Comms Bridge:** IMAP poller → inbound normalization → `/events/ingest`
- **Review Queue API:** GET/POST endpoints (see §4)
- **Thread Aggregator:** Include communication events in thread case file

### Wosool-Hub

- **Communication Tab:** Render `CommunicationReceivedEvent.rendered_as`
  - Gmail-style thread view per thread
  - Show sender, subject, timestamp, attachments
  - Mark as inbound/outbound

- **Review Queue Tab:** Pending correlations inbox (see §4)
  - List ambiguous messages
  - Human picks thread
  - Confirm → event committed

---

## 7. Testing

**File:** `tests/test_wave7_correlation_engine.py` (60+ tests)

### Coverage

- **L1 matching:** Message-ID, In-Reply-To, WhatsApp, SMS
- **L2 matching:** BCONV lookup
- **L3 matching:** Business keys (single + ambiguous)
- **L4 matching:** Participant filtering
- **L5 matching:** Temporal causality validation
- **Confidence scoring:** Escalation thresholds
- **Event creation:** All channels (email, WhatsApp, SMS)
- **Review queue:** Add, resolve, reject, expiry, filtering
- **Outbound governance:** Routing, stamping, approval cards

### Running Tests

```bash
pytest tests/test_wave7_correlation_engine.py -v
# 60+ tests, all green
```

---

## 8. Phase 2: Full Implementation

Wave 7 Phase 1 (this file) stubs the core layers and models. Phase 2 implements:

1. **Control-Plane Integration**
   - Wire `CorrelationEngine` into `/events/ingest`
   - Pre-seed indices on CP startup
   - Implement L4/L5 matching (currently stubbed)

2. **OS-Server Review Queue**
   - Persistent storage (SQLite)
   - REST endpoints
   - Cleanup job (TTL expiry)

3. **Wosool-Hub UI**
   - Communication tab (render events)
   - Review queue inbox (pick thread)
   - Thread timeline aggregation

4. **Testing in Production**
   - E2E: inbound email → correlation → thread resume
   - E2E: ambiguous message → review → resolution
   - E2E: outbound CRITICAL → approval card → send

---

## 9. Design Principles

1. **Deterministic, not probabilistic:** Layer outputs are binary (match/no-match), not ranked lists.
2. **High confidence first:** Layers are ordered by confidence (1.0 → 0.75). First layer to match wins.
3. **Explicit ambiguity escalation:** < 0.9 confidence → review queue, never silent guessing.
4. **Idempotent events:** Same message ID always resolves to the same thread (L1 dedup).
5. **Correlation metadata carried:** Every event carries `correlation_id` + `matched_on` for audit.
6. **Governance stamping:** Outbound always carries BCONV + reply token for return correlation.

---

## 10. References

- [Business Threads Plan](../business-threads-plan.md) — Thread model & lifecycle
- [Comms Module Deployment](../comms-module-deployment.md) — Live outbound/inbound
- [Wave 4 Constitution](../docs/WAVE-4-CONSTITUTION.md) — Architecture freeze
- [NBEM Ontology](../docs/NBEM-ONTOLOGY.md) — Thread, Cycle, Event terminology
