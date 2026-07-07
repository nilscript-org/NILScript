# Wave 5 (AI Boundary) — Migration from MCP Tool Selection to Kernel.Execute

## Overview

Wave 5 establishes the **AI Boundary** — the frozen contract between Hermes (the AI) and the Kernel (the server). This document describes the migration from today's model (Hermes sees all verbs and capabilities) to Wave 5 (server-side resolution, Hermes sees only business semantics).

## Today (Pre-Wave 5)

```
User (NL) → Hermes → MCP Tool Selection:
  |
  ├─ Hermes sees ALL verbs: [resource.read, procurement.create_invoice, comms.send_email, ...]
  ├─ Hermes generates: Tool Call {tool: procurement.create_invoice, args: {...}}
  └─ Kernel executes: MCP verb directly
```

**Problem:** Hermes has full visibility into implementation details (verbs, capabilities). This breaks encapsulation and makes it impossible to govern what AI can do independently of what the API exposes.

## Wave 5 (AI Boundary)

```
User (NL) → Hermes → Frozen Intent Schema → Kernel (Server-side Resolution):
  |
  ├─ Hermes sees ONLY business operations: [CreateBusinessCycle, ExecuteCycle, ReplyToThread, ...]
  ├─ Hermes fills Intent schema: {kind: CreateBusinessCycle, description: "...", parameters: {...}}
  ├─ Kernel.execute(intent):
  │  ├─ CapabilityResolver: Intent → Capabilities (Hermes never sees this)
  │  ├─ Governance: Check permission card (Hermes never sees this)
  │  └─ Execution: Fire resolved capabilities as verbs
  │
  └─ If ambiguous, Kernel → Hermes (Clarify): "Which Ahmed?" → Hermes refills Intent
```

**Benefit:** Hermes operates on business semantics only. The Kernel owns capability resolution and governance. Auditable, governed, and encapsulated.

## Migration Phases

### Phase 0: Intent Schema Foundation (Wave 5, Week 1)

**Done (THIS TASK):**
- Define frozen Intent taxonomy v1 (7 intent kinds)
- Define CapabilityResolver stub (server-side only)
- Define Kernel.execute and Kernel.compile stubs
- Write comprehensive tests
- Document migration path

**Files:**
- `nilscript/src/nilscript/wbos/intent.py` — Frozen Intent schema
- `nilscript/src/nilscript/wbos/capability_resolver.py` — Resolver stub
- `nilscript/src/nilscript/wbos/kernel.py` — Kernel stub
- `tests/test_wave5_intent_schema.py` — Intent tests
- `tests/test_wave5_capability_resolver_stub.py` — Resolver tests
- `tests/test_wave5_kernel_stub.py` — Kernel tests

### Phase 1: Specification Engine (Wave 5, Week 2-3)

Build the NL → BizSpec component that the Kernel uses during compile.

**Deliverable:**
- SpecificationEngine class (may reuse existing BizSpec compiler)
- Input: NL description + workspace context
- Output: BizSpec with identified systems, actors, rules
- Clarify loop: If ambiguities, emit ClarifyRequest back to Hermes

**Integration:**
- Kernel.compile(CreateBusinessCycleIntent) calls SpecificationEngine
- Specification fills intent.parameters with extracted systems/actors/rules

### Phase 2: Capability Encapsulation (Wave 5, Week 4)

Build the Capability Registry query layer and implement CapabilityResolver.

**Deliverable:**
- CapabilityRegistry: Query API (find_by_systems, find_by_domain, etc.)
- CapabilityResolver implementation:
  - `resolve_for_intent()` routes by intent kind
  - `find_capabilities_for_systems()` queries registry
  - `suggest_for_ambiguity()` generates clarification options
- Implement all resolver methods

**Integration:**
- Kernel.execute and Kernel.compile both use CapabilityResolver
- Resolver queries registry (server-side, Hermes never sees it)
- Returns ResolvedCapability list or ambiguities

### Phase 3: Kernel Implementation (Wave 5, Week 5-6)

Implement Kernel.execute and Kernel.compile fully.

**Kernel.execute route:**
1. Validate intent (schema check)
2. CapabilityResolver.resolve_for_intent() → resolved capabilities
3. Governance check (permission card, actor tier)
4. Execute resolved capabilities (fire verbs in order)
5. Emit audit log, timeline, result
6. Return ExecutionResult

**Kernel.compile route:**
1. Validate intent (schema check)
2. SpecificationEngine (NL → spec, with Clarify loop)
3. CapabilityResolver (spec → capabilities)
4. CycleBuilder (capabilities → cycle blueprint)
5. NILCompiler (blueprint → .nil text)
6. Validator (policy/type/gov checks)
7. Generate preview + ask for confirmation
8. Return CompiledPlan

### Phase 4: Hermes Integration (Wave 5, Week 7)

Integrate Hermes with the new Intent API.

**Deliverable:**
- Hermes MCP server exposes only Intent kinds (no verbs)
- Hermes fills Intent schema with business semantics
- Hermes handles Clarify responses from Kernel
- Remove verb visibility from Hermes (migrate from MCP tool list to Intent schema)

**Integration:**
- Hermes → Kernel.execute(intent) for runtime
- Hermes → Kernel.compile(intent) for design-time
- Hermes ← Kernel.ClarifyRequest() for ambiguity resolution
- Hermes → Kernel.execute(clarified_intent) resumes

### Phase 5: Migration (Wave 5, Week 8)

Run old and new systems in parallel, then cut over.

**Canary:**
- 10% of intents → Wave 5 Kernel.execute
- 90% of intents → Legacy MCP tool selection
- Monitor error rates, latency, audit trail

**Cut over:**
- 100% of intents → Wave 5 Kernel.execute
- Retire legacy MCP tool selection

## Intent Taxonomy v1 (Frozen)

These are the only operations Hermes can request. Breaking changes require Intent v2.0.

| Intent Kind | Meaning | Emitted By | Parameters |
|-----------|---------|-----------|-----------|
| `CreateBusinessCycle` | Design a new cycle from NL description | Hermes | actors, rules, systems |
| `ExecuteCycle` | Run a known cycle | Hermes | cycle_id, args |
| `ReplyToThread` | Send a message to a thread | Hermes | thread_id, message, attachments |
| `QueryThread` | Introspect thread history/documents | Hermes | thread_id, query_type |
| `ExplainDecision` | Ask why a decision was made | Hermes | decision_id, decision_point |
| `SummarizeThread` | Summarize thread activity | Hermes | thread_id, format |
| `Clarify` | Kernel asks Hermes to disambiguate | Kernel | options, context, question |

## API Contracts (Frozen)

### Intent (Input to Kernel)

```python
class Intent(BaseModel):
    kind: IntentKind  # Closed enum
    description: str  # Natural language
    workspace_id: str  # Tenant isolation
    actor_id: str  # Who is acting
    version: str = "1.0"  # Schema version
    parameters: dict[str, Any] = {}  # Business semantics
    # Extra fields forbidden (frozen, extra="forbid")
```

**Immutability:** Pydantic frozen=True — once created, cannot be modified.

**Versioning:** Version field allows future evolution (v1.1, v2.0). If schema changes break compatibility, create Intent v2.0.

### Kernel.execute() → ExecutionResult

```python
@dataclass
class ExecutionResult:
    success: bool
    intent_kind: IntentKind
    result: Any = None  # The outcome (run_id, message_id, etc.)
    error: str | None = None
    audit_log: dict[str, Any] = {}  # Governance events
    timeline: list[dict[str, Any]] = []  # Step-by-step execution
```

### Kernel.compile() → CompiledPlan

```python
@dataclass
class CompiledPlan:
    success: bool
    intent_kind: IntentKind
    cycle_blueprint: dict[str, Any] | None = None
    nil_code: str | None = None
    preview: str | None = None
    validation_errors: list[str] = []
    requires_confirmation: bool = False
    clarification_needed: list[dict[str, Any]] = []
```

## Resolver Layer (Server-Side Only)

### CapabilityResolver

```python
class CapabilityResolver:
    def resolve_for_intent(self, intent: Intent) -> ResolutionResult:
        """Intent → Capabilities (server-side only)."""
        # Route by intent kind
        # Query registry for matching capabilities
        # Return ResolvedCapability list or ambiguities
    
    def find_capabilities_for_systems(self, systems: list[str]) -> list[Capability]:
        """For ["email", "odoo"], find matching capabilities."""
        # Query registry: "email" → SendEmail, SendSMS, ...
        # Return list of capabilities
    
    def suggest_for_ambiguity(self, question: str, workspace_id: str) -> list[tuple]:
        """Generate clarification options."""
        # "Which Ahmed?" → [("ahmed@acme", "Ahmed - ACME"), ("ahmed@supplier", "Ahmed - Supplier")]
```

**Key principle:** CapabilityResolver is **Hermes-opaque**. Hermes never sees:
- The registry
- Capability ids
- Verb names
- Resolved capabilities

Hermes only sees clarification requests when ambiguities arise.

## Clarify Loop

When Kernel cannot resolve an intent unambiguously:

```
1. Hermes sends: CreateBusinessCycleIntent(description: "Create approval for suppliers")
2. SpecificationEngine extracts systems: ["procurement", "suppliers"]
3. CapabilityResolver finds ambiguity: "Which suppliers? (ACME, Supplier2, Supplier3)"
4. Kernel → Hermes: ClarifyRequest(question: "Which suppliers should auto-approve?", options: [...])
5. Hermes sends back: CreateBusinessCycleIntent(parameters: {suppliers: ["ACME"]})
6. Kernel resumes: Compile or Execute with clarified parameters
```

Hermes never sees the capability ids or verb names, only the business-level clarifications.

## Breaking Changes (Future Versions)

If Intent v1.0 needs to change:

1. **Non-breaking (v1.1):**
   - Add optional fields to parameters
   - Add new optional intent kinds
   - Version bump to 1.1 (backward compatible)

2. **Breaking (v2.0):**
   - Change existing field types
   - Remove intent kinds
   - Change frozen structure
   - Requires dual-running (v1.0 and v2.0 in parallel)
   - Hermes must be updated to fill v2.0 schema
   - Migration deadline is set and enforced

## Testing Checklist

Wave 5 delivers:

- [x] Intent schema is frozen (immutable, extra="forbid")
- [x] Versioning works (default v1.0, settable for future migration)
- [x] All 7 intent kinds have tests
- [x] CapabilityResolver stubs compile without errors
- [x] Kernel.execute and Kernel.compile are callable stubs
- [x] Resolver interface matches expected shape
- [x] Frozen intent objects cannot be modified
- [x] Intent schema rejects unknown fields
- [x] All tests pass

## Next Steps (Phase 1-5)

1. **Phase 1 (Week 2-3):** Build SpecificationEngine (NL → BizSpec)
2. **Phase 2 (Week 4):** Implement CapabilityResolver and CapabilityRegistry
3. **Phase 3 (Week 5-6):** Implement Kernel.execute and Kernel.compile
4. **Phase 4 (Week 7):** Integrate Hermes with Intent API
5. **Phase 5 (Week 8):** Canary and cut over (migrate 100% of traffic)

## References

- `nilscript/src/nilscript/wbos/intent.py` — Intent taxonomy
- `nilscript/src/nilscript/wbos/capability_resolver.py` — Resolver stub
- `nilscript/src/nilscript/wbos/kernel.py` — Kernel stubs
- `docs/NBEM-CONSTITUTION.md` — Platform foundations
- `docs/WAVE-4-CONSTITUTION.md` — Wave 4 architecture
