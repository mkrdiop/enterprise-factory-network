# Factory Passport v1

**Status:** Implemented baseline for PSI-41.  
**Authority:** A Passport is a deterministic, read-only projection of one exact registered EFS v1 release. It is not a new EFS object, identity, release, publication, trust assertion, certification or authorization.

## Source selection and authority

A Passport is generated only from the exact tuple `(publisher.id, factory.id, release.version)` requested from the registry. The registry query repository selects the committed release record and its immutable artifact location. The API reads the digest-addressed artifact and independently verifies/reconstructs the manifest before projection. Pending publication operations are not eligible sources.

Publisher identity remains the canonical opaque absolute URI governed by ADR-003. Factory identity remains the exact case-sensitive pair `(publisher.id, factory.id)`. Release version and digest are copied from the registered manifest and checked against the registry record. The Passport assigns no identifier and has no independent lifecycle.

## Representation

The normative JSON Schema is `schemas/passport/v1/factory-passport.schema.json`. `passportVersion` versions the projection contract only; it is not a factory or release version.

- `source`: exact EFS coordinates, digest and registry release record metadata.
- `publisher`, `factory`, `release`: declared identity/display metadata.
- `capabilities`: capability descriptions, full contract payloads, endpoints and declared capability execution profiles.
- `execution`: embedded profiles or external profile references exactly as declared. External references are not dereferenced or represented as resolved.
- `dependencies` and `policies`: declarations/references exactly as declared. They are not resolved or evaluated.
- `extensions`: copied without interpretation when present.
- `assurance`: artifact integrity is `verified` because the registry API has read and verified the immutable digest artifact. Publisher authentication, trust, signature verification and authorization are explicitly `not_evaluated`. Signature material is not included in the digest-addressed artifact.
- `provenance`: one entry for each copied leaf or empty container, mapping Passport JSON Pointer to source namespace and source JSON Pointer.

Optional source fields are omitted when absent. Empty arrays/objects are preserved. Array order is preserved from the source manifest; object member ordering is canonicalized for serialization. No runtime state, deployment, credentials, permissions, commercial metadata, certification, ratings or inferred capability claims are added.

## Determinism

For identical verified manifest content and identical registry metadata, the Passport object is identical. Machine-readable output is RFC 8785 JCS bytes. Provenance entries are sorted by target pointer, source namespace and source pointer. Source arrays retain their authored order; no semantic or alphabetical reordering is introduced. Human-readable Markdown is rendered from the same Passport object, has no generated timestamp, and uses stable section/field order.

## Provenance semantics

- `source=manifest`: `sourcePointer` is an RFC 6901 JSON Pointer into the verified reconstructed EFS manifest.
- `source=registry`: pointer addresses the named registry metadata record, not a manifest field.
- `rule=copy`: value is copied without reinterpretation. The assurance section is a fixed derivation from successful registry artifact verification and is described explicitly by its field contract; it does not claim publisher trust.

The registry record UUID is a registry-local reference only. It does not replace publisher/factory/release identity.

## API

- `GET /v1/passports?publisher_id=...&factory_id=...&version=...` returns canonical JSON.
- `GET /v1/passports?...&format=markdown` returns the human-readable rendering.

Both formats require an exact version. There is no latest-version lookup or independently mutable Passport endpoint. Missing releases return the registry's existing not-found error; unavailable or integrity-failing artifacts use the existing artifact errors.

## Non-goals

No passport persistence, publisher profile database, authentication/trust scoring, signature validation, policy evaluation, dependency resolution, endpoint health checks, runtime state, marketplace ranking or certification is implemented by PSI-41.
