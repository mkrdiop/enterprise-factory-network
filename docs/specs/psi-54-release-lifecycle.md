# PSI-54 — Registered Factory Release lifecycle

- **Status:** Normative specification proposal; pending owner and independent review
- **Version:** 1.0.0
- **Date:** 2026-11-16
- **Dependencies:** PSI-37, PSI-40, PSI-51, PSI-52, PSI-53
- **Conformance:** `schemas/psi-54-lifecycle-v1.schema.json`; `tests/conformance/psi-54-lifecycle-v1.json`

## 1. Settled candidate-versus-release decision

The Network's registered `FactoryRelease` lifecycle contains exactly five states: `published`, `suspended`, `deprecated`, `revoked`, `archived`.

The proposed `draft` and `validated` states are **not** states of a registered FactoryRelease. They belong to the authoring/candidate workflow before publication. Network creates a FactoryRelease only after manifest/schema/semantic validation, immutable PSI-40 digest verification and storage, PSI-51 signature verification, PSI-53 authorization and successful publication finalization. The row is created directly in `published` with its initial event in one atomic commit.

This aligns with PSI-39/40: there is no persisted release candidate today, and a release row is created only after artifact persistence/finalization. It preserves immutable artifact semantics and avoids mutable candidate state masquerading as a registered immutable release. If server-side candidates are later needed, define a separate `ReleaseCandidate` aggregate and promotion protocol; do not add candidate states to FactoryRelease.

## 2. Identity and separation

Lifecycle attaches to one exact persisted coordinate: canonical publisher URI, exact Factory ID, opaque release version and immutable digest, internally keyed by `release_record_id`. Never attach it to “latest”, a mutable Factory pointer, signature envelope, key or execution.

Lifecycle metadata MUST NOT change canonical manifest bytes, digest, publisher ID, Factory ID or release version. PSI-45 execution state, PSI-51 signature validity, PSI-53 publisher/key trust, PSI-52 authorization, PSI-49 compatibility and PSI-37 publisher namespace retirement remain separate facts.

## 3. State semantics

| State | Discovery | Exact retrieval | New invocation |
|---|---|---|---|
| published | ordinary discovery subject to authorization | allowed subject to authorization | eligible subject to policy, trust and compatibility |
| suspended | hidden from ordinary discovery | authorized administrative/audit reads only | denied |
| deprecated | discoverable with explicit deprecation metadata | allowed subject to authorization | eligible subject to policy, trust and compatibility |
| revoked | hidden from ordinary discovery | authorized security/audit reads only | denied |
| archived | hidden from ordinary discovery | retention/audit access only | denied |

Lifecycle is admission, not authorization. Published/deprecated never grant access by themselves. Artifact bytes in object storage do not imply publication or invocation eligibility. Existing executions are not automatically canceled; PSI-45 governs execution state unless a separate cancellation contract is approved.

## 4. Legal transition matrix

| From | To | Preconditions |
|---|---|---|
| published | suspended | explicit reason; PSI-53 `release.suspend` permits |
| published | deprecated | explicit reason; PSI-53 `release.deprecate` permits |
| published | revoked | explicit reason + evidence reference; PSI-53 `release.revoke` permits |
| suspended | published | fresh re-admission + PSI-53 authorization; never if revoked |
| suspended | deprecated | explicit reason; PSI-53 authorization |
| suspended | revoked | explicit reason + evidence; PSI-53 authorization |
| deprecated | revoked | explicit reason + evidence; PSI-53 authorization |
| deprecated | archived | retention preconditions + PSI-53 `release.archive` authorization |
| revoked | archived | retention preconditions + PSI-53 `release.archive` authorization |

All unlisted transitions, self-transitions, transitions from archived and transitions to draft/validated are rejected. Revoked is terminal except archival; archived is terminal. Replacement requires a new exact release coordinate.

## 5. Transition transaction and event

Request fields: exact release coordinate, expected lifecycle revision, target state, explicit non-empty reason, stable reason code, idempotency key and correlation ID. Revocation also requires an evidence reference. Actor identity comes from the PSI-53 authenticated principal, never the request body.

Service steps: resolve exact release; validate revision and transition matrix; evaluate the matching PSI-52 action through PSI-53 PEP; check transition-specific preconditions (fresh re-admission for suspended→published; retention eligibility for archive); at commit recheck evidence freshness and expected revision; append immutable event and update current-state projection in one DB transaction including PSI-53 audit outbox.

Event fields: event ID, release record ID and exact coordinate snapshot, from/to, revision, actor, action, reason/reason code, evidence reference, authorization decision reference, policy digest/version, trust/lifecycle evidence versions, correlation ID, idempotency key, request fingerprint and UTC committed timestamp. History is append-only; corrections are compensating events, never edits/deletes.

Concurrent requests with same expected revision: at most one succeeds; others get deterministic stale-revision conflict. Same idempotency key + identical request fingerprint returns original result. Same key + different fingerprint conflicts. Never authorize from stale preflight permit.

## 6. Publication and initial state

Publication requires PSI-37 identity admission; PSI-40 immutable digest verification/artifact persistence; PSI-51 signature verification (required signer identities come from policy, not envelope quorum semantics); PSI-53 authorization for applicable `factory.register`, `factory.publish`, `release.publish` checks and obligation enforcement; final freshness check; atomic FactoryRelease insertion in `published` with revision-1 initial lifecycle event and audit outbox. Object-store I/O is outside DB transaction. Failed final commit cannot expose a partial release.

## 7. Lifecycle admission

Transport-neutral result: `eligible` for published/deprecated (authorization, trust and compatibility still required); `denied` for suspended/revoked/archived; `indeterminate` if release/lifecycle evidence unavailable, malformed or stale. Registry discovery, retrieval and Runtime invocation use this shared contract. Runtime must not implement product-local states or infer published from artifact presence. PSI-54 never rewrites PSI-45 execution state.

## 8. Conformance

Every vector in `tests/conformance/psi-54-lifecycle-v1.json` MUST be consumed and validated against its schema. Test all legal/illegal transitions, exact-coordinate isolation, immutable digest preservation, authorization deny/indeterminate/obligation failure, stale revisions, idempotency, concurrency, outbox atomicity and Registry/Runtime parity.

Invariants: no FactoryRelease in draft/validated; every registered release starts published with atomic event; coordinate and digest never change; revoked/archived never restored; every transition uses PSI-53; durable audit for every mutation; no implicit PSI-45 execution transition; consumers follow state semantics above.
