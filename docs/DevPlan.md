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
- [ ] Recovery regression suite against full workflow lifecycle

### 17.2 Workflow Resume / Recovery
- [ ] Define resumable workflow checkpoint contract
- [ ] Restore dependency / execution state
- [ ] Resume only safe states
- [ ] Prevent duplicate completed work
- [ ] Recovery idempotency
- [ ] Crash/restart integration tests

### 17.3 Crash Consistency
- [ ] Atomic checkpoint semantics
- [ ] Interrupted write handling
- [ ] Corrupt-state quarantine
- [ ] Recovery failure isolation

### 17.4 Concurrency / Lease Control
- [ ] Task lease boundary
- [ ] Lease expiry
- [ ] Ownership fencing
- [ ] Duplicate worker prevention

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
Run and validate the new **full workflow recovery regression suite**, then close 17.1 and enter 17.2 only after the complete test suite remains green.
