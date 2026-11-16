# PSI-53 — Authorization, trust and revocation enforcement

- **Status:** Normative specification proposal; pending owner and independent review
- **Version:** 1.0.0
- **Date:** 2026-11-16
- **Dependencies:** PSI-37, PSI-40, PSI-50, PSI-51, PSI-52
- **Conformance:** `schemas/psi-53-enforcement-v1.schema.json`; `tests/conformance/psi-53-enforcement-v1.json`

## 1. Settled enforcement contract

PSI-53 adopts one mandatory server-side Policy Enforcement Point (PEP) and one deterministic, side-effect-free Policy Decision Point (PDP). The PEP is the only authorization boundary for registry, administrative and Runtime protected operations. Every API handler and internal service path MUST call it; UI-only checks are not enforcement.

A protected operation is permitted if and only if: (1) the principal is authenticated by a trusted authentication boundary; (2) the PEP derives the subject, action and exact resource from trusted server-side context; (3) all required pinned policies are available and their PSI-52 profile/digest verified; (4) the PDP outcome is exactly `permit`; (5) every obligation is recognized and durably fulfilled; (6) required publisher/key trust evidence is current and acceptable; (7) release operations pass PSI-54 lifecycle admission; (8) all consumed evidence remains fresh at commit; and (9) the protected mutation and audit outbox commit atomically.

Missing, malformed, unknown, stale, unavailable or conflicting required evidence means **no protected operation**. Preserve `deny` and `indeterminate` as distinct PDP outcomes. Never convert outage or uncertainty into allow.

## 2. Component boundaries

### Authenticated principal adapter
Accepts a principal established by the configured identity boundary, never a subject/role object supplied by the request. Emits the PSI-52 subject shape. Every attribute retains value, source, observed_at and expires_at. Reject missing/ambiguous principals and unverified privilege claims.

### Trusted attribute provider
Returns provenance-bearing attributes. Enforce `observed_at <= evaluation_time < expires_at`. Required missing/invalid attributes and provider errors are indeterminate, never silently defaulted.

### Immutable policy bundle resolver
Resolves exact configured policy ID/version/profile/digest references. Verify PSI-52 digest before use. No “latest” substitution and no omission of a required unavailable policy. Cache immutable bundles by exact digest.

### Reference PDP
Pure deterministic evaluation of the complete PSI-52 request and exact bundle. No DB, network, ambient clock, identity-provider or filesystem dependency. Evaluation time is explicit. Preserve PSI-52 deny-overrides, indeterminate-overrides-permit, default-deny, order independence, exact selectors, finite actions and obligation aggregation.

### Trust authority / PSI-51 resolver adapter
PSI-53 owns publisher/key trust and revocation evidence, and implements the existing `PublisherKeyResolver.resolve(publisher_id, key_id, required_algorithm, required_usage)` seam. Preserve publisher/key binding, algorithm/usage, public key, `KeyTrustStatus`, validity interval and monotonic `evidence_version`. PSI-51 remains responsible for cryptographic verification using verifier UTC time. A valid signature does not imply trusted publisher/key; trust does not imply valid signature. Publisher namespace retirement, publisher distrust, key revocation and release revocation are separate facts. PSI-53 MUST NOT persist a competing release lifecycle state.

### Policy Enforcement Point
Maps every route and internal operation to exactly one PSI-52 action/resource, derives exact coordinates from validated input and authoritative registry records, evaluates PDP, fulfills obligations, composes trust and PSI-54 admission, rechecks freshness at commit, and emits durable audit. Unknown route/action, incomplete coordinates or cross-tenant mismatch fail closed.

Capability invocation uses `capability.invoke` against the exact capability resource including publisher URI, Factory ID, opaque release version and capability ID. Do not add a new `execution_target` action to PSI-52 v1.

### Audit sink
For PostgreSQL-backed mutations, write an append-only logical audit/outbox record in the same transaction as the protected mutation. If outbox insertion fails, roll back the mutation. External immutable-store delivery may be asynchronous after the durable outbox commit. Record actor, exact resource/action, policy IDs/versions/digests, outcome/reason, trust/lifecycle evidence versions, obligation outcomes, correlation/idempotency IDs and timestamps. Never record private keys, bearer tokens or raw sensitive attribute values. Cryptographic tamper-evidence is not claimed by a normal append-only table.

## 3. Minimum route/action/resource map

| Operation | Action(s) | Resource |
|---|---|---|
| Factory registration | `factory.register` | prospective exact Factory under authenticated publisher |
| Release publication | `factory.publish` AND `release.publish` (separate decisions) | exact Factory and exact release |
| Factory read/discovery | `factory.read` / `factory.discover` | exact publisher + Factory |
| Release / Passport read | `release.read` | exact release |
| Capability invocation | `capability.invoke` | exact capability within exact release |
| Suspend / deprecate / revoke / archive | matching `release.*` action | exact persisted release |
| Publisher key management | `publisher.key.manage` | exact publisher |
| Policy read/manage | `registry.policy.read` / `registry.policy.manage` | registry |

Composite operations evaluate every listed action. A permit for one action does not imply another. The inventory MUST include HTTP routes, jobs, admin commands and internal service entry points; tests MUST prove no alternate path bypasses the PEP.

## 4. Publication and commit race

Before side effects, canonicalize manifest identity, authenticate publisher binding, construct prospective exact resource coordinates and authorize registration/publication. Persist immutable artifact bytes outside the DB transaction. At finalization, open the DB transaction, re-read authoritative identity and policy/trust/lifecycle evidence versions, verify freshness, then commit release + initial PSI-54 event + audit outbox atomically. If evidence changed, re-evaluate; never commit on stale preflight permit. Do not hold a DB transaction across object-store I/O. Apply the same commit-boundary recheck to lifecycle transitions.

## 5. Revocation freshness and cache

The required deployment setting is positive integer `max_evidence_age_seconds`. There is no universal numeric default. Production startup MUST fail if unset; no bounded-staleness production claim may be made without it. At commit, every consumed evidence item must satisfy `0 <= commit_time - observed_at <= max_evidence_age_seconds` and `commit_time < expires_at`. Permit cache TTL is capped by the earliest evidence expiry and configured bound. Use monotonic evidence generations; reordered/duplicate invalidations cannot roll back a newer generation. Lost/uncertain invalidation requires bounded revalidation. Source outage before commit fails closed. Test delayed/lost/reordered invalidations, expiry, source outage, concurrent revocation and policy updates. Caller-supplied signing timestamps never extend key trust.

## 6. Stable enforcement reasons

`AUTHN_REQUIRED`, `ACTION_UNMAPPED`, `RESOURCE_COORDINATES_INVALID`, `POLICY_DENIED`, `PDP_INDETERMINATE`, `OBLIGATION_UNFULFILLED`, `TRUST_UNAVAILABLE`, `KEY_NOT_TRUSTED`, `KEY_REVOKED`, `RELEASE_NOT_ADMISSIBLE`, `EVIDENCE_STALE`, `AUDIT_DURABILITY_FAILURE`, `AUTHORIZATION_REVISION_CHANGED`.

Transport adapters may map to HTTP status but preserve machine-readable reasons. Do not expose sensitive policy/trust internals to unauthenticated callers.

## 7. Conformance and invariants

Every vector in `tests/conformance/psi-53-enforcement-v1.json` MUST be consumed and validated against the adjacent schema. PSI-52 policy vectors remain independently mandatory; PSI-53 vectors test enforcement composition, not a replacement policy language.

No protected operation without authenticated principal and exact server-derived resource/action. No allow on missing/stale/unavailable evidence. No conflation of signature validity, trust, authorization or lifecycle. No action outside PSI-52 vocabulary. No mutation without durable audit. No permit cached beyond earliest evidence expiry/configured bound. No stale authorization across commit.

Implementation acceptance additionally requires exhaustive route coverage, alternate-path bypass tests, PostgreSQL atomicity, property-based tests and Python 3.11–3.13 CI.
