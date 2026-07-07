# Phase 3 Verification Checklist

**Phase 3 Execution Goal:** Create comprehensive test suite that simulates the end-to-end flow (Settings UI → CP → Executor → os-server) and prove all success criteria pass.

**Session:** 2026-07-07  
**Milestone:** Wave 4 §3 — Capability Encapsulation Enforcement  
**Status:** READY FOR EXECUTION

---

## Success Criteria & Verification Matrix

Each criterion below is tied to a specific test or verification method. All must PASS before Phase 3 is deemed complete.

### 1. BizSpec Authoring & Validation

| Criterion | Test/Method | Expected Result | Status | Evidence |
|-----------|-----------|-----------------|--------|----------|
| BizSpec authoring UI form renders | `test_hub_settings_form_serializes_bizspec` | Form displays with fields: cycle name, domain_id, steps builder, governance level | [ ] PASS | |
| Form validation works | Manual UI test or e2e Playwright | Publish button disabled until: name + domain_id + min 1 step | [ ] PASS | |
| JSON preview updates live | Manual UI test or Playwright | JSON panel shows live serialization as user edits | [ ] PASS | |
| Step builder allows effect, approval, wait, notify | Unit test on StepBuilder component | All 4 step types can be added/removed/edited | [ ] PASS | |
| Governance level selector works | Unit test on governance dropdown | Can select LOW/MEDIUM/HIGH, affects envelope.tier | [ ] PASS | |

**Test files:**
- `nilscript/tests/test_phase3_e2e.py::TestSettingsUIToCPFlow::test_hub_settings_form_serializes_bizspec`
- Manual/E2E: wosool-hub Settings UI page

---

### 2. BizSpec Compilation

| Criterion | Test/Method | Expected Result | Status | Evidence |
|-----------|-----------|-----------------|--------|----------|
| BizSpec + Domain compiles successfully | `test_bizspec_compiles_with_domain_bindings` | `compile_bizspec()` returns `CompiledPlan` without errors | [ ] PASS | |
| CompiledPlan includes backend_bindings | `test_compiled_plan_has_backend_bindings` | `plan.backend_bindings` dict populated with capability→backend map | [ ] PASS | |
| All effect steps have backend assigned | `test_compiled_plan_has_all_effect_steps` | Every effect step in plan.steps has `backend` field set | [ ] PASS | |
| Governance envelope aggregates correctly | `test_governance_envelope_aggregates_correctly` | Envelope.tier = max tier across effects | [ ] PASS | |
| D8 explicit bindings enforced | `test_d8_improvement_explicit_vs_implicit_routing` | Backend bindings resolved from Domain, not implicit | [ ] PASS | |

**Test files:**
- `nilscript/tests/test_phase3_e2e.py::TestBizSpecCompilation`
- `nilscript/tests/test_phase3_parity_simulation.py::test_d8_improvement_explicit_vs_implicit_routing`

---

### 3. Flow Lowering

| Criterion | Test/Method | Expected Result | Status | Evidence |
|-----------|-----------|-----------------|--------|----------|
| `lower_to_flow()` preserves domain_id | `test_flow_preserves_domain_id` | `flow.domain_id == plan.domain` | [ ] PASS | |
| Flow carries backend_bindings | `test_flow_preserves_backend_bindings` | `flow.backend_bindings == plan.backend_bindings` | [ ] PASS | |
| Flow structure is valid & executable | `test_flow_structure_is_valid` | `flow.entry` set, all steps have `id`, steps linked | [ ] PASS | |
| Round-trip through NIL grammar works | `test_parity_round_trip_nil_grammar` | `parse_nil(print_nil(cycle)) == cycle` | [ ] PASS | |

**Test files:**
- `nilscript/tests/test_phase3_e2e.py::TestFlowLowering`
- `nilscript/tests/test_phase3_parity_simulation.py::test_parity_round_trip_nil_grammar`

---

### 4. Executor & Governed Routing

| Criterion | Test/Method | Expected Result | Status | Evidence |
|-----------|-----------|-----------------|--------|----------|
| `LocalExecutor.from_governed()` instantiates correctly | `test_executor_instantiates_governed_routing_client` | Executor created with `run_id`, bindings, adapters | [ ] PASS | |
| GovernedRoutingNilClient selected (not legacy) | Integration test in cp/os-server | Executor logs show "GovernedRoutingNilClient" instantiation | [ ] PASS | |
| Verbs route to correct adapters | `test_full_execution_with_explicit_routing` | Odoo receives odoo verbs only; comms receives comms verbs only | [ ] PASS | |
| No cross-adapter routing | `test_full_execution_with_explicit_routing` | No verb sent to wrong adapter | [ ] PASS | |
| Unbound verb fails gracefully | `test_execution_with_unbound_verb_fails_gracefully` | Returns error result, no crash | [ ] PASS | |

**Test files:**
- `nilscript/tests/test_phase3_e2e.py::TestGovernedRoutingExecution`
- Integration test (CP + os-server)

---

### 5. Execution Flow

| Criterion | Test/Method | Expected Result | Status | Evidence |
|-----------|-----------|-----------------|--------|----------|
| Settings UI form submission succeeds | HTTP mock test | `/api/cycles` POST returns 200 + cycle_id | [ ] PASS | |
| CP API receives BizSpec correctly | `test_cp_api_endpoint_receives_bizspec` | Payload serialized, domain_id preserved | [ ] PASS | |
| CP logs show compile step | Integration test | logs show "Compiling BizSpec", compile time | [ ] PASS | |
| CP logs show lower step | Integration test | logs show "Lowering to Flow", backend bindings resolved | [ ] PASS | |
| CP stores cycle in database | Integration test | `get_cycle(workspace, cycle_id)` retrieves stored cycle | [ ] PASS | |
| os-server receives Flow + bindings | Integration test | os-server GET `/api/cycles/{cycle_id}` returns flow + domain_id | [ ] PASS | |
| Executor receives correct program | Integration test | Program dict has correct domain_id, backend_bindings | [ ] PASS | |

**Test files:**
- `nilscript/tests/test_phase3_e2e.py::TestSettingsUIToCPFlow`
- Integration test (wosool-hub + CP + os-server)

---

### 6. Execution Results

| Criterion | Test/Method | Expected Result | Status | Evidence |
|-----------|-----------|-----------------|--------|----------|
| Execution returns execution_id | `test_execution_result_has_execution_id` | Result has `execution_id` field | [ ] PASS | |
| Execution returns status | Status field set to one of: queued, running, completed, failed | [ ] PASS | |
| Status transitions correct | `test_execution_status_transitions` | completed=True when status="completed" | [ ] PASS | |
| Error field populated on failure | Integration test | Error contains actionable message when step fails | [ ] PASS | |

**Test files:**
- `nilscript/tests/test_phase3_e2e.py::TestExecutionReturnValues`

---

### 7. Thread Creation & Correlation

| Criterion | Test/Method | Expected Result | Status | Evidence |
|-----------|-----------|-----------------|--------|----------|
| Thread has business_ref | `test_thread_has_business_ref` | Thread.business_ref matches PO pattern (e.g., "PO-2026-007-001") | [ ] PASS | |
| Thread has correlation_id | `test_thread_has_business_ref` | Thread.correlation_id matches message pattern (e.g., "msg_20260707_abc123") | [ ] PASS | |
| Thread data structure complete | `test_thread_data_structure_complete` | All required fields: thread_id, business_ref, correlation_id, cycle_id, status, created_at | [ ] PASS | |
| Thread linked to execution_id | Integration test | Thread.execution_id matches executor.run_id | [ ] PASS | |
| Thread linked to cycle_id | Integration test | Thread.cycle_id == flow.domain_id | [ ] PASS | |

**Test files:**
- `nilscript/tests/test_phase3_e2e.py::TestThreadCreationWithCorrelation`
- Integration test (os-server)

---

### 8. Parity: Legacy Cycle Compatibility

| Criterion | Test/Method | Expected Result | Status | Evidence |
|-----------|-----------|-----------------|--------|----------|
| Effect verbs identical sequence | `test_parity_effect_verbs_identical_sequence` | Compiled flow produces same verbs in same order | [ ] PASS | |
| Exactly 2 human gates | `test_parity_exactly_two_human_gates` | Both approval steps present | [ ] PASS | |
| Email wait with 7-day timeout | `test_parity_email_wait_event_with_7_day_timeout` | Wait event, match dict, timeout_seconds=604800 | [ ] PASS | |
| Timeout escalation routing | `test_parity_timeout_escalation_routing` | Timeout routes to distinct escalation notify step | [ ] PASS | |
| Governance envelope HIGH/IRREVERSIBLE | `test_parity_governance_envelope_high_irreversible` | Envelope matches live cycle's tier | [ ] PASS | |
| All backends bound to Odoo (D8) | `test_parity_backend_bindings_all_odoo_D8` | All effect verbs → "odoo" | [ ] PASS | |
| Legacy cycle still works | `test_backward_compat_legacy_cycle_execution` | Cycles without domain_id still executable | [ ] PASS | |

**Test files:**
- `nilscript/tests/test_phase3_parity_simulation.py` (all tests)
- Integration test (run legacy cyc_order + compiled BizSpec in parallel)

---

### 9. Feature Flags

| Criterion | Test/Method | Expected Result | Status | Evidence |
|-----------|-----------|-----------------|--------|----------|
| `USE_GOVERNED_ROUTING=true` activates | Environment variable test | When flag=true, uses GovernedRoutingNilClient | [ ] PASS | |
| `USE_GOVERNED_ROUTING=false` uses legacy | Environment variable test | When flag=false, uses legacy RoutingNilClient | [ ] PASS | |
| Default behavior correct | Deployment test | Without flag, defaults to true (new behavior) | [ ] PASS | |

**Test files:**
- Integration test (controlplane + feature flag env var)

---

### 10. Logging & Observability

| Criterion | Test/Method | Expected Result | Status | Evidence |
|-----------|-----------|-----------------|--------|----------|
| CP logs compile step | Integration test | Log line: `[CP] Compiling BizSpec: {domain_id}` | [ ] PASS | |
| CP logs backend bindings resolved | Integration test | Log line: `[CP] Backend bindings: {...}` | [ ] PASS | |
| Executor logs verb routing | Integration test | Log line: `[Executor] Routing {verb} to {backend}` | [ ] PASS | |
| Thread creation logged | Integration test | Log line: `[os-server] Thread created: {thread_id}` | [ ] PASS | |
| Error conditions logged clearly | Integration test | Errors include: verb, backend, reason | [ ] PASS | |

**Test files:**
- Integration test with log capture

---

## Test Execution Checklist

### Unit Tests (nilscript)

Run locally:
```bash
cd /home/ubuntu/Downloads/nizam/nilscript
pytest tests/test_phase3_e2e.py -v
pytest tests/test_phase3_parity_simulation.py -v
```

Expected: **All tests PASS**

```
test_phase3_e2e.py::TestBizSpecCompilation::test_bizspec_compiles_with_domain_bindings PASSED
test_phase3_e2e.py::TestBizSpecCompilation::test_compiled_plan_has_all_effect_steps PASSED
test_phase3_e2e.py::TestBizSpecCompilation::test_governance_envelope_aggregates_correctly PASSED
test_phase3_e2e.py::TestFlowLowering::test_flow_preserves_domain_id PASSED
test_phase3_e2e.py::TestFlowLowering::test_flow_preserves_backend_bindings PASSED
test_phase3_e2e.py::TestFlowLowering::test_flow_structure_is_valid PASSED
test_phase3_e2e.py::TestGovernedRoutingExecution::test_executor_instantiates_governed_routing_client PASSED
test_phase3_e2e.py::TestGovernedRoutingExecution::test_full_execution_with_explicit_routing PASSED
test_phase3_e2e.py::TestGovernedRoutingExecution::test_execution_with_unbound_verb_fails_gracefully PASSED
test_phase3_e2e.py::TestSettingsUIToCPFlow::test_hub_settings_form_serializes_bizspec PASSED
test_phase3_e2e.py::TestSettingsUIToCPFlow::test_cp_api_endpoint_receives_bizspec PASSED
test_phase3_e2e.py::TestThreadCreationWithCorrelation::test_thread_has_business_ref PASSED
test_phase3_e2e.py::TestThreadCreationWithCorrelation::test_thread_data_structure_complete PASSED
test_phase3_e2e.py::TestExecutionReturnValues::test_execution_result_has_execution_id PASSED
test_phase3_e2e.py::TestExecutionReturnValues::test_execution_status_transitions PASSED
test_phase3_e2e.py::test_phase3_complete_flow PASSED

test_phase3_parity_simulation.py::test_parity_effect_verbs_identical_sequence PASSED
test_phase3_parity_simulation.py::test_parity_exactly_two_human_gates PASSED
test_phase3_parity_simulation.py::test_parity_email_wait_event_with_7_day_timeout PASSED
test_phase3_parity_simulation.py::test_parity_timeout_escalation_routing PASSED
test_phase3_parity_simulation.py::test_parity_governance_envelope_high_irreversible PASSED
test_phase3_parity_simulation.py::test_parity_backend_bindings_all_odoo_D8 PASSED
test_phase3_parity_simulation.py::test_parity_flow_step_count_consistent PASSED
test_phase3_parity_simulation.py::test_parity_notify_messages_bilingual PASSED
test_phase3_parity_simulation.py::test_parity_capability_resolution PASSED
test_phase3_parity_simulation.py::test_parity_step_binding_carries_through PASSED
test_phase3_parity_simulation.py::test_parity_control_strategy_matches PASSED
test_phase3_parity_simulation.py::test_parity_round_trip_nil_grammar PASSED
test_phase3_parity_simulation.py::test_d8_improvement_explicit_vs_implicit_routing PASSED
test_phase3_parity_simulation.py::test_backward_compat_legacy_cycle_execution PASSED
test_phase3_parity_simulation.py::test_parity_summary_live_cyc_order_can_be_compiled PASSED

===== 32 passed in X.XXs =====
```

### Integration Tests (wosool-hub + CP + os-server)

| Test | Command | Status |
|------|---------|--------|
| Hub Settings UI renders | Manual or E2E: `npm run dev`, visit `/settings/cycle-definition` | [ ] PASS |
| Form submits to CP | E2E test or Playwright | [ ] PASS |
| CP stores cycle | Query controlplane.db | [ ] PASS |
| os-server retrieves flow | HTTP GET `/api/cycles/{cycle_id}` | [ ] PASS |
| Execution succeeds | Trigger cycle, check execution logs | [ ] PASS |
| Thread created with correlation | Query os-server threads table | [ ] PASS |

---

## Coverage Summary

| Component | Coverage Target | Method |
|-----------|-----------------|--------|
| BizSpec compilation | 100% (new compiler stack) | `test_phase3_e2e.py + test_phase3_parity_simulation.py` |
| Flow lowering | 100% (deterministic transformation) | `test_phase3_e2e.py::TestFlowLowering` |
| Governed routing | 100% (routing dispatch logic) | `test_phase3_e2e.py::TestGovernedRoutingExecution` |
| Parity (legacy ↔ compiled) | 100% (live cycle compatibility) | `test_phase3_parity_simulation.py` |
| Thread correlation | 100% (identity + business ref) | `test_phase3_e2e.py::TestThreadCreationWithCorrelation` |
| Settings UI → CP → Executor | Integration tests | E2E / manual |

**Target: 80%+ coverage across all new Phase 3 code**

Run coverage:
```bash
pytest tests/test_phase3_*.py --cov=nilscript.compiler --cov=nilscript.kernel.executor --cov-report=term-missing
```

---

## Known Gaps & Deferreds

| Item | Status | Reason | Phase |
|------|--------|--------|-------|
| Settings UI step builder full UI | PENDING | Requires React component work | Phase 4 |
| Hermes integration (BizSpec ← Intent) | PENDING | Wave 5 AI boundary | Phase 5 |
| Policy Engine facade | PENDING | Authority Phase 1 (non-blocking) | Phase 4 |
| Omnichannel correlation layers 3–5 | PENDING | Named Correlation Engine | Phase 6 |
| Cycle-Agent isolation layer rewrite | PENDING | Intent scoping | Phase 5 |

---

## Sign-Off

**Phase 3 Execution Complete When:**

- [ ] All unit tests pass locally (32 tests)
- [ ] Integration tests pass (Settings UI → CP → Executor → Thread)
- [ ] Parity CI passes (legacy cyc_order ↔ compiled identical semantics)
- [ ] Feature flags tested (USE_GOVERNED_ROUTING true/false)
- [ ] Backward compat verified (old cycles still work)
- [ ] Logging verified (all critical steps logged)
- [ ] Coverage ≥80% on compiler + executor code
- [ ] No new security warnings in scan
- [ ] Deployment checklist cleared (see next doc)

**Approved by:** [Phase 3 Lead]  
**Date:** [Completion Date]
