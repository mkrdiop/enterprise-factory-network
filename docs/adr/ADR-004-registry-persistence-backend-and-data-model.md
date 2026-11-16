# ADR-004 — Registry persistence backend and relational data model

- **Status:** Accepted
- **Date:** 2026-11-16
- **Decision owners:** Founder / Enterprise Factory architecture
- **Related Linear issues:** [PSI-38](https://linear.app/getpsi/issue/PSI-38/design-registry-persistence-model), [PSI-39](https://linear.app/getpsi/issue/PSI-39/implement-manifest-registry-api), [PSI-40](https://linear.app/getpsi/issue/PSI-40/implement-immutable-release-storage)
- **Related specifications:** [ADR-003 — Publisher namespace and issuer/trust model](ADR-003-publisher-namespace-and-issuer-trust-model.md), [Registry persistence model](../registry-persistence-model.md), [EFS v1 Canonical Factory Manifest Object Model](https://app.notion.com/p/41af741d651181ac9488d932f13051f0)
- **Supersedes / superseded by:** None

## Context

PSI-38 requires a persistence model for publisher identities, publisher-scoped Factories, exact immutable releases, digest metadata and immutable artifact references. The registry must support concurrent registration, durable uniqueness, tombstones, referential integrity and versioned migrations without turning database identifiers or storage locations into EFS identities.

ADR-003 is an accepted, binding input. In particular, the publisher identifier is an absolute URI already serialized under `efs-uri-c14n-1`; it is opaque, local-only and compared exactly. The Factory identity is the exact pair `(publisher.id, factory.id)`. Publisher and Factory identities cannot be reassigned; retired identities remain permanently tombstoned. A registry-local UUID is not a substitute for either portable identity.

The repository currently has a Python reference validator and test toolchain, but no established persistence backend, ORM or migration framework. PSI-38 must therefore choose an initial operational backend while keeping EFS semantics independent of that choice.

## Decision drivers

- Preserve ADR-003 identity and lifecycle invariants at the database boundary.
- Enforce uniqueness and referential integrity under concurrent writers.
- Keep immutable manifest bytes separate from mutable registry metadata.
- Permit artifact storage locations and database hosting to change without changing release identity.
- Keep repository interfaces and domain models independent of PostgreSQL-specific types.
- Support reproducible clean initialization, forward migrations, backup and recovery.
- Avoid premature publisher authentication, trust, authorization or semantic-version behavior.

## Options considered

### Option A — PostgreSQL with SQLAlchemy and Alembic (recommended)

Use PostgreSQL as the first supported operational relational backend, SQLAlchemy 2.x for the Python persistence boundary, and Alembic for versioned migrations. Use PostgreSQL deterministic `C` collation for opaque identifier equality and database constraints/triggers for uniqueness and immutable identity/release fields.

Benefits: mature transactional behavior, concurrency control, unique and composite foreign-key constraints, operational backup/replication tooling, and a well-supported Python ecosystem. Trade-offs: PostgreSQL-specific migration DDL and operational dependency. The domain/repository interfaces remain portable; PostgreSQL is the initial supported adapter, not part of EFS.

### Option B — SQLite as the operational backend

Benefits: minimal deployment, zero separate database service and convenient local development. Drawbacks: weaker fit for a multi-writer federated registry, different concurrency/locking behavior, and a less representative production test environment. SQLite remains suitable for isolated unit tests only where behavior is not relied on for PostgreSQL concurrency or trigger guarantees; it is not the production registry backend selected by this proposal.

### Option C — Defer backend selection or use a document database

Deferral leaves PSI-39/40 without a stable transaction and uniqueness contract. A document store could persist manifests naturally, but publisher/factory/release uniqueness, immutable lifecycle and transactional registration still require explicit modeling and carefully scoped transactions. Neither option offers a better initial fit than a relational registry.

## Proposed decision

1. Use PostgreSQL as the first supported operational database.
2. Use SQLAlchemy 2.x for domain-oriented repositories and Alembic for ordered, versioned migrations.
3. Store canonical publisher URIs and Factory IDs as exact text values under deterministic bytewise/case-sensitive equality (`COLLATE "C"` for PostgreSQL text columns participating in identity uniqueness).
4. Use registry-local UUID primary keys for relational joins only. Never expose them as replacements for `publisher.id` or `factory.id` in EFS manifests, passports or federation identity.
5. Keep publisher namespace, Factory, release, artifact digest and artifact location as distinct records.
6. Preserve publisher and Factory rows permanently; retirement is a state transition to a tombstone, never a DELETE or identifier reuse.
7. Treat a published release row and its identity/version/digest/artifact association as immutable. Mutable descriptive projections and artifact-location replicas are separate records.
8. Keep the database backend, SQL schema, local IDs and storage keys outside the EFS specification. A future adapter must pass the same repository contract and identity conformance tests.

This ADR is **Proposed**, not Accepted. It becomes binding only after explicit founder approval and merge of the ADR update.

## Relational model

The normative logical model and PostgreSQL mapping are specified in [docs/registry-persistence-model.md](../registry-persistence-model.md). The core relations are:

- `publishers`: local UUID, canonical opaque publisher URI, lifecycle state and timestamps. Unique on the exact URI.
- `publisher_metadata`: mutable descriptive projection, separate from the immutable publisher URI.
- `factories`: local UUID, publisher FK, exact opaque factory ID, lifecycle state and timestamps. Unique on (publisher FK, factory ID).
- `artifact_blobs`: content identity tuple (digest profile, algorithm, digest value), byte length and creation metadata. Unique on the complete digest tuple, with a composite candidate key including the local blob ID for release-level referential validation.
- `artifact_locations`: replaceable storage-provider/object-key locations for a blob; never part of portable identity.
- `factory_releases`: Factory FK, exact version, digest tuple and artifact-blob FK. Unique on (Factory FK, exact version); release association is immutable.

Use RESTRICT semantics for identity/release foreign keys. Do not cascade-delete historical identity, release or artifact records. Database checks enforce enumerated lifecycle values and timestamp consistency. Retired publishers cannot register new Factories/releases; retired Factories cannot register new releases, while historical reads remain available. PostgreSQL triggers and database privileges protect immutable identity columns and published release rows against UPDATE/DELETE.

## Transaction and artifact boundary

Artifact bytes live outside the relational database behind an artifact-storage interface. A release is published only after the artifact has been written and verified by the artifact-storage/digest layer (PSI-40). The registry then commits the publisher/factory association, blob metadata/location and release row in one database transaction. A failed database commit may leave an unreferenced content-addressed object; it must never leave a committed release pointing to absent blob metadata. Orphan-object reconciliation is an artifact-storage concern, not a reason to weaken release immutability.

Database uniqueness constraints, not preflight SELECTs, arbitrate concurrent claims. The losing transaction receives a deterministic conflict. Parent identity creation and release registration must be atomic within one database transaction. Exact retry/idempotency response semantics are specified by PSI-39.

## Rationale and evidence

- **Normative input:** ADR-003 fixes publisher and Factory identity, canonical comparison, immutability and tombstone semantics.
- **Repository evidence:** the current project is Python 3.11–3.13 with pytest and Ruff, and has no existing persistence backend to preserve.
- **Engineering judgment:** PostgreSQL is a strong first operational choice for a concurrent registry with relational integrity; SQLAlchemy/Alembic fit the existing Python implementation without making those technologies part of EFS.
- **Unresolved until implementation:** supported PostgreSQL major-version floor, deployment topology, connection-pool defaults, backup RPO/RTO, and exact SQLAlchemy/Alembic patch versions.

## Consequences

### Positive

- Portable publisher and Factory identities remain independent of database-generated IDs.
- Database uniqueness handles races across registry workers.
- Tombstones and immutable releases preserve history and federation conflict semantics.
- Content-addressed artifact identity is separate from mutable storage location.
- A repository boundary enables future adapters without changing EFS.

### Negative / trade-offs

- PostgreSQL is an operational dependency for the first production registry.
- PostgreSQL triggers/collation require PostgreSQL integration tests and backend-specific migration code.
- SQLAlchemy and Alembic add dependencies and migration discipline.
- Cross-system artifact/database publication is not a single distributed transaction; content-addressed writes and orphan reconciliation are required.

### Follow-up work

- [x] Founder approval of ADR-004 (2026-11-16).
- [ ] Implement SQLAlchemy domain/repository interfaces and PostgreSQL adapter.
- [ ] Add Alembic baseline migration and clean-database initialization.
- [ ] Add PostgreSQL constraints, immutable-field triggers and tombstone protections.
- [ ] Add PostgreSQL CI service and concurrency/migration tests.
- [ ] Implement artifact adapter and verified publication boundary in PSI-40.
- [ ] Specify API-level idempotency and deterministic conflict mapping in PSI-39.
- [ ] Document backup, restore, retention and orphan reconciliation before production rollout.

## Security, privacy and operations

Publisher URI syntax and database uniqueness do not prove namespace control. No row status in this schema may be rendered as verified/trusted without a separately governed proof-of-control and trust mechanism. Authentication and authorization are explicitly outside PSI-38.

Never dereference publisher URIs during persistence or lookup. Escape identifier strings in user interfaces. Do not store signing private keys or credentials in publisher records. Database access must use least-privilege roles; application roles must not bypass immutability protections. Audit and trust evidence are separate concerns and require their own governance.

## Compatibility and migration

The initial Alembic revision creates the registry schema from an empty database. There is no prior supported persistence schema in the repository today; therefore no fictitious legacy database upgrade is claimed. Subsequent revisions must be forward-only and tested from the previous supported revision. Published identity and release rows are not rewritten during migrations.

A future backend adapter must preserve exact identity equality, uniqueness, permanent tombstones, immutable release association and transaction semantics. Backend migration may copy local UUIDs or remap them only if all internal references are updated transactionally; portable publisher URI, Factory ID, release version and digest must remain unchanged.

Rollback is safe only before a migration has accepted writes that depend on the new schema. Destructive down-migrations of published registry data are prohibited; recovery uses forward fixes or backup restoration under an operator-approved recovery procedure.

## References

- RFC 3986 — Uniform Resource Identifier (URI): Generic Syntax.
- [ADR-003 — Publisher namespace and issuer/trust model](ADR-003-publisher-namespace-and-issuer-trust-model.md).
- [PSI-38 — Design registry persistence model](https://linear.app/getpsi/issue/PSI-38/design-registry-persistence-model).
- [PSI-39 — Implement manifest registry API](https://linear.app/getpsi/issue/PSI-39/implement-manifest-registry-api).
- [PSI-40 — Implement immutable release storage](https://linear.app/getpsi/issue/PSI-40/implement-immutable-release-storage).

## Change history

| Date | Change | Reason |
| --- | --- | --- |
| 2026-11-16 | Initial Proposed decision and relational model | PSI-38 persistence design |
