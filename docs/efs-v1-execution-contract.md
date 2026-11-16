# EFS v1 Shared Execution Contract

**Status:** Normative EFS v1 execution-envelope contract; implementation baseline for PSI-44  
**Envelope version:** `1.0`  
**Authority:** EFS v1 capability/contract model in `docs/efs-v1-capability-contract-model.md` (PSI-42)  
**Affected products:** Factory Studio, Factory Connect, Factory Runtime, Enterprise Factory Network

## 1. Authority and non-duplication

This document defines how an invocation and its outcomes are represented across the four Enterprise Factory products. It does not define another capability or contract model. PSI-42 remains authoritative for capability identity, exact contract identity `(contract.id, contract.version)`, payload schemas, declared errors, governed guarantees and interaction-mode meaning.

The canonical machine-readable envelope schema is `schemas/execution/v1/execution-envelope.schema.json`. The Enterprise Factory Network repository owns the schema, reference validator, diagnostics, examples, vectors and conformance tests. Product adapters MUST consume these definitions and MUST NOT introduce product-local envelope, correlation, error-code, state or guarantee semantics.

The envelope version is independent of `efsVersion`, Factory release version, capability contract version, execution-profile version, transport protocol version and implementation build version.

## 2. Exact invocation context

Every message MUST carry a `context` object containing:

- `publisherId`: exact canonical publisher URI from ADR-003;
- `factoryId`: exact publisher-scoped Factory identifier;
- `releaseVersion`: exact opaque release version;
- `releaseDigest`: exact approved digest profile, algorithm and value for that immutable release;
- `capabilityId`: exact capability identifier within that release;
- `contract.id` and `contract.version`: exact PSI-42 contract coordinate;
- `executionProfileId`: the explicitly selected profile declared by that capability;
- `executionMode`: exactly one of `sync`, `async`, `streaming`, `event`.

All identifiers and coordinates are compared exactly. A message MUST NOT resolve “latest”, infer a release or contract version, switch a profile, or silently substitute a different capability. The contract URI is an opaque identifier and MUST NOT be dereferenced. The release digest binds the message to the immutable release bytes, not to a storage locator.

A capability that has no explicit `executionProfiles` selection cannot be assigned an ambient profile by an adapter. For embedded execution, the selected profile ID and mode MUST match exactly one declared profile and its declared modes. For externally referenced execution, the profile reference ID MUST resolve exactly; the referenced immutable profile artifact must be verified before a runtime claims that its mode is supported. This envelope definition does not retrieve external profile artifacts.

## 3. Common message fields and propagation

All message types carry:

- `envelopeVersion`: `1.0`;
- `messageType`: the discriminated message kind;
- `messageId`: opaque producer-assigned message identifier;
- `invocationId`: stable identifier for this invocation;
- `context`: the exact immutable invocation context above;
- `correlationId`: stable identifier propagated across the interaction;
- `occurredAt`: RFC 3339 date-time.

A follow-up message MUST include `causationId`, identifying the immediately preceding message in the observed causal chain. The initial `request` or `event` MAY include a causation identifier when it is itself caused by an upstream message. Identifiers are opaque strings; EFS v1 does not require UUID generation or a particular tracing vendor.

The message producer assigns `messageId`. Consumers MUST preserve `invocationId`, `correlationId` and the complete `context` through accepted, progress, result and error messages. Causation records the direct predecessor; correlation groups the wider interaction.

## 4. Message types

| Type | Meaning | Mode |
| --- | --- | --- |
| `request` | Starts a request/response, asynchronous or streaming invocation. `payload` is the capability input object. | sync, async, streaming |
| `event` | Represents an event occurrence that initiates or advances an event-driven capability. `payload` is the capability input object. | event |
| `accepted` | Receiver acknowledges acceptance or reports that the request is queued. | async, streaming |
| `progress` | A streaming progress signal or one streaming data item. | streaming |
| `result` | Terminal successful outcome. `payload` is one capability output object. | any declared mode |
| `error` | Terminal failure using one declared contract error code and optional structured details. | any declared mode |

### 4.1 Accepted and queued

`disposition` is either `accepted` or `queued`. It reports only what the receiver says it has done at this boundary. In particular, `queued` MUST NOT be interpreted as durable persistence, guaranteed delivery, exactly-once processing, retry safety, or eventual completion unless a separate governed profile explicitly defines that guarantee.

### 4.2 Progress and streaming data

A `progress` message has a producer-assigned non-negative `sequence` and `eventKind`:

- `progress`: a progress signal with no capability data payload;
- `data`: one streaming data item whose `payload` is validated against the exact capability `outputs` schema.

The sequence is an ordinal assigned by the producer. It does not establish transport delivery order, contiguous delivery, replayability, deduplication or exactly-once delivery. Consumers MUST NOT infer these guarantees.

### 4.3 Result and error

A `result.payload` MUST be validated against the exact selected contract's `outputs` schema. A `request.payload` and `event.payload` MUST be validated against `inputs`. A streaming data item MUST be validated against `outputs`.

An `error.code` MUST exactly match one declared code in the selected capability contract. The envelope does not replace or reinterpret the contract's error vocabulary. If `error.details` is present, the selected error declaration MUST contain a structured details schema and the details MUST be validated against it. Human-readable `error.message` is optional and MUST NOT be used as a machine discriminator.

All payload and structured error-details validation MUST be delegated to the shared PSI-43 capability contract validator, using the exact context coordinates. This PSI-44 envelope validator does not implement a second payload schema engine.

## 5. Mode-specific message flow

The following are the allowed message-level patterns in envelope version 1.0:

- **sync:** `request -> result | error`
- **async:** `request -> accepted -> result | error`; a receiver MAY produce a result/error directly after the request when no separate acceptance message is emitted.
- **streaming:** `request -> accepted -> progress* -> result | error`; a receiver MAY produce a terminal result/error directly after acceptance.
- **event:** `event -> result | error`

The transition helper checks one observed causal edge and propagation of invocation, correlation and context. It is not the execution lifecycle state machine. PSI-45 owns the normative state vocabulary, legal state transitions, terminal-state handling and replay/idempotency semantics. A sequence of envelopes MUST NOT be treated as proof of durable state or successful execution merely because a message is syntactically valid.

EFS v1 envelope version 1.0 does not define a cancellation message or cancellation guarantee. An adapter MUST NOT claim that cancellation is supported or infer cancellation semantics from a transport. A future cancellation contract requires a governed EFS profile/specification change.

## 6. Guarantees and transport independence

The envelope deliberately contains no implicit `retryable`, `idempotent`, `durable`, `ordered`, `replayable`, `cancellable`, `approvalRequired` or `compensatable` flags. These are not standard envelope fields in version 1.0. A consumer MUST interpret a guarantee only when its key and semantics are defined by a governed EFS profile and explicitly declared by the selected capability/execution profile.

No transport is mandated. MCP, A2A, OpenAPI, CloudEvents, HTTP, gRPC, WebSocket, message brokers and future protocols are possible adapter choices, not EFS semantics. A protocol adapter MUST preserve exact invocation context, message type, correlation/causation, payload, declared error code and mode constraints. It MUST NOT elevate transport-specific behavior into a shared EFS guarantee without governance.

## 7. Validation and product responsibilities

The reference validator performs:

1. Draft 2020-12 envelope-schema validation with asserted date-time format;
2. exact binding of publisher, Factory, release version/digest, capability, contract ID/version, profile and mode to the selected manifest;
3. exact declared error-code checking;
4. capability execution-profile binding and embedded mode checking;
5. causal-edge validation for message type, invocation ID, correlation ID, context and causation ID;
6. delegation of inputs, outputs and structured error details to the PSI-43 validator through an explicit adapter port.

Product boundaries:

- **Factory Studio:** authors examples and validates envelopes against the shared schema; does not invent alternate field names.
- **Factory Connect:** maps native event/request protocols to the shared message types while preserving exact context and causal identifiers.
- **Factory Runtime:** validates inputs before dispatch, outputs on result/data, and declared errors/details; enforces exact selected profile and mode.
- **Enterprise Factory Network:** publishes and distributes the canonical schema, fixtures and conformance requirements. It does not execute capabilities or create a second runtime state source.

The registry's immutable release remains authoritative. A Passport is a derived read-only view and is not an invocation authority or runtime state store.

## 8. Conformance corpus

- Schema: `schemas/execution/v1/execution-envelope.schema.json`
- Examples: `conformance/execution/v1/examples.json`
- Semantic vectors: `conformance/execution/v1/vectors.json`
- Acceptance mapping: `conformance/execution/v1/acceptance.json`
- Diagnostic catalogue: `conformance/execution/v1/diagnostic-catalog.json`
- Fixture catalogue: `conformance/execution/v1/fixture-catalog.json`
- Tests: `tests/test_execution_contract.py`

The examples cover sync, async, streaming and event modes, including accepted/queued, progress/data, result and declared error messages. They are transport-neutral and are not protocol implementation samples.

## 9. Explicit non-goals

Envelope version 1.0 does not implement or define a runtime engine, workers, scheduling, queues, transports, retries, idempotency, cancellation, durable acceptance, delivery guarantees, policy authorization, publisher trust, signature verification, semantic compatibility or the PSI-45 lifecycle state machine.

## 10. Change history

- 2026-11-16 — PSI-44 shared transport-neutral envelope model and executable conformance corpus established.
