# Registry persistence model — PSI-38

- **Status:** Approved design and implementation baseline; ADR-004 Accepted on 2026-11-16.
- **Date:** 2026-11-16
- **Controlling identity decision:** [ADR-003 — Publisher namespace and issuer/trust model](adr/ADR-003-publisher-namespace-and-issuer-trust-model.md)
- **Related decision:** [ADR-004 — Registry persistence backend and relational data model](adr/ADR-004-registry-persistence-backend-and-data-model.md)
- **Linear:** [PSI-38](https://linear.app/getpsi/issue/PSI-38/design-registry-persistence-model)
- **Repository:** `enterprise-factory-network`

## 1. Purpose and boundary

This document defines the logical and physical persistence baseline for the Enterprise Factory Network registry. It is a registry implementation model, not an extension or replacement of EFS.

The registry stores publisher namespaces, publisher-scoped Factories, exact immutable releases, digest metadata and references to immutable manifest artifacts. It also maintains operational metadata needed to find those records and their artifact bytes.

**ADR-003 is binding.** Every table, key, repository method, API projection, migration and test MUST preserve its identity semantics:

- `publisher.id` is the exact absolute canonical URI under `efs-uri-c14n-1`.
- The URI is opaque. Persistence and lookup never dereference it, resolve DNS, follow redirects or perform network access.
- Factory identity is exactly `(publisher.id, factory.id)`. Factory ID comparison is exact and case-sensitive over the decoded Unicode scalar sequence.
- Publisher and Factory identities are immutable and never reassigned. Retired identifiers remain permanent tombstones.
- Registry-local UUIDs, storage keys, endpoints, display names and release versions are not portable identities.
- Identity syntax and uniqueness do not establish ownership, authentication, trust, certification or authorization.

No Factory Studio, Factory Connect, Factory Runtime or Enterprise Factory Network product-local publisher identity scheme is permitted. All four products consume this shared EFS profile.

## 2. Backend and implementation boundary

Approved initial operational stack (see ADR-004):

- PostgreSQL relational database.
- SQLAlchemy 2.x persistence mapping and repository implementations.
- Alembic ordered migrations.
- Python domain types and repository interfaces that do not expose PostgreSQL-specific types to API/domain callers.
- Artifact bytes stored outside PostgreSQL behind a content-addressed artifact-storage interface; the database stores digest identity and location references only.

PostgreSQL is the first supported registry adapter, not an EFS requirement. The logical model is portable. A second backend is not required in PSI-38; it must pass the same repository contract and conformance tests before being supported.

The current repository is Python 3.11–3.13, pytest and Ruff. No existing database backend or migration history exists to preserve. The initial migration therefore creates the schema from an empty database.

## 3. Logical entities

### 3.1 Publisher namespace

One row represents one claimed publisher namespace in this registry.

| Field | Type / rule | Mutability |
| --- | --- | --- |
| `publisher_record_id` | UUID primary key, generated locally | Immutable |
| `publisher_uri` | ASCII canonical URI string, unique under exact bytewise comparison | Immutable |
| `lifecycle_state` | `active` or `retired` | State transition only |
| `created_at` | UTC timestamp with timezone | Immutable |
| `retired_at` | Nullable UTC timestamp | Set once on retirement |

The database UUID is internal and MUST NOT be serialized in an EFS manifest or used as the federation publisher identity. The unique URI column uses deterministic bytewise/case-sensitive collation (`C` in PostgreSQL). Application admission must run the exact ADR-003 `efs-uri-c14n-1` validator before insertion; a database uniqueness constraint is not a substitute for canonical URI validation.

A publisher URI is never updated. Retirement changes lifecycle state but retains the row forever. No delete, reassignment, alias or transfer operation exists in v1.

### 3.2 Publisher descriptive metadata

Mutable descriptive fields are separate from the immutable publisher identity row. The initial projection may contain a nullable display name and update timestamp. It is derived from authoritative manifest data or later verified registry metadata; it is never used for identity or trust. The exact provenance and conflict policy for multi-release display-name projection belongs to the registry API/Passport work and must not alter the publisher URI.

Do not store signing private keys, credentials or trust claims in this table.

### 3.3 Factory

One row represents one stable Factory identity scoped to a publisher.

| Field | Type / rule | Mutability |
| --- | --- | --- |
| `factory_record_id` | UUID primary key, generated locally | Immutable |
| `publisher_record_id` | FK to publisher namespace | Immutable |
| `factory_id` | Exact decoded EFS string, case-sensitive, bytewise comparison | Immutable |
| `lifecycle_state` | `active` or `retired` | State transition only |
| `created_at` | UTC timestamp with timezone | Immutable |
| `retired_at` | Nullable UTC timestamp | Set once on retirement |

Required constraint: `UNIQUE(publisher_record_id, factory_id)`. The database MUST NOT impose global uniqueness on `factory_id`: two publishers may independently use the same Factory ID. The composite pair is the logical identity; the UUID is only a join key.

The database must not case-fold or Unicode-normalize `factory_id`. Configure deterministic bytewise comparison for identity columns. Application validation must use the decoded JSON string value, not its escape spelling.

Factory rows are retained permanently. Retirement never releases the ID for reuse.

### 3.4 Artifact blob

One row represents immutable content identified by the complete digest tuple.

| Field | Type / rule |
| --- | --- |
| `artifact_blob_id` | Internal UUID primary key |
| `digest_profile` | Required profile identifier |
| `digest_algorithm` | Required algorithm identifier |
| `digest_value` | Exact encoded digest string |
| `byte_length` | Non-negative stored byte length |
| `created_at` | UTC timestamp |

Required constraints: `UNIQUE(digest_profile, digest_algorithm, digest_value)` and a composite candidate key `UNIQUE(artifact_blob_id, digest_profile, digest_algorithm, digest_value)` so the release row can enforce that its digest tuple matches the referenced blob. Digest tuple equality is exact. For EFS factory releases, PSI-34's approved `efs-jcs-sha256-v1` profile and SHA-256 algorithm are expected; the storage abstraction may represent other governed artifact profiles without silently substituting them. Unsupported profiles are rejected by the relevant profile/registry layer.

A digest is content integrity, not publisher identity, signature verification, trust or authorization.

### 3.5 Artifact location

An artifact blob may have one or more physical storage locations. A location row contains an internal location ID, blob FK, storage-provider identifier, opaque object key, location state and timestamps. Enforce uniqueness of a provider/object-key pair and prevent one object key from being associated with conflicting blobs.

Locations are replaceable/replicable operational metadata. They are not publisher IDs, Factory IDs, release IDs or EFS URIs. Changing a storage provider or object key MUST NOT change a release digest or Factory identity. The object key is never dereferenced as a publisher identity.

### 3.6 Factory release

One row represents one published immutable release of one Factory.

| Field | Type / rule | Mutability |
| --- | --- | --- |
| `release_record_id` | Internal UUID primary key | Immutable |
| `factory_record_id` | FK to Factory | Immutable |
| `version` | Exact EFS release version string; no semantic-version interpretation | Immutable |
| `digest_profile` | Exact digest profile | Immutable |
| `digest_algorithm` | Exact digest algorithm | Immutable |
| `digest_value` | Exact digest value | Immutable |
| `artifact_blob_id` | FK to matching artifact blob/digest tuple | Immutable |
| `published_at` | UTC timestamp | Immutable |
| `created_at` | UTC timestamp | Immutable |

Required constraints:

- `UNIQUE(factory_record_id, version)`.
- A composite foreign key ties `artifact_blob_id` to the exact digest profile/algorithm/value tuple in `artifact_blobs`.
- The referenced Factory and artifact blob must exist.
- Foreign keys use RESTRICT semantics; no cascade deletion of published history.

Version is opaque at this layer. The registry does not infer ordering, compatibility, “latest” or SemVer precedence. Those semantics are deferred to M4. A release row cannot be updated to point to different content. A new content value for an existing Factory/version is a conflict, not an overwrite.

## 4. Relationship model

```text
publishers
  1 ─────── N factories
                  1 ─────── N factory_releases
                                  N ─────── 1 artifact_blobs
                                                   1 ─────── N artifact_locations

publishers
  1 ─────── 0..1 publisher_metadata
```

Portable identity and local keys:

| Concept | Portable identity | Local persistence key |
| --- | --- | --- |
| Publisher | Canonical `publisher.id` URI | `publisher_record_id` UUID |
| Factory | `(publisher.id, factory.id)` | `factory_record_id` UUID |
| Release | Factory identity + exact release version + digest | `release_record_id` UUID |
| Artifact content | Digest profile + algorithm + value | `artifact_blob_id` UUID |
| Artifact location | None; operational locator only | `artifact_location_id` UUID |

The local UUID is never a canonical identifier and never replaces the portable key in manifests, passports, federation messages or product interfaces.

## 5. Database constraints and immutability

The PostgreSQL implementation must include:

1. Exact unique constraint on `publishers.publisher_uri`.
2. Exact unique constraint on `(factories.publisher_record_id, factories.factory_id)`.
3. Exact unique constraint on `(factory_releases.factory_record_id, factory_releases.version)`.
4. Unique artifact digest tuple.
5. Foreign keys with RESTRICT semantics and required composite FK tying release digest metadata to its artifact blob.
6. CHECK constraints for allowed lifecycle values, non-negative byte length and consistent retired-state/timestamp combinations.
7. Database trigger or equivalent database-enforced protection against changing/deleting publisher URI, Factory identity pair, and published release records.
8. Application/database role separation so normal registry writes cannot bypass immutable-field protections.

Retirement is the only supported lifecycle mutation on publisher/Factory identity rows. The transition is one-way from active to retired. A retired row remains queryable for historical release resolution and federation conflict detection. A retired publisher cannot register new Factories or releases; a retired Factory cannot register new releases. Retirement does not cascade-delete or rewrite historical records.

The database enforces exact uniqueness and referential integrity. The application validator enforces the full ADR-003 URI syntax/canonicalization profile; do not duplicate an incomplete URI parser in SQL.

## 6. Transaction boundaries and publication sequence

The artifact bytes and relational database cannot share a single ACID transaction. Use content-addressed writes and a strict publication order:

1. Parse the manifest with duplicate JSON-member rejection.
2. Validate against the EFS v1 schema and semantic conformance profile.
3. Recompute and verify the release digest using the approved PSI-34 profile (PSI-40).
4. Write the exact immutable bytes to the artifact store under the content digest; verify the stored object.
5. Begin one relational database transaction.
6. Resolve or create the publisher row by exact canonical URI; resolve or create the Factory by exact scoped ID.
7. Insert or verify the artifact blob and location metadata.
8. Insert the immutable Factory release row referencing the exact artifact/digest tuple.
9. Commit once. Any database conflict or failure rolls back all relational changes.

Database unique constraints arbitrate concurrent writers. A preflight SELECT is not a concurrency guarantee. Translate unique/FK violations into stable domain conflict/error results at the repository/service boundary.

If the artifact write succeeds but the database transaction fails, the result may be an unreferenced content-addressed object. This is safe with respect to published history and can be reconciled by an orphan-object inventory/garbage-collection process after a conservative retention interval. The reverse condition—a committed release pointing to nonexistent artifact metadata—is prohibited. PSI-40 owns artifact existence, verification and orphan reconciliation details.

No release is published until the artifact is present and verified. Publisher/factory creation and release registration in the database are atomic within the same transaction.

## 7. Repository/data-access boundary

Domain-facing interfaces should be explicit and independent of SQLAlchemy session/query objects:

- `PublisherRepository`: get by canonical URI; create claim; retire; fetch by local internal ID for joins.
- `FactoryRepository`: get by exact publisher URI + Factory ID; create; retire; list by publisher.
- `ArtifactRepository`: get/create blob by exact digest tuple; attach/list locations.
- `ReleaseRepository`: get exact release by publisher URI + Factory ID + version; create immutable release; list releases with deterministic cursor/order contract (API details in PSI-39).
- `RegistryUnitOfWork`: transaction boundary coordinating repository operations and commit/rollback.

Repositories accept domain values, not raw HTTP payloads. They return typed domain records/results, not ORM entities. SQLAlchemy mappings remain in the infrastructure adapter. The domain layer must not import PostgreSQL driver types or depend on PostgreSQL-specific collation objects.

Expected conflict classes include publisher URI already claimed, Factory identity already exists, Factory/version already published with same digest, Factory/version already published with a different digest, retired identity, missing parent, and artifact reference mismatch. Exact HTTP status and idempotency behavior belongs to PSI-39.

## 8. Migration strategy

- Use Alembic revision identifiers and ordered migration dependencies.
- First revision creates all core tables, indexes, constraints, triggers and required database extensions (avoid extensions unless justified).
- Clean initialization from an empty PostgreSQL database is mandatory and repeatable.
- Upgrade tests run from the immediately previous supported revision. Since this is the first persistence schema, no earlier supported database revision currently exists; do not claim a legacy upgrade test.
- Migrations are forward-first. Never rewrite published publisher/factory/release identity values.
- Destructive down-migrations that drop or rewrite published records are prohibited. Recovery uses forward corrective migrations or an operator-approved backup restore.
- Test migration application, schema state, uniqueness, foreign keys, immutability triggers and transaction rollback against the actual supported PostgreSQL version.

## 9. Concurrency, isolation and failure behavior

- Rely on database unique constraints for identity/version race arbitration.
- Use transactions for multi-row publisher/factory/release registration.
- Choose the weakest isolation level that preserves invariants through unique constraints and explicit locking where necessary; PostgreSQL READ COMMITTED is the initial default candidate. Document any operation requiring stronger isolation or row locks.
- Do not use “check then insert” without handling the unique-conflict race.
- Retry only bounded transient transaction failures (e.g., serialization/deadlock) and never reinterpret a uniqueness conflict as success without checking the exact stored digest.
- Ensure failed transactions leave no partial publisher/factory/release rows.
- Use deterministic exact-release ordering and stable cursor semantics in PSI-39; do not add implicit latest-version selection here.

## 10. Test and acceptance matrix

| ID | Scenario | Expected result |
| --- | --- | --- |
| DB-01 | Initialize empty PostgreSQL database | All migrations apply; schema ready |
| DB-02 | Insert canonical URN publisher ID | One publisher row; URI preserved exactly |
| DB-03 | Insert same canonical URI twice | Unique conflict; no duplicate publisher |
| DB-04 | Insert same Factory ID under two publishers | Two distinct Factory rows |
| DB-05 | Insert same Factory ID under same publisher twice | Unique conflict |
| DB-06 | Change publisher URI after registration | Database rejects mutation |
| DB-07 | Change Factory ID or publisher FK after registration | Database rejects identity mutation |
| DB-08 | Retire publisher/Factory | Tombstone retained; identifier cannot be reused |
| DB-09 | Insert same release version twice for one Factory | Unique conflict |
| DB-10 | Same release version under different Factories | Allowed |
| DB-11 | Release references absent artifact blob | FK rejects insert |
| DB-12 | Release digest tuple differs from referenced blob | Composite FK rejects insert |
| DB-13 | Update/delete published release | Database rejects mutation/deletion |
| DB-14 | Concurrent create same publisher URI | Exactly one succeeds; other gets deterministic conflict |
| DB-15 | Concurrent create same Factory identity | Exactly one succeeds |
| DB-16 | Concurrent create same Factory/version with differing digests | Exactly one immutable release wins; other gets conflict |
| DB-17 | Fail transaction after publisher/factory insert before release commit | All relational changes roll back |
| DB-18 | Artifact write succeeds but DB transaction fails | No release row; orphan object is reconcilable |
| DB-19 | Move/add artifact location | Release digest and portable identity unchanged |
| DB-20 | Clean migration and migration from previous supported revision | Both pass; no data loss |
| DB-21 | Noncanonical publisher URI bypasses API and is inserted | Repository admission rejects; DB uniqueness alone is not claimed as URI conformance |
| DB-22 | URI with query/fragment/userinfo or network dereference attempt | Rejected locally; no network call |

CI must run repository contract tests and PostgreSQL integration tests on Python 3.11, 3.12 and 3.13. SQLite-only success is not sufficient evidence for PostgreSQL concurrency, collation, trigger or migration acceptance.

## 11. Explicit non-goals

- Publisher proof-of-control, authentication, signing keys, signatures, trust roots and revocation (PSI-50/51 and M5).
- Policy evaluation or authorization.
- Factory lifecycle/revocation protocol beyond local active/retired tombstones.
- Semantic-version parsing, compatibility and latest resolution (M4).
- Capability contract validation (M3).
- Dependency resolution.
- Marketplace search, licensing, procurement and complete four-product integration (M6).
- Runtime deployment or execution.
- Artifact digest implementation and object-store adapter details (PSI-40), beyond the persistence contract.
- HTTP API and idempotency contract details (PSI-39).

## 12. PSI-38 completion gate

PSI-38 is complete only when the backend decision is accepted, the schema and repository boundary are implemented, versioned migrations initialize a clean PostgreSQL database, constraints/triggers enforce identity and release invariants, and the complete test matrix is represented in automated tests/CI. This document alone is the design baseline, not evidence that those implementation criteria have passed.
