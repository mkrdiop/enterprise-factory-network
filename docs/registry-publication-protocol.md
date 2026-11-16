# Registry publication protocol — shared PSI-39 / PSI-40 contract

- **Status:** Implementation baseline for PSI-39 and PSI-40
- **Date:** 2026-11-16
- **Controlling decisions:** ADR-003 (publisher identity), ADR-004 (PostgreSQL persistence)
- **Related work:** PSI-39 manifest registry API; PSI-40 immutable release storage
- **Scope:** The internal contract between registry publication orchestration, relational persistence and content-addressed artifact storage.

## 1. Purpose and invariants

PSI-39 and PSI-40 are parallel implementation workstreams, not independent publication pipelines. They MUST implement this one contract.

1. The canonical publisher identifier is the exact absolute URI accepted by ADR-003 / `efs-uri-c14n-1`. It is never dereferenced. Factory identity remains the exact pair `(publisher.id, factory.id)`; local UUIDs are database join keys only.
2. A release version is an opaque exact string. This layer does not parse SemVer, select “latest”, or infer compatibility.
3. A published release binds one exact Factory identity and version to one verified `efs-jcs-sha256-v1` digest identity.
4. The database is authoritative for publication state and release discoverability. An object existing in storage is not, by itself, a published release.
5. Artifact storage is authoritative for artifact bytes, not publisher/factory/release identity, trust, signatures or authorization.
6. There MUST NOT be a committed release row whose referenced artifact is absent or unverified.
7. A failure may leave an unreferenced content-addressed object or a pending publication operation. It MUST NOT leave a visible half-published release.
8. Retry and recovery MUST be idempotent. Published bytes and release identity/version/digest associations are immutable.

## 2. The digest-addressed payload is the canonical projection

The approved digest profile hashes the domain-separated JCS envelope:

`{"domain":"efs.factory-release.v1","manifest":<manifest projection>}`

The manifest projection excludes exactly `release.digest` and `release.signature`, as defined by PSI-34. The digest is SHA-256 over the RFC 8785 JCS serialization of that envelope, encoded as unpadded Base64URL.

**Storage MUST persist the exact canonical JCS envelope bytes used as the digest preimage**, not arbitrary submitted JSON bytes and not a reconstructed full manifest containing excluded signature material. This makes the digest-addressed object unambiguous: the stored bytes themselves hash to the object key.

Consequences:

- Whitespace, key ordering and equivalent JSON serialization do not create distinct artifacts.
- The supplied `release.digest` is verified against the recomputed digest; it is not trusted as an input to the digest.
- `release.signature` is excluded from the content object. Signature material, signing identity, trust and revocation are separate concerns (PSI-50/51 and M5); PSI-39 MUST NOT claim signature verification.
- Retrieval parses the stored envelope, verifies its bytes against the expected digest, extracts the manifest projection, and reconstructs the response manifest by adding the verified `release.digest`. It MUST NOT invent or synthesize a signature.
- The canonicalizer rejects duplicate JSON object names and inputs outside the approved JCS/I-JSON profile before storage.

## 3. Ownership and dependency direction

| Concern | Owner | Contract |
| --- | --- | --- |
| HTTP routes, request/response schemas, pagination, error mapping | PSI-39 | Public versioned API |
| EFS schema and semantic validation before publication | PSI-39 | Existing validator, no duplicate validator |
| Publisher/Factory lookup and lifecycle admission | PSI-39 + existing repositories | ADR-003 exact identity |
| Publication orchestration and durable operation state | PSI-39 | SQLAlchemy unit-of-work / repository boundary |
| Digest profile implementation and test vectors | PSI-40 | One implementation of `efs-jcs-sha256-v1` |
| Content-addressed put/read/verify adapter | PSI-40 | `ArtifactStore` protocol below |
| Artifact blob/location/release persistence | Shared DB contract; repositories | Existing PSI-38 relational model |
| Signature trust, policy authorization, semantic compatibility | Out of scope | PSI-50/51, M5, M4 |

Dependency direction is one-way: PSI-39 depends on the PSI-40 digest and storage interfaces; PSI-40 MUST NOT import HTTP/API code or define a second publisher/factory identity model. Both depend on the PSI-38 persistence/domain boundary. Storage keys are derived only from the digest tuple.

## 4. Shared internal interfaces

The implementation SHOULD expose framework-neutral Python types/protocols under `registry/` (exact module layout may follow repository conventions). These are internal interfaces, not additions to EFS.

### 4.1 Digest identity and canonical payload

A digest identity is the immutable tuple:

- `profile = "efs-jcs-sha256-v1"`
- `algorithm = "SHA-256"`
- `value = <43-character unpadded Base64URL>`

The PSI-40 digest service accepts strictly parsed manifest data and returns:

- the validated digest identity;
- the exact canonical envelope bytes used as the digest preimage;
- the parsed manifest projection needed for response reconstruction.

The digest service MUST verify a supplied manifest digest, and MUST reject unsupported profiles, malformed Base64URL, duplicate member names, invalid UTF-8, non-I-JSON values, non-finite numbers and any mismatch. It MUST NOT silently choose another profile or rewrite publisher/factory identity.

### 4.2 ArtifactStore protocol

The storage boundary is digest-only and publisher-agnostic. It SHOULD provide the equivalent of:

- `put_if_absent(digest, canonical_payload, expected_length) -> StoredArtifact`
- `read(digest) -> byte stream`
- `describe(digest) -> StoredArtifact | None` (verified receipt for recovery; `None` only when the object is absent)
- `delete_if_match(stored_artifact_generation) -> bool` (maintenance/GC only; never part of normal publication)

`StoredArtifact` contains the digest identity, byte length, provider identifier, opaque object key and provider generation/version token where available. The registry persists that generation on the artifact-location row so future conditional garbage collection can use the exact object generation.

Required semantics:

1. Object key is deterministic from the complete digest tuple; it contains no publisher URI, Factory ID, version, display name or user-controlled path component.
2. `put_if_absent` is atomic create-if-absent. It MUST never overwrite an existing object.
3. If the key already exists, the adapter reads and verifies the existing bytes against the digest and expected length. Equal valid content is an idempotent success; corrupt or conflicting content is an integrity failure and MUST be quarantined/reported, never overwritten.
4. Successful writes are durable according to the provider's documented durability contract before returning.
5. Reads return bytes that the caller can independently verify. Provider metadata/ETags alone are not proof of integrity.
6. The adapter does not perform network retrieval from manifest-provided URIs and does not interpret publisher identity.
7. Normal API callers cannot delete or mutate stored objects. Deletion is a separately authorized maintenance operation protected by generation preconditions and database reference checks.

The initial implementation may use a local filesystem adapter for deterministic tests and development, but the interface MUST permit object-store implementations without changing PSI-39 or EFS semantics.

### 4.3 Durable publication operation repository

Because PostgreSQL and external artifact storage cannot share an ACID transaction, PSI-39 MUST persist a publication operation before writing the object. Add a versioned Alembic migration for a durable operation/idempotency record. The record contains at minimum:

- operation ID (local UUID);
- opaque idempotency key and stable request fingerprint;
- exact publisher URI, Factory ID and release version;
- expected digest profile/algorithm/value and canonical payload byte length;
- operation state and created/updated timestamps;
- bounded, non-secret failure code/detail for operational diagnosis.

The operation record is not an EFS identity and is not exposed as an authorization credential. It MUST NOT contain private keys, secrets or unrestricted raw request headers.

The operation repository provides transactional operations equivalent to:

- `prepare_or_get(request) -> PublicationOperation`
- `get(operation_id)`
- `list_recoverable(limit)`
- `finalize_release(operation_id, stored_artifact) -> PublishedRelease`
- `record_retryable_failure(operation_id, code)`
- `record_terminal_conflict(operation_id, code)`

`finalize_release` MUST use one PostgreSQL transaction to insert/verify the artifact blob and location, insert the immutable release row, and mark the operation committed. The operation and release commit together. It MUST use the existing unique constraints as concurrency arbiters, not a preflight SELECT alone.

The operation record reserves the digest against garbage collection while pending. A conservative orphan collector MUST never delete content referenced by a committed release or by a non-terminal publication operation.

### 4.4 Publication service boundary

PSI-39 owns an orchestration service with the logical contract:

`publish(manifest_bytes, idempotency_key) -> PublicationResult`

The service validates and canonicalizes before reservation, then coordinates the operation repository and PSI-40 digest/storage services. The HTTP layer is a thin adapter and MUST NOT write artifact objects or release rows directly.

A `PublicationResult` distinguishes at least:
- `committed`: release is durably retrievable;
- `pending`: durable operation exists but publication is not yet committed;
- `conflict`: identity/version or idempotency key is bound to different content;
- `rejected`: schema, semantic, parser or digest validation failed.

Do not return success/201 or expose a release as retrievable until the final relational transaction commits. A pending result is explicit and retryable (202 or equivalent documented response).

## 5. Publication protocol and transaction boundaries

### Phase A — pure validation (no database or storage writes)

1. Strictly decode UTF-8 and parse JSON while rejecting duplicate member names and non-JSON constants.
2. Validate the manifest against the EFS v1 Draft 2020-12 schema with the repository's explicit format checking.
3. Run the existing semantic conformance validator, including ADR-003 canonical publisher URI checks.
4. Compute the canonical digest envelope using the PSI-40 implementation.
5. Compare the recomputed digest tuple with the supplied `release.digest`. Reject mismatch before reserving an operation.
6. Derive a stable request fingerprint from the exact portable release identity/version and digest tuple; do not include mutable transport headers or storage location.

### Phase B — reserve durable intent (PostgreSQL transaction A)

1. Resolve/create the publisher and Factory using exact ADR-003 identity semantics. Reject retired publisher/Factory parents.
2. Create or retrieve the operation by idempotency key and request fingerprint.
3. If the same key is already associated with a different fingerprint, return a deterministic idempotency conflict.
4. If the exact Factory/version is already committed with the same digest, return the existing release as an idempotent success. If the version is bound to a different digest, return a release-version conflict.
5. Commit the pending operation. This transaction is short and performs no external storage I/O.

The database's unique constraints arbitrate races. Concurrent operations with different idempotency keys may both reach storage; only one digest can win the immutable Factory/version association. The loser returns a deterministic conflict and its unreferenced object remains safe for later GC.

### Phase C — immutable artifact write (outside any DB transaction)

1. Call `put_if_absent` with the digest identity and canonical envelope bytes.
2. Verify the returned object by reading it back (or by an equivalent provider guarantee plus independent byte verification); recompute the digest from returned bytes.
3. A storage timeout is an unknown outcome, not permission to overwrite. Retry the same digest/key using create-if-absent semantics and verify any existing object.
4. On transient storage failure, leave the operation pending and record a retryable diagnostic. Do not create a release row.

### Phase D — atomic publication commit (PostgreSQL transaction B)

1. Re-check the operation is pending and its fingerprint/digest match.
2. Re-check publisher and Factory are still active. Retirement racing with publication must be resolved under the database's existing row-lock/trigger invariants; a retired parent cannot gain a new release.
3. Insert or verify the artifact blob and location metadata.
4. Insert the immutable Factory release row, bound by the composite digest FK.
5. Mark the publication operation committed and attach the release record.
6. Commit all these relational changes atomically.

Only after this commit may the API return a published release or allow exact-version retrieval. A unique-key race on Factory/version resolves to either the already-committed same digest (idempotent success) or a different-digest conflict. Roll back all transaction-B relational writes on failure.

## 6. Failure recovery matrix

| Failure point | Durable state | Required behavior |
| --- | --- | --- |
| Parse/schema/semantic/digest validation fails | No operation, no object | Reject; no side effects |
| Transaction A fails | No committed operation | Return retryable DB error; no storage write |
| Process crashes after A, before object write | Pending operation, object absent | Client retry or recovery worker resumes; no release visible |
| Object write fails before creation | Pending operation, object absent | Retry same idempotent put; no release visible |
| Object write succeeds but response times out | Pending operation, object may exist | Retry put-if-absent, read and verify; never overwrite |
| Process crashes after object write, before B | Pending operation, verified object exists | Recovery worker reads/verifies by digest and attempts B |
| Transaction B fails/rolls back | Pending operation, object exists | Retry B after re-verification; no release visible |
| Two different digests race for same Factory/version | Both may have pending intents/objects; one release wins | Winner commits; loser records conflict; losing object becomes a GC candidate only after retention and reference checks |
| Existing digest key contains corrupt bytes | Pending operation; corrupt object quarantined/flagged | Integrity error; never overwrite or publish |
| DB commit succeeds but HTTP response is lost | Committed release and operation | Client retry with same key returns the same committed result |
| Storage read fails or bytes fail digest verification | Committed metadata may remain, but retrieval unavailable/corrupt | Return stable integrity/unavailable error; never return unverified bytes; raise operational alert |

A recovery worker is idempotent and bounded. It scans pending operations, reads by digest, verifies the canonical envelope and attempts transaction B. It does not infer missing bytes from metadata. If the object is absent, the operation remains pending for client resubmission or an explicit expiry/abandonment policy; PSI-39 MUST NOT silently mark it committed.

## 7. Idempotency, conflicts and visibility

- Same idempotency key + same request fingerprint: return the same operation/result; pending requests resume safely.
- Same idempotency key + different fingerprint: stable idempotency conflict.
- Same publisher/factory/version + same digest: idempotent existing-release result.
- Same publisher/factory/version + different digest: immutable version conflict; never overwrite.
- Same digest used by multiple releases: one stored content object may be shared; each release retains its own exact identity/version row.
- A pending operation is not a published release and MUST NOT appear in normal factory lookup, release listing or exact-version retrieval.
- Exact release retrieval is by canonical publisher URI + exact Factory ID + exact version. No implicit latest/compatible resolution.
- Pagination ordering and cursor semantics are explicit and deterministic; cursors are opaque to clients. Version ordering MUST NOT imply semantic-version precedence.

## 8. Garbage collection and retention

Orphan cleanup is not part of the publication critical path. A collector may consider an object only after a conservative grace period and a fresh relational reference check. It MUST exclude objects referenced by:
- any committed release;
- any non-terminal publication operation;
- any active replication/repair task, if such tasks are introduced.

Deletion MUST use the storage generation/version token as a conditional precondition. If the provider cannot guarantee conditional deletion, automatic deletion is disabled for that adapter. GC is idempotent, auditable and never changes release metadata. PSI-40 provides storage-level primitives; PSI-39 owns publication-operation references and the registry-side eligibility check.

## 9. Stable error taxonomy

The API maps internal failures to stable codes; it does not expose SQL, object keys, stack traces, secrets or provider credentials. At minimum:

- `EFS_MANIFEST_PARSE_INVALID`
- `EFS_MANIFEST_SCHEMA_INVALID`
- `EFS_MANIFEST_PROFILE_INVALID`
- `EFS_RELEASE_DIGEST_MISMATCH`
- `EFS_RELEASE_DIGEST_PROFILE_UNSUPPORTED`
- `EFS_IDEMPOTENCY_KEY_REUSED`
- `EFS_RELEASE_VERSION_CONFLICT`
- `EFS_PUBLICATION_PENDING`
- `EFS_ARTIFACT_INTEGRITY_FAILURE`
- `EFS_ARTIFACT_UNAVAILABLE`
- `EFS_REGISTRY_NOT_FOUND`
- `EFS_PUBLISHER_RETIRED`
- `EFS_FACTORY_RETIRED`

Validation errors may include the existing stable diagnostic codes and JSON Pointer paths. Internal exceptions are translated at the service/API boundary.

## 10. Acceptance and failure-injection tests

Both workstreams MUST contribute tests against this shared contract:

1. Canonical payload bytes hash to the declared digest on Python 3.11, 3.12 and 3.13.
2. Whitespace/key-order variants produce the same digest and stored object.
3. Different excluded signature values do not create a second digest-addressed payload; no signature is synthesized on retrieval.
4. Duplicate JSON members, invalid UTF-8, NaN/Infinity, invalid JCS values and supplied digest mismatch are rejected before any DB/storage side effect.
5. Put-if-absent repeated with identical bytes is idempotent; conflicting/corrupt existing bytes are never overwritten.
6. A pending operation is invisible to release lookup/listing.
7. Failure after transaction A leaves a recoverable pending operation and no release row.
8. Failure after object write but before transaction B is recovered without rewriting or changing bytes.
9. Failure during transaction B rolls back blob/location/release/operation finalization together.
10. Lost HTTP response after commit is resolved by same-key retry.
11. Concurrent same-version/same-digest registrations converge to one release and stable success results.
12. Concurrent same-version/different-digest registrations produce exactly one immutable winner and one deterministic conflict.
13. Orphan GC cannot delete an object referenced by a pending operation or committed release; conditional delete protects against object replacement races.
14. Retired publisher/Factory admission remains rejected under publication races.
15. Exact retrieval recomputes digest from stored bytes before returning reconstructed manifest content.
16. API tests prove no latest/compatibility inference and deterministic pagination.

## 11. Workstream deliverables

### PSI-39 — Manifest Registry API
- Versioned HTTP/JSON API contract and deterministic error envelope.
- Durable publication operation model/migration and repository operations.
- Publication orchestration service using the PSI-40 interfaces.
- Exact factory lookup, release listing, exact-version retrieval and keyset pagination.
- OpenAPI contract and API/DB/storage integration tests, including failure injection and idempotency.

### PSI-40 — Immutable Release Storage
- Normative `efs-jcs-sha256-v1` implementation and machine-readable test vectors.
- Canonical envelope payload type and digest verification.
- `ArtifactStore` protocol plus initial deterministic adapter.
- Put-if-absent, read verification, corruption handling and conditional deletion primitive.
- Cross-process/cross-version digest tests and storage tamper/failure tests.

### Explicit exclusions
No publisher authentication or trust proof, signatures/key discovery/revocation, policy evaluation/authorization, semantic-version compatibility/latest resolver, dependency resolution, capability contract validation, marketplace search or runtime admission. The four products continue to consume the one EFS publisher identity profile and shared registry contract.
