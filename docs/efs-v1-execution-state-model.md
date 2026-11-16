# EFS v1 Shared Execution State Model

**Status:** Normative EFS v1 lifecycle state model; implementation baseline for PSI-45  
**State/event version:** 1.0  
**Authority:** PSI-42 capability/contract model and PSI-44 execution envelope  
**Affected products:** Factory Studio, Factory Connect, Factory Runtime, Enterprise Factory Network

## 1. Authority and boundaries

This defines one shared deterministic lifecycle vocabulary. It does not replace the PSI-42 capability/contract model or PSI-44 message envelope. PSI-44 remains authoritative for exact invocation context, message types, correlation/causation and mode-specific message semantics. PSI-43 remains the only payload validator.

The reference implementation is registry/execution_state.py; schemas and conformance corpus live beside the PSI-44 contract. Product surfaces MUST consume these definitions and MUST NOT create competing lifecycle vocabularies.

The validator is pure. It does not execute factories, schedule workers, persist events, implement queues, authorize invocation, enforce tenant policy, or provide concurrency control. A persistence adapter MUST atomically compare-and-swap the expected revision when committing an accepted transition.

## 2. State vocabulary

| State | Meaning |
| --- | --- |
| created | Local initial snapshot exists; no request/event transition has been accepted |
| requested | A validated PSI-44 request or event initiated this invocation |
| accepted | Receiver emitted an accepted disposition |
| queued | Receiver reported queued disposition; this is not a durability or delivery guarantee |
| running | Runtime explicitly started work or emitted streaming progress/data |
| waiting | Runtime adapter explicitly reports a wait condition |
| succeeded | Successful terminal result |
| failed | Failure terminal result |
| cancelled | Cancellation terminal state, only through an explicitly governed control event |

Terminal states are succeeded, failed, and cancelled. No terminal state can transition to any other state.

## 3. Normative transitions

The machine-readable table is conformance/execution/v1/state-vectors.json.

| Event | Allowed prior state(s) | Resulting state |
| --- | --- | --- |
| request | created | requested |
| accepted | requested | accepted |
| queued | requested | queued |
| started | requested, accepted, queued, waiting | running |
| progress | accepted, queued, running | running |
| waiting | running | waiting |
| resumed | waiting | running |
| succeeded | requested, accepted, queued, running, waiting | succeeded |
| failed | requested, accepted, queued, running, waiting | failed |
| cancelled | created, requested, accepted, queued, running, waiting | cancelled |

PSI-44 mapping is deterministic: request/event -> request; accepted disposition -> accepted or queued; progress -> progress; result -> succeeded; error -> failed. A progress envelope moves accepted/queued execution to running, or records a same-state running audit event. PSI-44 streaming sequence is not the lifecycle revision and is not proof of delivery order.

Waiting/resumed are runtime-adapter lifecycle signals, not new PSI-44 message types. Cancellation is not added to envelope version 1.0: it requires a separate governed control event with a non-empty governance reference. No transport-specific cancellation is inferred.

## 4. Transition event and state snapshot

A transition event carries version, unique event ID, invocation ID, correlation ID, optional causation ID, source, source message ID, event type, prior state, resulting state, expected revision, stable reason code, occurrence time and exact immutable PSI-44 context.

The state snapshot carries state version, invocation ID, correlation ID, exact context, current state, monotonically increasing revision and last applied event ID. Schemas:

- schemas/execution/v1/execution-state.schema.json
- schemas/execution/v1/execution-state-event.schema.json

No independent publisher, Factory, release, capability or contract identity is created. These values are preserved from exact PSI-44 context.

## 5. Ordering, concurrency and replay

Each successful transition increments the per-invocation revision by one. An event MUST carry the revision it expects. A stale revision is rejected with EFS_EXECUTION_STATE_REVISION_CONFLICT. This is a compare-and-swap precondition, not a lock; concurrent writers MUST enforce it atomically in their persistence boundary.

The caller supplies its durable event-ID index to the pure validator:

- same event ID and identical event content: accepted as a replay with no state mutation;
- same event ID and different content: rejected with EFS_EXECUTION_STATE_EVENT_ID_CONFLICT;
- stale expected revision or incorrect prior state: rejected; caller must reload and reconcile rather than blindly retry.

The model does not infer exactly-once processing, delivery order, durable queueing, retry safety, idempotency of the underlying capability, or replayability from PSI-44 stream sequence. Replay handling only makes application of the same recorded transition event idempotent at this state boundary.

## 6. Diagnostics and failure behavior

Diagnostics are stable, machine-readable, use RFC 6901-style paths, and are deterministically sorted. The catalogue is conformance/execution/v1/state-diagnostic-catalog.json. Invalid events do not mutate the input snapshot. Invalid transitions, correlation/context changes, duplicate-ID conflicts, stale revisions and terminal-state attempts fail closed.

## 7. Product responsibilities

- Factory Studio uses the shared state/event schemas and vectors in authored examples and previews; it does not invent a separate lifecycle.
- Factory Connect maps external request/response/event signals to PSI-44 envelopes and shared lifecycle events; unsupported semantics remain explicit.
- Factory Runtime owns actual execution and may emit governed runtime lifecycle signals; it preserves exact PSI-44 context and uses atomic revision checks in its state store.
- Enterprise Factory Network distributes normative schemas, validator and corpus; registry/Passport remains release metadata, not runtime state authority.

## 8. Explicit non-goals

No worker engine, scheduler, queue, database persistence, transport implementation, authorization, policy evaluation, tenant isolation, retry, exactly-once delivery, cancellation protocol, or product-specific state model is implemented. Cancellation is represented as a terminal state only when an external governed control event authorizes the transition; PSI-44 envelope 1.0 remains unchanged.

## 9. Conformance

- Vectors: conformance/execution/v1/state-vectors.json
- Acceptance mapping: conformance/execution/v1/state-acceptance.json
- Diagnostic catalogue: conformance/execution/v1/state-diagnostic-catalog.json
- Fixture catalogue: conformance/execution/v1/state-fixture-catalog.json
- Tests: tests/test_execution_state.py

Every PSI-45 acceptance criterion maps to executable tests. Both schemas use Draft 2020-12 and local references only. Existing PSI-44 envelope schema and report contracts are unchanged.
