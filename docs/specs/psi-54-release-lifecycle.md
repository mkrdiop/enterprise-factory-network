# PSI-54 — Registered Factory Release lifecycle

- **Status:** Normative specification proposal; pending explicit acceptance and independent review
- **Version:** 1.1.0
- **Dependencies:** PSI-37, PSI-40, PSI-45, PSI-51, PSI-52, PSI-53

## 1. Candidate versus registered release
The Network `FactoryRelease` aggregate has exactly five states: `published`, `suspended`, `deprecated`, `revoked`, `archived`. `draft` and `validated` are authoring-side workflow states and are not persisted Network release states or members of this aggregate. The owning authoring workflow is outside PSI-54; PSI-54 defines no candidate persistence or candidate state machine.

Network accepts a publication request only after the authoring boundary asserts validation and Network independently verifies canonical manifest identity, PSI-40 immutable digest, PSI-51 signature evidence, PSI-53 authorization and obligations. Network does not accept or persist a mutable candidate. Persisted candidates require a separate aggregate and promotion contract.

## 2. Exact identity and separation
Lifecycle attaches to one exact persisted release coordinate: canonical publisher URI, exact Factory ID, opaque release version and immutable digest, internally keyed by `release_record_id`. It never attaches to latest, a mutable Factory pointer, signature envelope, key or execution. Lifecycle metadata never changes canonical manifest bytes or digest.

PSI-45 execution state, PSI-51 signature validity, PSI-53 publisher/key trust, PSI-52 authorization, compatibility and publisher namespace retirement remain separate facts. PSI-54 does not cancel, retry, or rewrite an existing execution; PSI-45 owns execution behavior.

## 3. State semantics and transitions
| State | Discovery | Exact retrieval | New invocation |
|---|---|---|---|
| published | ordinary discovery subject to authorization | authorized | eligible subject to policy, trust and compatibility |
| suspended | hidden from ordinary discovery | authorized administrative/audit reads | denied |
| deprecated | discoverable with deprecation metadata | authorized | eligible subject to policy, trust and compatibility |
| revoked | hidden from ordinary discovery | authorized security/audit reads | denied |
| archived | hidden from ordinary discovery | retention/audit access | denied |

Legal transitions only: published → suspended/deprecated/revoked; suspended → published/deprecated/revoked; deprecated → revoked/archived; revoked → archived. All other transitions, self-transitions, transitions from archived and transitions to/from draft or validated are rejected. Revoked cannot be restored; replacement requires a new exact release coordinate. Every transition invokes PSI-53 with the exact PSI-52 lifecycle action. PSI-54 does not map release lifecycle transitions onto PSI-45 execution states or emit PSI-45 execution events.

## 4. Idempotency contract
An idempotency record is scoped by `(tenant_id, authenticated_principal_id, exact_release_coordinate, operation)`, where the exact release coordinate is the canonical publisher URI, Factory ID, opaque release version and immutable digest. This coordinate exists before initial publication commits, so the same scope works for first publication and later transitions without relying on a database surrogate ID. The key is unique only within that scope and is bound to a canonical request fingerprint. Lookup occurs after authentication and scope derivation but **before** reading current lifecycle state or checking expected revision.

- Same scoped key + same fingerprint: return the persisted original result, stable reason and response reference exactly, whether originally accepted or rejected. Do not re-run transition validation or authorization.
- Same scoped key + different fingerprint: return `IDEMPOTENCY_CONFLICT`.
- Same raw key in a different tenant/principal/release/operation scope is a distinct key, not a collision or replay.
- No matching scoped key: evaluate the new request normally.

The idempotency record and original outcome are persisted atomically with the corresponding transition result. A replay MUST NOT manufacture an accepted result or replace the original reason with a generic replay reason.

## 5. Transition transaction and event
Transition request fields: exact release coordinate, expected revision, target state, non-empty reason, stable reason code, scoped idempotency key and correlation ID. Revocation additionally requires an evidence reference. Actor identity comes from PSI-53 authenticated principal, never the request body.

After idempotency lookup, validate legal transition, authorization, reason/evidence and transition-specific preconditions, then compare expected revision. At commit recheck consumed evidence generations/freshness and use optimistic concurrency. Append immutable event, update current-state projection, persist idempotency outcome and PSI-53 audit outbox in one DB transaction. At most one concurrent request using a given expected revision succeeds. Corrections are compensating events, never history edits/deletes.

Lifecycle event fields include event ID, release record ID, exact coordinate/digest snapshot, from/to, revision, actor, exact PSI-52 action, reason/reason code, evidence reference, authorization decision reference, policy digest/version, evidence generations, correlation ID, scoped idempotency identity, request fingerprint and UTC committed timestamp.

## 6. Initial publication event
Creation is not a transition from a prior registered lifecycle state. Network inserts the release directly in `published` and writes the initial event in the same database transaction as the release row and PSI-53 audit outbox:
- event ID: globally unique, stable event identifier;
- event type: `factory_release.published`;
- action: `release.publish` (the composite authorization decision also records each required check, including conditional `factory.register`);
- revision: `1`;
- `from_state: null`, `to_state: published`;
- actor: authenticated PSI-53 principal;
- exact publisher/Factory/release coordinate and immutable digest snapshot;
- exact authorization decision reference covering required publication checks;
- UTC committed timestamp;
- durable idempotency outcome and audit outbox record.

The publication request must be authoring-validated; digest and signature verified; exact coordinate established; and all applicable `factory.register`, `factory.publish`, `release.publish` checks permitted. `factory.register` is required only when this operation creates the Factory; an existing Factory release publication requires `factory.publish` and `release.publish`. PSI-50's detached envelope has no signer quorum semantics. PSI-51 reports independent per-signer cryptographic/trust outcomes; PSI-52 policy defines the exact required signer identity set and PSI-53 enforces each required identity without inventing an any-signer or threshold rule. Release insertion, revision-1 event and audit outbox are atomic. Object-store I/O is outside the DB transaction; a failed final commit exposes no registered release.

## 7. Lifecycle admission and PSI-45 boundary
Lifecycle admission is `eligible` for published/deprecated, `denied` for suspended/revoked/archived and `indeterminate` when authoritative release/lifecycle evidence is unavailable, malformed or stale. Eligibility is not authorization. Runtime uses PSI-54 admission before PSI-45 execution admission. PSI-45's separate execution state model remains authoritative for invocation states, transition events, event replay and revision CAS. PSI-54 does not define PSI-45 scheduling, retries, cancellation or terminal execution statuses, and lifecycle transitions never mutate an execution state.

## 8. Conformance and acceptance
The v1.1 vectors cover legal/illegal transitions, original accepted and rejected idempotent replays, scoped key isolation, same-key/different-fingerprint conflict, and atomic initial publication event creation. Independent implementations MUST validate schemas and execute every vector. Integration acceptance additionally requires concurrent revision tests, persistence/transaction tests, exact-coordinate isolation and Registry/Runtime parity.
