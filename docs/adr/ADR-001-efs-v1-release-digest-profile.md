# ADR-001 — EFS v1 release digest profile

- **Status:** Accepted
- **Date:** 2026-11-16
- **Decision owners:** EFS v1 founder approval
- **Related Linear issues:** PSI-34, PSI-35
- **Related specification:** [EFS v1 — Canonical Factory Manifest Object Model, Section 12](https://app.notion.com/p/41af741d651181ac9488d932f13051f0)

## Context

EFS v1 requires an integrity binding for an immutable Factory Release. The digest must be deterministic across independent implementations and must not depend on a self-referential serialization of the digest field. The canonical object model needs a profile precise enough for schema consumers and future registry/signature implementations.

## Decision drivers

- Deterministic canonicalization across implementations.
- Explicit domain separation to prevent cross-object digest reuse.
- A stable, URL-safe textual encoding.
- Separation of content integrity from publisher authentication and trust.
- No unrestricted network dependency in the digest calculation.

## Options considered

### Option A — Profiled JCS and SHA-256

Use JSON Canonicalization Scheme (RFC 8785), SHA-256 and unpadded Base64URL, with a domain-separated envelope and explicit projection/exclusion rules.

### Option B — Implementation-defined JSON serialization

Allow each implementation to serialize the manifest before hashing.

This is simpler initially but cannot guarantee interoperable digests across implementations.

### Option C — Defer the digest profile

Keep only an opaque digest field until a later registry/signature design.

This delays interoperability and leaves release identity/integrity semantics underspecified.

## Decision

**Accepted:** EFS v1 uses the profile identifier `efs-jcs-sha256-v1`:

- Canonicalization: JSON Canonicalization Scheme (RFC 8785).
- Digest algorithm: SHA-256.
- Text encoding: unpadded Base64URL.
- Preimage envelope: `{"domain":"efs.factory-release.v1","manifest":"<manifest projection>"}`.
- The release-defining projection excludes only `release.digest` and `release.signature`.
- Duplicate JSON object member names and inputs outside the supported I-JSON/JCS constraints are rejected.

The digest profile, algorithm and value are required. Digest verification establishes content integrity only; it does not authenticate a publisher or establish trust. Signature and trust verification remain separate.

## Rationale and evidence

The founder-approved PSI-34 decision set records this exact profile and its exclusion rules. PSI-35 implements the manifest schema shape; PSI-36 deliberately does not implement digest computation or verification. This ADR records the already-approved PSI-34 decision and does not expand PSI-36 conformance claims.

## Consequences

### Positive

- Independent implementations have a deterministic release digest contract.
- Domain separation prevents accidental cross-domain interpretation.
- Digest and signature/trust responsibilities remain separate.

### Negative / trade-offs

- Implementations must support RFC 8785 and the specified I-JSON restrictions.
- A dedicated digest implementation and golden vectors require their own implementation/acceptance work.

### Follow-up work

- [ ] Implement and test digest computation/verification under the owning release-integrity issue.
- [ ] Add cross-language golden vectors before claiming multi-language digest conformance.
- [ ] Define signature/key discovery/trust separately under PSI-50.

## Security, privacy and operations

Reject duplicate object names and invalid canonicalization inputs. Do not treat a matching digest as proof of publisher identity, authorization or trust. Do not fetch external resources to calculate the digest.

## Compatibility and migration

The profile identifier is part of the release integrity contract. Any future change to canonicalization, digest algorithm, envelope, projection or encoding requires a new profile/version and an explicit compatibility/migration decision; it must not silently reinterpret existing digests.

## References

- [RFC 8785 — JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785)
- [PSI-34 canonical object model and approved decision set](https://app.notion.com/p/41af741d651181ac9488d932f13051f0)
- [PSI-35 schema implementation](https://github.com/mkrdiop/enterprise-factory-network/pull/1)

## Change history

| Date | Change | Reason |
| --- | --- | --- |
| 2026-11-16 | Recorded accepted digest profile | Preserve founder-approved PSI-34 decision in Git ADR index |
