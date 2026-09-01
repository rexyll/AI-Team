# AI-Team Development Plan

## Phase 16 — Observability & Alerting

### 16.5 Alerting
- [x] Alert foundation
- [x] Failure-rate threshold rule
- [x] Latency threshold rule
- [x] Retry threshold rule
- [x] Reviewer rejection / recovery alerts
- [x] Tool-loop anomaly alerts
- [x] Bounded tool telemetry
- [x] Deduplication
- [x] Cooldown
- [x] Provider-independent interface
- [x] Alert rule regression tests

### 16.6 Alert Delivery
- [x] Provider-independent delivery boundary
- [x] Structured alert event
- [x] Structured-log sink
- [x] Webhook sink + Network Egress enforcement
- [x] Bounded retry / failure semantics
- [x] Delivery observability
- [x] Cross-component delivery regression contracts
- [x] Phase 16.6 implementation complete

## Phase 17 — Runtime Reliability

### 17.1 Runtime State Persistence
- [x] State-store boundary
- [x] Snapshot isolation
- [x] TaskManager lifecycle persistence integration
- [x] Atomic lifecycle commit / rollback
- [x] Recovery loading boundary
- [x] Recovery snapshot validation
- [x] Persistent manager bootstrap from recovered state
- [x] Full workflow lifecycle recovery regression
- [x] Phase 17.1 complete

### 17.2 Workflow Resume / Recovery
- [x] Define resumable workflow checkpoint contract
- [x] Restore dependency / execution state
- [x] Resume only safe states
- [x] Prevent duplicate completed work
- [x] Recovery idempotency
- [x] Crash/restart integration tests

### 17.3 Crash Consistency
- [x] Atomic checkpoint semantics
- [x] Interrupted write handling
- [x] Corrupt-state quarantine
- [x] Recovery failure isolation

### 17.4 Concurrency / Lease Control
- [x] Task lease boundary
- [x] Lease expiry
- [x] Ownership fencing
- [x] Duplicate worker prevention
  - [x] Shared execution lease boundary
  - [x] Concurrent entry rejection contract
  - [x] Failure-safe lease cleanup contract
  - [x] Integrate execution lease into TaskWorkflow
  - [x] End-to-end duplicate execution regression

### 17.5 Stuck Task Detection
- [ ] Heartbeat / liveness contract
- [ ] Stuck-task classification
- [ ] Recovery trigger

### 17.6 Recovery Observability
- [ ] Recovery metrics
- [ ] Recovery tracing
- [ ] Recovery audit events

### 17.7 Full Reliability Regression
- [ ] Persistence → recovery → resume end-to-end tests
- [ ] Crash simulation
- [ ] Concurrency regression
- [ ] Full test suite

## Phase 19 — Production Scale / v0.2 Architecture

### 19.1 Multi-project scheduling and resource governance
- [x] Project execution scope identity
- [x] Project-local resource admission
- [x] Deterministic multi-project scheduling
- [x] Cross-project resource isolation
- [x] Project execution handoff
- [x] Scheduling/admission observability
- [x] Focused and full regression coverage

### 19.2 Long-lived execution and recovery

#### 19.2.1 Durable project execution checkpoint contract
- [x] Immutable project execution checkpoint identity and scope
- [x] Reuse canonical `WorkflowCheckpoint`
- [x] Recoverable vs terminal checkpoint states
- [x] Atomic filesystem checkpoint store
- [x] Project-scoped recoverable enumeration
- [x] Task/project scope validation
- [x] Publish checkpoint through `ProjectExecutionHandoff`
- [x] Reconstruct active reservations after restart
- [x] Require authoritative reconciliation before retry/finalization
- [x] Crash/restart integration across checkpoint, TaskManager, and TaskWorkflow

### 19.3 Cost / model governance
#### 19.3.1 Project model governance policy — first slice
- [x] Immutable provider/model route contract
- [x] Per-project token/call budget contract
- [x] Deterministic model admission decision contract
- [x] Primary-route health and explicit fallback semantics
- [x] Cross-project budget isolation regression coverage
- [ ] Runtime token/call attribution
- [ ] Canonical LLM invocation integration
- [ ] Provider/model cost-rate configuration
- [ ] Budget-aware scheduler admission
- [ ] Degradation/fallback observability

### Current next step
Validate the **19.3.1 project model governance policy** with focused tests and full regression. Then integrate usage attribution into the existing LLM invocation boundary without introducing a second runtime or bypassing existing observability/security controls.
