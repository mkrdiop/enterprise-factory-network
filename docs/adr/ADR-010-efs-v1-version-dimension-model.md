# ADR-010 — EFS v1 version-dimension model

- **Status:** Accepted
- **Date:** 2026-11-16
- **Decision owners:** EFS architecture (founder-authorized PSI-46 resolution)
- **Related Linear issues:** [PSI-46](https://linear.app/getpsi/issue/PSI-46/define-independent-semantic-version-dimensions), PSI-47, PSI-48, PSI-49
- **Related specifications:** [EFS v1 canonical Factory Manifest object model](https://app.notion.com/p/41af741d651181ac9488d932f13051f0), [EFS v1 capability and contract model](../efs-v1-capability-contract-model.md), [EFS v1 version-dimension model](../efs-v1-version-dimensions.md)
- **Supersedes / superseded by:** None

## Context

EFS v1 contains several version-like values with different meanings and owners: the specification version, Factory release version, capability contract version and implementation build identity. Treating all of them as one generic version would erase scope and ownership boundaries. In particular, PSI-42 explicitly makes contract versions opaque exact strings, while the current registry preserves exact release-version strings and immutable content digests.

M4 needs one normative decision before a parser, compatibility model or report engine can be implemented. Without it, different products could introduce incompatible version grammars or infer compatibility from unrelated identifiers.

## Decision drivers

- Preserve PSI-34 canonical manifest fields and PSI-42 contract-version semantics.
- Keep EFS specification, Factory release, contract and implementation build identities independent.
- Preserve exact immutable release coordinates and ADR-001 digest semantics.
- Permit deterministic comparison only where a dimension defines grammar and scope.
- Prevent product-local version vocabularies and false-positive compatibility claims.
- Avoid a breaking change to existing EFS v1 manifest representation.

## Options considered

### Option A — One SemVer grammar for every version-like value

Rejected. It conflicts directly with PSI-42's opaque contract-version rule, incorrectly assumes a universal build grammar, and encourages cross-dimension ordering.

### Option B — Four independent dimensions with field-specific semantics

Selected. Apply SemVer 2.0.0 only to EFS `efsVersion` and Factory `release.version`; preserve capability contract version as an opaque exact string; keep implementation build identity in external provenance with producer-owned semantics.

### Option C — Defer version semantics to each product

Rejected. This creates incompatible product-local interpretations and makes shared compatibility impossible to reproduce.

### Option D — Defer all comparison semantics to future work

Rejected as a complete solution. PSI-46 must establish grammar applicability, identity and scope now, while PSI-47 and PSI-48 implement parser and compatibility behavior against that fixed model.

## Decision

**Accepted: EFS v1 defines four independent version dimensions with the following field-aware semantics.**

1. **EFS specification version:** manifest root `efsVersion`; strict SemVer 2.0.0; owned by EFS; compared only with EFS specification versions.
2. **Factory release version:** `release.version`; strict SemVer 2.0.0; owned by the publisher's release stream; compared only within the exact `(publisher.id, factory.id)` scope. The exact supplied string remains the release coordinate.
3. **Capability contract version:** `capability.contract.version`; opaque non-empty exact string, ordinal and case-sensitive equality only. No SemVer parsing, precedence, ranges or negotiation in EFS v1. This preserves PSI-42.
4. **Implementation build version:** external build/provenance metadata, not a field in the EFS v1 core manifest. Its grammar and comparison semantics are owned by the build producer; consumers MUST NOT infer Factory release or contract semantics from it.

For the two SemVer fields, exact SemVer 2.0.0 grammar and precedence apply. Build metadata does not affect precedence. Distinct exact release labels with equal precedence MUST NOT be silently ordered or selected.

No cross-dimension comparison is valid. Factory release versions from different publisher/Factory identities are not comparable in the EFS release stream. The immutable release coordinate and digest rules under ADR-001/003/004 remain unchanged. A digest is content-integrity evidence, not a version or trust assertion.

Execution-profile, policy, protocol, dependency-constraint and external artifact identifiers retain their owning profile semantics; this ADR does not coerce them into the four dimensions.

## Rationale and evidence

- The current normative manifest schema defines `efsVersion`, `release.version` and `contract.version` as strings; this ADR assigns field-aware semantics without changing their representation.
- PSI-42 explicitly states that `contract.version` is opaque and not SemVer-comparable. Preserving it is mandatory for backward compatibility.
- ADR-003 fixes Factory identity as exact `(publisher.id, factory.id)`; release version is scoped below that identity.
- ADR-001 defines `efs-jcs-sha256-v1` as the immutable content digest profile. Digest and semantic version serve different purposes.
- The decision is encoded in `docs/efs-v1-version-dimensions.md` and language-neutral conformance vectors.

## Consequences

### Positive

- One field-aware version model governs all four products.
- Parser and compatibility implementations can be deterministic and tested against shared vectors.
- Contract semantics and immutable registry behavior are preserved.
- Build tooling remains free to evolve without polluting the portable manifest.

### Negative / trade-offs

- APIs must carry dimension and scope rather than accepting an unqualified version string.
- Equal-precedence release labels require exact selection; no automatic tie-breaker is available.
- Contract compatibility cannot be inferred from version ordering and needs explicit contract evidence.

### Follow-up work

- [x] Record the normative model and conformance vectors (PSI-46).
- [ ] Implement strict field-aware SemVer parsing and release change rules (PSI-47).
- [ ] Define compatibility dimensions, outcomes and evidence requirements (PSI-48).
- [ ] Implement the deterministic compatibility report engine (PSI-49).

## Security, privacy and operations

Version syntax, digest integrity, publisher identity, signature verification, trust, permission and runtime authorization are separate claims. Do not dereference opaque identifiers or infer namespace control from URI syntax. Do not select equal-precedence releases implicitly. Preserve exact release and contract coordinates in logs and reports.

## Compatibility and migration

No manifest field is added, removed or renamed. The structural schema remains unchanged. PSI-42 opaque contract versions are unchanged. Registry exact-string uniqueness and immutable release digests are unchanged. The normative decision does not rewrite historical records or require digest recomputation.

PSI-47 will implement semantic validation for the two SemVer-governed fields. Any rollout that rejects pre-existing non-SemVer values must inventory affected records and provide an explicit migration/compatibility plan; it must never silently rewrite immutable releases.

## References

- [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html)
- [ADR-001 — EFS v1 release digest profile](ADR-001-efs-v1-release-digest-profile.md)
- [ADR-003 — Publisher namespace and issuer/trust model](ADR-003-publisher-namespace-and-issuer-trust-model.md)
- [EFS v1 capability and contract model](../efs-v1-capability-contract-model.md)
- [PSI-42 — capability and contract model](https://linear.app/getpsi/issue/PSI-42/define-capability-and-contract-model)
- [PSI-46 — independent semantic-version dimensions](https://linear.app/getpsi/issue/PSI-46/define-independent-semantic-version-dimensions)

## Change history

| Date | Change | Reason |
| --- | --- | --- |
| 2026-11-16 | Accepted four-dimension field-aware version model | Resolve PSI-46 as normative gate for M4 |
