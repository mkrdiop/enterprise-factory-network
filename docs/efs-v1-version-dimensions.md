# EFS v1 version-dimension model

**Status:** Normative for EFS v1; PSI-46 implementation baseline  
**Authority:** Enterprise Factory Network (shared EFS reference definition)  
**Related work:** PSI-34–PSI-46; ADR-001, ADR-003 and ADR-004  
**Affected products:** Factory Studio, Factory Connect, Factory Runtime, Enterprise Factory Network

## 1. Purpose and authority

This specification defines the identity, ownership, scope, representation and comparison boundaries for version-like values used by EFS v1. It is the normative source for PSI-47 (version parser and release rules) and PSI-48 (compatibility dimensions and rules). PSI-49 consumes those shared rules and MUST NOT create a second version or compatibility model.

The four dimensions are independent. They do not share one global version namespace, owner, grammar or precedence relation. In particular, **EFS v1 does not apply SemVer to capability contract versions**: PSI-42's opaque-string rule remains binding.

The Network repository is the sole shared authority for the reference specification, machine-readable vectors and future parser/conformance implementations. Factory Studio, Factory Connect and Factory Runtime MUST consume these definitions through adapters. Product adapters MAY translate native build metadata into external provenance, but MUST NOT redefine EFS version semantics.

Normative terms MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are requirements.

## 2. Normative dimension matrix

| Dimension | Canonical source / representation | Owner and scope | EFS v1 grammar and comparison |
| --- | --- | --- | --- |
| EFS specification version | Root manifest field `efsVersion` | EFS specification authority; identifies the EFS specification semantics used by the manifest | Strict Semantic Versioning 2.0.0. Compare only with another EFS specification version. |
| Factory release version | `release.version` | Publisher's Factory release stream, scoped to the exact Factory identity `(publisher.id, factory.id)` | Strict Semantic Versioning 2.0.0. Compare only within the same exact publisher/Factory scope. Exact stored string remains the release coordinate. |
| Capability contract version | `capability.contract.version` | Contract owner; scoped to the exact opaque `contract.id` and capability definition | Opaque, non-empty, exact string. Equality is ordinal, case-sensitive string equality. No SemVer parsing, ordering, precedence or range inference. |
| Implementation build version | External build/provenance metadata; not a field in the EFS v1 core manifest | Build producer/build system; scoped to its own artifact/build identity | EFS v1 assigns no grammar or universal comparison semantics. A producer MAY use SemVer under its own policy; consumers MUST NOT assume it. |

These are the only four dimensions standardized by this model. The words “version”, “revision”, “profile”, “protocol”, “build” or “release” in other fields do not automatically make those values members of one of these dimensions.

## 3. SemVer-governed fields

Only `efsVersion` and `release.version` use Semantic Versioning 2.0.0 in EFS v1. Implementations that parse either field MUST implement the exact SemVer 2.0.0 grammar and precedence rules, including prerelease identifiers and build metadata.

The following are invalid for these two fields:
- a leading `v` or other prefix;
- whitespace or surrounding whitespace;
- partial versions such as `1` or `1.2`;
- missing core numeric components;
- leading zeroes in numeric core identifiers or numeric prerelease identifiers (except the value `0`);
- non-ASCII or malformed SemVer syntax;
- coercion, shorthand expansion or implementation-specific normalization.

Precedence follows SemVer 2.0.0. A stable version has higher precedence than its prereleases. Prerelease identifiers are compared using the SemVer rules. Build metadata is ignored for precedence.

Two distinct exact version strings that differ only in build metadata are distinct labels but have equal SemVer precedence. For example, `1.2.3+build.7` and `1.2.3+build.8` are not ordered relative to one another. A registry or consumer MUST NOT choose one over the other by lexical order, insertion time, digest, or an invented tie-breaker. A caller MUST select the exact release coordinate.

An implementation MUST NOT compare `efsVersion` with `release.version`, even though both use SemVer. It MUST NOT compare Factory release versions across different publisher/Factory identities. A SemVer library may be reused internally, but every API and rule MUST retain the dimension and scope so invalid cross-dimension comparisons can be rejected.

## 4. Opaque capability contract version

PSI-42 defines `capability.contract.version` as a non-empty opaque string. EFS v1 preserves that decision without reinterpretation.

- A contract version is valid at this layer when it is a non-empty string satisfying the EFS v1 structural schema.
- Equality is exact and case-sensitive. No trimming, case folding, Unicode normalization, URI normalization, parsing, numeric conversion or aliasing is performed.
- Values such as `1.0.0`, `2026-Q4`, `vNext` and `vendor:blue` are opaque values. Their appearance does not imply a grammar or ordering.
- EFS v1 defines no contract-version precedence, “newer” relation, range expression, negotiation or automatic upgrade.
- The portable contract definition coordinate is the exact pair `(contract.id, contract.version)`. A capability invocation additionally binds that contract to the exact immutable publisher/Factory/release/digest/capability coordinate under PSI-44.
- A consumer MUST NOT search for a matching contract ID and silently substitute another version.

A future EFS revision MAY introduce an explicitly named contract-version profile. Such a change requires a successor specification/profile and ADR, explicit versioned opt-in, migration analysis and new conformance vectors. It MUST NOT retroactively change the meaning of EFS v1 manifests or the PSI-42 contract model.

## 5. Implementation build version

Implementation build identity is external provenance, not portable Factory or contract identity.

- EFS v1 adds no `buildVersion` property to the core Factory Manifest.
- The build producer owns the representation and grammar of its build identifier.
- A build record SHOULD bind to the exact artifact or implementation subject it describes. It MUST NOT replace the Factory release coordinate or its digest.
- A consumer MUST NOT infer Factory release precedence, contract compatibility, publisher identity, authenticity or trust from a build identifier.
- Build provenance MAY be carried in separately governed artifact/attestation metadata. Its schema and trust semantics are outside PSI-46.

This boundary permits reproducible build systems and product-specific pipelines without fragmenting the portable EFS v1 manifest.

## 6. Release identity, immutability and digest separation

The canonical Factory identity remains the exact pair `(publisher.id, factory.id)` under ADR-003. Release version is not part of that stable Factory identity; it identifies one immutable release within that Factory's release stream.

The exact release coordinate is:

```text
(
  publisher.id,
  factory.id,
  release.version,
  release.digest.profile,
  release.digest.algorithm,
  release.digest.value
)
```

The digest profile `efs-jcs-sha256-v1` identifies exact release content under ADR-001. The version labels evolution; the digest binds content. They are complementary and MUST NOT be substituted for one another.

- The registry MUST preserve the exact supplied `release.version` string; it MUST NOT rewrite or normalize it.
- The registry's immutable uniqueness constraint remains exact-string uniqueness for `(publisher.id, factory.id, release.version)`.
- Re-publication of different content under the same exact release coordinate/version is a conflict, not an update.
- A new digest does not silently create a new release version, repair a conflict or authorize replacement.
- Equal SemVer precedence does not weaken exact release identity or immutable storage rules.
- A matching digest establishes content integrity only. It does not prove publisher identity, namespace control, authenticity, trust, permission or authorization.

## 7. Cross-dimension references and non-inference

A manifest's EFS specification version, Factory release version, capability contract version and implementation build identifier MUST remain separately represented and separately interpreted.

| Reference / field | Resolution rule |
| --- | --- |
| `efsVersion` | Selects the EFS specification semantics; it is not a Factory release. |
| `release.version` | Exact release label within one publisher/Factory identity; digest binds its immutable content. |
| `contract.id` + `contract.version` | Exact opaque contract coordinate; scoped to its capability definition and selected immutable release for invocation. |
| Implementation build identifier | Resolved only through the separately governed provenance/artifact system that owns it. |

Execution-profile references, policy profile/version values, protocol identifiers, dependency `versionConstraint` strings and external artifact versions are not implicitly governed by this four-dimension model. Their grammar and comparison semantics belong to their owning profiles. PSI-48 MAY evaluate such a value only when that profile supplies explicit rules and evidence. No generic SemVer parser may coerce them into Factory release SemVer.

No dimension may be inferred from display names, endpoint addresses, timestamps, digest values, database IDs, registry insertion order or the value of another dimension.

## 8. Relationship to validation, compatibility and trust

The following are separate stages and claims:

1. Structural validation determines whether fields satisfy the EFS v1 schema.
2. Version validation parses only the SemVer-governed fields identified in this specification.
3. Digest verification establishes content integrity for the exact release artifact.
4. Signature and publisher trust verification establish claims only under the separately governed trust model (M5).
5. Compatibility assessment evaluates exact subject and consumer profiles using PSI-48 rules and explicit evidence.
6. Policy evaluation and runtime admission determine whether a particular operation is authorized and supported.

Passing one stage MUST NOT be represented as proof of another. In particular, a syntactically valid version or compatible report does not establish trust or authorization.

## 9. Conformance vectors and acceptance

The language-neutral normative vectors are in `conformance/efs/v1/version-dimension-vectors.json`; PSI-46 acceptance traceability is in `conformance/efs/v1/version-dimension-acceptance.json`.

The vectors specify field ownership, grammar applicability, exact equality, scope, immutability, SemVer edge cases and prohibited inferences. They are normative test inputs for PSI-47 and PSI-48. PSI-46 does not implement a production parser or compatibility evaluator; those are subsequent issues.

## 10. Compatibility and migration

This decision does not add, remove or rename EFS v1 manifest fields. It does not alter the Draft 2020-12 schema's current structural acceptance of non-empty version strings. SemVer grammar enforcement is a separate semantic-validation implementation under PSI-47; PSI-46 first establishes the normative field-aware meaning.

The registry continues to preserve exact release-version strings and existing immutable uniqueness. Existing release records are not rewritten. Contract versions remain opaque as before PSI-46. No implementation build field is added to the manifest. Therefore, the normative decision itself does not require a manifest migration or digest recomputation.

A later implementation that rejects a previously stored non-SemVer `efsVersion` or `release.version` must report and plan that rollout explicitly; it MUST NOT silently rewrite a published immutable release. Any actual EFS specification profile migration requires its own compatibility and rollout plan.

## 11. Explicit non-goals

- Implementing the parser/comparator or Factory release change classifier (PSI-47).
- Defining compatibility outcomes, supported ranges or evidence sufficiency (PSI-48).
- Implementing a compatibility report engine (PSI-49).
- Parsing contract versions as SemVer.
- Defining dependency constraint, execution profile, protocol or policy version grammars.
- Adding build metadata to the EFS v1 core manifest.
- Automatic “latest” or “latest compatible” resolution, version negotiation or upgrade selection.
- Signatures, key discovery, publisher trust, permissions, authorization or revocation (M5).
- Rewriting historical manifests, release coordinates or digests.

## 12. Change control

This document is the normative EFS v1 version-dimension authority. PSI-47 and PSI-48 MUST link to and implement it. A change to a dimension's owner, field, grammar, scope, comparison semantics or cross-reference rule requires a successor ADR and a versioned specification change with conformance and migration impact analysis. Product-local overrides are prohibited.
