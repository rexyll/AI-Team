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
- [ ] Duplicate worker prevention
  - [x] Shared execution lease boundary
  - [x] Concurrent entry rejection contract
  - [x] Failure-safe lease cleanup contract
  - [ ] Integrate execution lease into TaskWorkflow
  - [ ] End-to-end duplicate execution regression

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

### Current next step
Complete **17.4.4 Duplicate Worker Prevention** by integrating the lease boundary into the actual `TaskWorkflow.execute()` entry point and adding an end-to-end concurrent execution regression. A reusable `LeaseGuardedExecutor` now provides the shared execution boundary and deterministic race contracts; the workflow integration remains intentionally pending until it can be added without bypassing the existing Developer/Tester/Reviewer lifecycle semantics.
