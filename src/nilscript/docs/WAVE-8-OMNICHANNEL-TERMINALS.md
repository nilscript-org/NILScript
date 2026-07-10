# Wave 8: Omnichannel Terminals

**Status**: Foundation design + stubs  
**Phase**: Wave 8, Phases 1–3  
**Owner**: Kernel Team  
**Last Updated**: 2026-07-07

---

## Overview

Wave 8 introduces omnichannel message terminals — the infrastructure for Wosool to be reached and operated from any messaging platform (WhatsApp, Slack, Email, SMS) and the mobile app.

The system is built in three phases:

1. **Phase 1: Terminal Foundation** (complete)
   - Channel adapter contract
   - Invocation parser
   - Permission card rendering (channel-native UI)
   - Mobile terminal API design
   - Tests + documentation

2. **Phase 2: Channel Implementations** (in-progress)
   - WhatsApp adapter (Evolution API)
   - Slack adapter (Bolt framework)
   - SMS adapter (Twilio / Nexmo)
   - Email adapter (SMTP + IMAP)

3. **Phase 3: Correlation & Routing** (queued)
   - Message correlation engine (link inbound messages to threads)
   - Channel-agnostic message router
   - Conversation history integration

---

## Architecture

### Component Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                    Messaging Channels                           │
│    WhatsApp | Slack | Email | SMS | Mobile Web                 │
└─────────────────┬───────────────────────────────────────────────┘
                  │ Webhooks / API calls
                  │
┌─────────────────▼───────────────────────────────────────────────┐
│           Channel Adapters (adapter_contract.py)                │
│     Abstract interface + concrete implementations               │
└─────────────────┬───────────────────────────────────────────────┘
                  │ Standardized messages + responses
                  │
┌─────────────────▼───────────────────────────────────────────────┐
│                   Terminal Layer                                │
│                                                                 │
│  ┌─────────────────────┐  ┌──────────────────────┐             │
│  │ Invocation Parser   │  │ Permission Card      │             │
│  │ (parse cycle cmds)  │  │ Renderer             │             │
│  └─────────────────────┘  │ (channel-native UI)  │             │
│                           └──────────────────────┘             │
│                                                                 │
│  ┌──────────────────────────────────────────────┐              │
│  │         Mobile Terminal API                  │              │
│  │  (list threads, detail, approve, message)    │              │
│  └──────────────────────────────────────────────┘              │
└─────────────────┬───────────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────────┐
│                   Kernel (existing)                             │
│  Cycles, governance, persistence, execution                    │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

**Outbound (Cycle → Channel)**:
```
Kernel executes a cycle step that needs approval
    ↓
Permission Card generated {proposal_id, tier, actions}
    ↓
PermissionCardRenderer.render_for_channel(card, "whatsapp")
    ↓
Channel-specific payload (WhatsApp interactive message, Slack Block Kit, etc.)
    ↓
ChannelAdapter.send_permission_card(recipient, rendered_payload)
    ↓
User receives card in their channel (button UI, text codes, HTML links)
```

**Inbound (Channel → Kernel)**:
```
User sends message in channel or clicks approval button
    ↓
Channel sends webhook to /events/{channel} endpoint
    ↓
ChannelAdapter.handle_inbound(webhook_payload) or handle_permission_response(...)
    ↓
Standardized InboundMessage or PermissionCardResponse
    ↓
Correlation Engine links message to thread (via business_ref, recent history, ML)
    ↓
Kernel processes (route to cycle, execute approval, message thread, etc.)
```

---

## Channel Adapter Contract

**File**: `channels/adapter_contract.py`

Every channel adapter implements this abstract interface:

```python
class ChannelAdapter(ABC):
    CHANNEL_NAME: str  # "whatsapp", "slack", "email", "sms"
    
    async def send_message(recipient, body, metadata) -> OutboundMessage
    async def send_permission_card(recipient, card) -> str
    async def handle_inbound(webhook_payload) -> InboundMessage
    async def handle_permission_response(webhook_payload) -> PermissionCardResponse
    async def fetch_conversation_history(recipient, limit=10) -> list[ConversationMessage]
```

### Model Layer

**OutboundMessage**:
- `message_id`: Channel-assigned ID
- `recipient`: Channel-specific ID (phone, email, user ID, etc.)
- `timestamp`: When sent
- `status`: SENT | DELIVERED | READ | FAILED | PENDING

**InboundMessage** (standardized across all channels):
- `sender`: Who sent it
- `body`: Message content
- `timestamp`: When received
- `channel`: Which channel (whatsapp, slack, email, sms)
- `channel_message_id`: Platform-native ID
- `reply_to`: ID of message being replied to (optional)
- `message_type`: TEXT | MEDIA | AUDIO | DOCUMENT | INTERACTIVE | SYSTEM
- `metadata`: Channel-specific extra data

**PermissionCard** (governance gate):
- `proposal_id`: Unique ID
- `thread_id`: Associated thread/cycle
- `title`: Short title
- `description`: Longer explanation
- `actions`: {action_key: label} e.g., {"approve": "✓ Approve", "deny": "✗ Deny"}
- `tier`: LOW | MEDIUM | HIGH | CRITICAL
- `metadata`: Extra data

**PermissionCardResponse**:
- `proposal_id`: Which proposal was answered
- `action`: Which button/code was chosen (approve, deny, escalate, etc.)
- `timestamp`: When
- `responder`: Who (user ID, phone, email, etc.)
- `channel`: Which channel the response came from

### Registry

The `ChannelAdapterRegistry` is a simple map of channel_name → adapter:

```python
registry = ChannelAdapterRegistry()
registry.register(WhatsAppAdapter(...))
registry.register(SlackAdapter(...))

adapter = registry.get("whatsapp")
channels = registry.list_channels()  # ["slack", "whatsapp"]
```

### Error Hierarchy

- `ChannelError` (base)
  - `ChannelAuthError`: Auth/permission failure
  - `ChannelRateLimitError`: Rate limit exceeded
  - `ChannelTimeoutError`: Operation timed out
  - `ChannelUnsupportedError`: Feature not supported by channel

---

## Invocation Parser

**File**: `channels/invocation_parser.py`

Parses channel messages to detect cycle invocations.

### Invocation Patterns

**WhatsApp**:
```
@wosool order Acme 100 units
/order Acme 100 units
wosool: order Acme 100 units
```

**Slack**:
```
@wosool-bot order Acme 100 units
/wosool order Acme 100 units
wosool: order Acme 100 units
```

**SMS**:
```
wosool: order Acme 100
WOSOOL: order Acme 100
```

**Email** (subject or body):
```
Cycle: order Acme 100
cycle: order Acme 100
```

### InvocationMatch

```python
@dataclass
class InvocationMatch:
    intent: str  # "ExecuteCycle"
    cycle_name: str  # "order", "approve_invoice"
    parameters: dict[str, Any]  # {"vendor": "Acme", "amount": 1000}
    channel: str
    sender: str
    confidence: float  # [0.0, 1.0]
    raw_message: str
```

### Usage

```python
parser = InvocationParser()

# Parse a message
match = parser.parse("@wosool order Acme 100", "whatsapp", sender="user_123")
if match:
    print(f"Cycle: {match.cycle_name}")
    print(f"Confidence: {match.confidence}")
    print(f"Parameters: {match.parameters}")

# Fill in missing parameters from thread context
match_filled = parser.fill_missing_slots(
    match,
    thread_context={"vendor_id": "vendor_acme", "currency": "USD"}
)
```

### Supported Channels

- `whatsapp`: Via Evolution API (mentions, slash commands, text)
- `slack`: Via Bolt framework (mentions, slash commands, direct text)
- `sms`: Short commands with minimal syntax
- `email`: Subject line or body parsing

---

## Permission Card Rendering

**File**: `channels/permission_card_renderer.py`

Renders governance gates in channel-native UI and parses responses.

### Rendering

Each channel has a specialized renderer that handles:
- Converting generic PermissionCard → channel-native payload
- Capturing responses via channel callbacks
- Parsing responses back to PermissionCardResponse

```python
renderer = PermissionCardRenderer()

card = PermissionCard(
    proposal_id="prop_123",
    thread_id="thread_456",
    title="Approve invoice",
    description="Vendor Acme $1000",
    actions={"approve": "✓ Approve", "deny": "✗ Deny"},
    tier="MEDIUM"
)

# Render for a specific channel
whatsapp_rendered = await renderer.render_for_channel("whatsapp", card)
# OR specific methods:
slack_rendered = await renderer.render_for_slack(card)
```

### Channel-Specific Formats

**WhatsApp** (Interactive Message):
```json
{
  "interactive": {
    "type": "button",
    "body": {
      "text": "🟡 Approve invoice?\n\nVendor Acme $1000"
    },
    "action": {
      "buttons": [
        {"type": "reply", "reply": {"id": "approve", "title": "✓ Approve"}},
        {"type": "reply", "reply": {"id": "deny", "title": "✗ Deny"}},
        {"type": "reply", "reply": {"id": "escalate", "title": "⬆ Escalate"}}
      ]
    }
  }
}
```
Max 3 buttons per message. Response is user-selected button ID.

**Slack** (Block Kit):
```json
{
  "blocks": [
    {"type": "context", "elements": [{"type": "mrkdwn", "text": "🟡 Approval Required — MEDIUM tier"}]},
    {"type": "section", "text": {"type": "mrkdwn", "text": "*Approve invoice?*\nVendor Acme $1000"}},
    {"type": "divider"},
    {"type": "actions", "elements": [
      {"type": "button", "text": {"type": "plain_text", "text": "Approve"}, "value": "approve", "action_id": "card_approve_prop_123"},
      {"type": "button", "text": {"type": "plain_text", "text": "Deny"}, "value": "deny", "action_id": "card_deny_prop_123"}
    ]},
    {"type": "context", "elements": [{"type": "mrkdwn", "text": "Proposal: `prop_123`"}]}
  ]
}
```
Unlimited buttons. Response is button action_id and value.

**SMS** (Text + Codes):
```
🟡 Approve invoice?

Vendor Acme $1000

Reply: A (Approve), D (Deny), E (Escalate)

ID: prop_123
```
Response is single character code (A, D, E, etc.).

**Email** (HTML + Plain Text):
- HTML version with clickable action links
- Plain text version with reply codes
- Supports both web clients (links) and email replies (text codes)

### Response Handling

```python
# After user clicks button or replies

response_payload = {
    "message": {...},  # Channel-native format
    "sender": {...}
}

response = await renderer.handle_card_response("whatsapp", response_payload)

# response is PermissionCardResponse:
print(response.proposal_id)  # "prop_123"
print(response.action)       # "approve"
print(response.responder)    # "+1234567890"
print(response.channel)      # "whatsapp"
```

---

## Mobile Terminal API

**File**: `channels/mobile_terminal.py`

The mobile app is a thin client that queries the backend for thread data and sends approval responses. It is NOT a cycle editor — editing happens in the web UI.

### ThreadSummary (List View)

Fields for list display:
- `thread_id`, `cycle_name`, `subject`
- `status`: ACTIVE | PENDING_APPROVAL | COMPLETED | FAILED | PAUSED
- `last_update`: Timestamp
- `pending_approvals`: Count of waiting approvals
- `unread_messages`: Count
- `participants`: List of people involved
- `business_ref`: Optional external reference (order ID, etc.)

### ThreadDetail (Full View)

Rich detail with:
- `timeline`: List of TimelineEvent (message_sent, step_completed, approval_needed, etc.)
- `approvals`: List of ApprovalProposal (pending governance gates)
- `documents`: List of DocumentRef (attachments)
- `messages`: Conversation history
- `participants`: People involved with roles
- `metadata`: Extra thread-specific data

### API Methods

```python
terminal = MobileTerminal()

# List threads with filtering
threads, total = await terminal.fetch_threads(
    workspace_id="ws_123",
    filter_by={
        "status": "pending_approval",
        "assigned_to": "user_456",
        "cycle_name": "order"
    },
    limit=20,
    offset=0
)

# Get thread detail
detail = await terminal.fetch_thread_detail("thread_123")

# Send approval
await terminal.send_approval_response(
    proposal_id="prop_123",
    action="approve",
    comment="Looks good"
)

# Send message in thread
msg = await terminal.send_message(
    thread_id="thread_123",
    body="We'll ship tomorrow",
    attachments=[...]
)

# Search threads
results = await terminal.search_threads("ws_123", query="acme", limit=10)

# List all pending approvals for user
pending = await terminal.list_my_pending_approvals("ws_123")
```

### Push Notifications

```python
notifications = MobileNotification()

# When approval is needed
await notifications.approval_needed(
    proposal_id="prop_123",
    title="Approve invoice from Acme",
    tier="MEDIUM",
    recipient_user_id="user_456"
)

# When thread is updated
await notifications.thread_updated(
    thread_id="thread_123",
    event="message_added",
    title="New message from Sales",
    recipient_user_id="user_456"
)

# When someone sends a message
await notifications.message_received(
    thread_id="thread_123",
    sender_name="Alice",
    preview="We'll ship tomorrow",
    recipient_user_id="user_456"
)
```

---

## Integration: Correlation Engine

**Status**: Phase 3 (design), not yet implemented

The Correlation Engine links inbound messages to threads by:

1. **Business Reference**: Message contains "order-123" → find thread with business_ref="order-123"
2. **Sender + Channel**: Message from user who participated in thread → add to that thread
3. **Conversation History**: Fetch recent messages from channel, find thread with matching context
4. **Entity Extraction**: NLP extracts vendor name, amount, etc. → match to thread data
5. **ML Scoring**: Combine signals, return top-N thread candidates

Example:

```python
correlation_engine = CorrelationEngine()

inbound = InboundMessage(
    sender="+1234567890",
    body="Order confirmed for Acme",
    channel="whatsapp"
)

candidates = await correlation_engine.find_thread_candidates(
    inbound,
    workspace_id="ws_123",
    limit=5
)

# candidates = [
#     {"thread_id": "thread_123", "score": 0.95, "reason": "sender participated"},
#     {"thread_id": "thread_456", "score": 0.80, "reason": "vendor name match"}
# ]

best_thread = candidates[0]
await kernel.add_message_to_thread(best_thread["thread_id"], inbound)
```

---

## Testing

**File**: `tests/test_wave8_channels.py`

Comprehensive test coverage (15+ tests):

1. **Adapter Registry** (5 tests)
   - Register/get adapters
   - Duplicate registration error
   - Get nonexistent adapter error
   - List channels
   - Has channel check

2. **Invocation Parser** (8 tests)
   - WhatsApp patterns (@wosool, /command, wosool:)
   - Slack patterns (@bot, /command)
   - SMS patterns (wosool:)
   - Email subject parsing
   - Parameter extraction (key=value)
   - No match detection
   - Fill missing slots from context
   - List supported channels

3. **Permission Card Rendering** (13 tests)
   - WhatsApp rendering + response parsing
   - Slack rendering + response parsing
   - SMS rendering + response parsing
   - Email rendering + response parsing
   - Renderer dispatch to channel-specific renderers
   - Unsupported channel error

4. **Integration Tests** (2 tests)
   - End-to-end WhatsApp approval flow
   - Cycle invocation detection and parsing

Run tests:
```bash
pytest tests/test_wave8_channels.py -v
```

---

## Phase 2: Channel Implementations (Roadmap)

### WhatsApp Adapter

Uses Evolution API (current implementation in `channels/whatsapp/`):
- Outbound messages via `/send/text`
- Interactive messages via `/send/interactive` for permission cards
- Inbound via webhook at `/webhook/whatsapp`
- Rate limits, idempotency keys, circuit breaker

### Slack Adapter

Uses Bolt framework:
- Outbound messages + Block Kit via `client.chat_postMessage`
- Interactive components via `client.conversations_open` (modals) or `client.chat_postMessage` (blocks)
- Inbound via `/events` endpoint with signature verification
- Slash command handling via Bolt middleware

### SMS Adapter

Uses Twilio or Nexmo:
- Outbound SMS via `sendMessage` API
- Short text codes for permission cards (A/D/E)
- Inbound via webhook callback
- Number normalization, carrier lookup

### Email Adapter

Using SMTP + IMAP:
- Outbound via SMTP with HTML + plain text
- Action links + reply-based responses
- Inbound via IMAP polling or webhook (SendGrid, Postmark, etc.)
- Subject line parsing, thread ID tracking

---

## Phase 3: Correlation & Routing (Roadmap)

### Correlation Engine

- Link inbound messages to threads
- Multi-signal scoring (business ref, sender, history, entity extraction)
- Fallback to user confirmation if ambiguous

### Message Router

- Route inbound to: cycle invocation handler, thread message handler, or approval response handler
- Standardize across all channels

### Conversation History Integration

- Fetch recent messages from each channel
- Use for context in cycle parameter filling
- Feed into correlation scoring

---

## Design Decisions

### Q: Why separate adapters for each channel?

**A**: Channels have fundamentally different APIs, protocols, and capabilities. Adapting them all to a single model would require either:
1. A least-common-denominator interface (too weak)
2. An adaptation layer that converts between APIs (adds complexity)
3. Separate adapters with a shared contract (proven approach, used by messaging frameworks)

We chose option 3. Each adapter is self-contained, making it easy to add new channels without touching existing ones.

### Q: Why is the mobile app a "thin terminal" and not a full cycle editor?

**A**: Editing cycles requires schema knowledge, validation, testing, and version control. The web UI is the source of truth. The mobile app's job is to *execute* cycles and *approve* steps — not author them. This keeps the mobile client simple and ensures all cycle changes go through the web UI with proper oversight.

### Q: Why do permission cards render differently per channel?

**A**: Each channel has different UI constraints and user expectations:
- WhatsApp: max 3 interactive buttons, no HTML
- Slack: rich Block Kit with color, sections, context
- SMS: 160-char limit, numeric codes
- Email: HTML + plain text, links work

Forcing all channels to the same rendering would either look generic (bad UX) or exceed channel limits. Channel-native rendering respects each platform's strengths.

### Q: How does correlation handle ambiguous messages?

**A**: Phase 3 will implement:
1. Scoring algorithm (combine multiple signals)
2. Confidence thresholds (high → auto-add, medium → human review, low → reject)
3. User confirmation UI (show top-N candidates, let user pick)

For MVP, we'll require explicit thread linking (e.g., include business_ref in message or reply to a thread message).

---

## Dependency Graph

```
adapter_contract.py
  ├─ models only (Pydantic)
  ├─ no external channel libraries

invocation_parser.py
  ├─ dataclasses
  ├─ re (regex)
  └─ no external dependencies

permission_card_renderer.py
  ├─ adapter_contract.py (types)
  ├─ dataclasses
  ├─ datetime
  └─ no external dependencies

mobile_terminal.py
  ├─ Pydantic models
  ├─ Enum
  └─ no external dependencies

test_wave8_channels.py
  ├─ all modules above
  └─ pytest, pytest-asyncio
```

All modules are framework-agnostic. Actual channel implementations (whatsapp, slack, etc.) will depend on their respective SDKs.

---

## Configuration

Channel adapters are configured via environment variables or config objects:

```python
# WhatsApp (Evolution)
whatsapp_config = EvolutionConfig(
    base_url=os.getenv("EVOLUTION_API_URL"),
    api_key=os.getenv("EVOLUTION_API_KEY"),
)

# Slack
slack_config = SlackConfig(
    bot_token=os.getenv("SLACK_BOT_TOKEN"),
    signing_secret=os.getenv("SLACK_SIGNING_SECRET"),
)

# Mobile API
mobile_config = MobileTerminalConfig(
    base_url=os.getenv("API_BASE_URL"),
    api_version="v1",
    timeout_seconds=30,
)
```

---

## Next Steps (Wave 8 Phase 2)

1. Implement WhatsApp adapter (Evolution API integration)
2. Implement Slack adapter (Bolt framework)
3. Implement SMS adapter (Twilio)
4. Implement Email adapter (SMTP + IMAP)
5. Wire channel adapters to kernel message routing
6. Deploy to staging for E2E testing
7. Phase 3: Correlation engine + message router

---

## Related Documents

- [NBEM-CONSTITUTION.md](NBEM-CONSTITUTION.md) — Platform ontology (Threads, Cycles, Verbs)
- [WAVE-4-CONSTITUTION.md](WAVE-4-CONSTITUTION.md) — Compiler, lowering, NIL syntax
- [WAVE-6-AUTHORITY-LAYERS.md](WAVE-6-AUTHORITY-LAYERS.md) — Governance gates
