# ADR-003 — Publisher namespace and issuer/trust model

- **Status:** Accepted
- **Date:** 2026-11-16
- **Decision owners:** Founder / EFS architecture
- **Related Linear issues:** [PSI-37](https://linear.app/getpsi/issue/PSI-37/define-factory-identity-and-publisher-namespace), [PSI-50](https://linear.app/getpsi/issue/PSI-50/define-signing-and-digest-envelope)
- **Related specifications:** [EFS v1 Canonical Factory Manifest Object Model](https://app.notion.com/p/41af741d651181ac9488d932f13051f0), [EFS v1 Requirements Baseline](https://app.notion.com/p/41af741d651181ee87d5e868b6167d54)
- **Supersedes / superseded by:** None

## Context

EFS v1 defines stable logical Factory identity as the pair `(publisher.id, factory.id)`. The publisher and factory identifiers remain stable across release versions. The PSI-34 canonical model separates identity from display names, locations, release versions, execution identities and trust.

The EFS v1 schema currently accepts any non-empty string for `publisher.id`. That is insufficient for an interoperable, publisher-scoped registry and federation model. PSI-37 must define the identifier syntax, canonical comparison, collision behavior and lifecycle without making an identifier itself proof of ownership or trust.

## Decision

**Use an absolute URI as the opaque publisher identifier.** The URI is a durable name, not a network address to be fetched and not evidence that the presenter controls the namespace.

The following profile is normative for EFS v1 publisher identifiers.

### 1. Identifier syntax

1. `publisher.id` MUST be an absolute URI conforming to RFC 3986. Relative references and IRIs outside the RFC 3986 ASCII URI syntax are not accepted.
2. The URI MUST contain a valid scheme. The scheme is case-insensitive and is serialized in lowercase.
3. The identifier MUST NOT contain a query component, fragment component or userinfo component. These components make durable identity comparison needlessly dependent on application semantics or credential-like material.
4. Whitespace, control characters, malformed percent-encoding, invalid authority syntax and non-ASCII literal characters MUST be rejected. Internationalized domain names MUST use their ASCII A-label form. Non-ASCII path data, if needed, MUST be UTF-8 percent-encoded.
5. No scheme allow-list is imposed by EFS v1. This preserves URI/URN extensibility. A scheme's presence does not make its namespace authoritative; namespace entitlement is a separate verification concern.
6. Illustrative valid identifiers include `urn:example:publishers:acme` and `https://identity.example/publishers/acme`. They are examples, not reserved namespaces or endorsements.

### 2. Canonical serialization and equality

EFS v1 uses the canonical comparison profile **`efs-uri-c14n-1`**, based on the generic syntax-based normalization rules in RFC 3986 §6.2.2:

1. Lowercase the URI scheme.
2. If an authority contains a host, lowercase the host. This includes hexadecimal letters in an IPv6 literal. Do not lowercase the path.
3. Normalize percent-encoding: decode percent-encoded octets only when they represent RFC 3986 unreserved characters; uppercase hexadecimal digits in all remaining percent triplets. Reject malformed triplets.
4. Remove dot segments from hierarchical paths using the RFC 3986 dot-segment algorithm.
5. Preserve all other components exactly. In particular, preserve path case, explicit ports (including an explicitly supplied default port), empty-path versus slash distinctions, and reserved-character escaping. Do not reorder or reinterpret components.
6. Do not apply scheme-specific normalization, DNS/IDNA conversion, Unicode normalization, default-port inference, redirect resolution or application-level equivalence rules.

A publisher identifier supplied in a manifest MUST already be in this canonical serialized form. Validators MUST reject a non-canonical spelling rather than silently rewriting it. Registry storage and comparison use the canonical string and ordinal, case-sensitive equality. Implementations MUST NOT trim, case-fold, Unicode-normalize or otherwise rewrite the identifier.

This deliberately chooses deterministic generic syntax normalization rather than attempting to decide whether two URIs are semantically equivalent under an unknown scheme. Two different canonical strings are different identifiers, even if a scheme operator or application considers them equivalent.

### 3. Opaque identity semantics

- An identifier MUST NOT be dereferenced during parsing, schema validation, conformance validation, registration identity comparison or ordinary registry lookup.
- Implementations MUST NOT fetch it over HTTP, follow redirects, resolve DNS, consult a URI scheme handler, or perform key discovery as part of identity processing.
- The URI MAY be non-resolvable. Its continued existence as an identity does not depend on a live website, DNS record, registry endpoint or hosting provider.
- The URI does not encode or prove a publisher's display name, legal status, current owner, signing key, trust level or permissions.
- Publisher website, hosting, display name, contact details and signing keys may change without changing `publisher.id`.

### 4. Factory identity and comparison

The canonical Factory identity remains the pair:

`(canonical publisher.id, factory.id)`

- `factory.id` remains an opaque, non-empty JSON string as defined by EFS v1; PSI-37 does not require it to be a URI.
- Factory IDs are compared exactly and case-sensitively by their decoded Unicode scalar sequence. No case folding or Unicode normalization is applied. JSON escape spelling is not identity-bearing; the decoded string value is.
- The same `factory.id` under two different canonical publisher IDs identifies two different Factories.
- Release version, digest, factory name, publisher name, registry record ID, endpoint URL and runtime execution identity are not part of the Factory identity.
- Display names may change between releases without changing the identity pair.

### 5. Namespace ownership, claims and collisions

URI syntax does not establish namespace entitlement. A registry MUST distinguish an identifier claim from a verified publisher identity.

- A client submitting a previously unseen URI MUST NOT, by that act alone, be treated as having proved control of its namespace.
- A registry MUST NOT silently merge two publisher records or transfer a publisher ID because the URI strings match or because a claimant is first to submit it.
- A registry MUST enforce uniqueness on the canonical publisher URI and on the pair `(publisher.id, factory.id)`.
- A repeated claim for an existing canonical publisher URI is a deterministic conflict unless the claimant is already authenticated and authorized to manage that publisher record under the registry's separately defined account/ownership controls.
- Federation compares canonical strings. If independently operated registries contain conflicting claims for the same canonical URI, they MUST surface a conflict for verification; they MUST NOT resolve it by first-seen precedence or automatic merge.
- Proof of namespace control, issuer authentication, key binding, trust evaluation and authorization are separate controls, governed by PSI-50/51 and the security/trust workstream. The verification mechanism may differ by URI scheme and must not be inferred from syntax.

### 6. Stability, retirement and transfer

1. A publisher URI is immutable once registered as a publisher identity. It MUST NOT be edited in place or reassigned to a different publisher.
2. A retired publisher identity MUST remain as a permanent tombstone. Its URI is never made available for reuse. Historical releases and audit references continue to resolve to the original identity record.
3. A Factory identity pair is likewise never reassigned. Retiring a Factory does not release its `factory.id` for reuse under that publisher.
4. EFS v1 does not define publisher-identity transfer, URI rename, alias-based identity equivalence or automatic legal-entity succession. These operations are unsupported in v1. A successor publisher uses a new publisher URI and new Factory identity pairs; any future authenticated migration/transfer protocol requires a successor ADR and explicit provenance.
5. A publisher changing its website, legal/display name, infrastructure or keys does not need a new URI if the publisher namespace remains under its control. A loss of namespace control is a trust/security incident, not a reason for the registry to silently reassign the identity.

### 7. Registry record separation

The registry MUST keep these concepts distinct:

- canonical publisher URI (portable identity);
- registry-local publisher record ID (database key);
- publisher display and contact metadata (mutable descriptive data);
- namespace-ownership verification state and evidence;
- issuer/signing-key identities and trust state;
- Factory identity pair;
- immutable release version and digest;
- artifact retrieval/storage location.

A registry-local database ID MUST NOT leak into the portable manifest as a replacement for `publisher.id`. A retrieval URL MUST NOT be treated as the publisher identity.

## Options considered

| Option | Decision | Rationale |
| --- | --- | --- |
| Absolute URI, opaque | **Selected** | Decentralized namespace, extensible URI/URN forms, no central allocator or network lookup |
| Registry-issued UUID | Rejected | Couples identity creation and portability to registry allocation |
| Reverse-DNS string | Rejected | Tightly couples identity syntax to DNS and domain lifecycle while offering no proof of current control |
| Defer / arbitrary string | Rejected | Leaves uniqueness and federation comparison underspecified |

## Compatibility and migration

The PSI-35 structural schema predates the completed publisher identity profile and currently accepts a non-empty string. The existing canonical valid fixture uses `urn:example:publishers:acme`, which already satisfies the selected absolute-URI direction.

From acceptance of this ADR onward, an EFS v1 manifest is conformant only when `publisher.id` satisfies `efs-uri-c14n-1`. The schema and layered conformance validator must be updated to enforce this rule. A non-URI or non-canonical publisher ID accepted by the earlier structural-only schema is not grandfathered into registry admission.

Implementations MUST NOT silently rewrite an existing manifest: changing `publisher.id` changes the Factory identity and release digest projection. A publisher that needs to migrate a pre-profile draft must issue a new manifest under the new identity and recompute its release digest. Already published immutable artifacts, if any, remain unchanged and are not reassigned. Before external production rollout, operators must inventory any pre-profile manifests and plan explicit publisher-led migration.

This is an explicit completion of the EFS v1 identity profile, not a change to the PSI-34 canonical object shape.

## Security, privacy and operations

- URI validation and canonicalization MUST be local and deterministic. They must not create an SSRF, DNS-rebinding, redirect or ambient-network dependency.
- Registry uniqueness is not ownership verification. An unverified claim must not be presented as a verified publisher or as a trust certification.
- Verification evidence and audit events belong to registry/security records, not to the URI string. Do not store credentials or private keys in the publisher identity record.
- URI strings can contain sensitive-looking or misleading text even when syntactically valid. Render them as data, escape them in user interfaces and never execute or navigate them automatically.
- Exact comparison avoids accidental identity collapse, but visually confusable strings remain possible. Registries may warn operators; they MUST NOT silently normalize or merge identities.

## Consequences

### Positive

- Provides a portable publisher namespace without a central UUID allocator.
- Supports URI and URN identifiers while keeping identity independent of network availability.
- Defines deterministic comparison and collision behavior across implementations.
- Makes publisher identity, namespace control, authentication, trust, authorization and artifact location explicitly separate.
- Preserves the PSI-34 Factory identity pair.

### Trade-offs

- URI syntax and canonicalization require a shared implementation and test vectors.
- URI syntax cannot prove namespace ownership; a separate verification and trust system is mandatory for verified publisher claims.
- Exact opaque comparison intentionally treats distinct canonical strings as distinct identities, even where an external scheme might consider them equivalent.
- v1 does not support identity transfer or alias-based migration.

## Follow-up work

- [ ] Add the `efs-uri-c14n-1` publisher identifier vectors and conformance tests.
- [ ] Update the Draft 2020-12 schema and layered validator to enforce the absolute, canonical URI profile.
- [ ] Add deterministic diagnostics for invalid and non-canonical publisher IDs.
- [ ] Ensure registry persistence uses canonical publisher IDs and permanent tombstones.
- [ ] Keep publisher proof-of-control, issuer authentication, signing keys, trust roots and revocation in PSI-50/51 and M5.
- [ ] Inventory any pre-profile external manifests before production registry admission.

## References

- RFC 3986 — Uniform Resource Identifier (URI): Generic Syntax, especially §§2.1, 2.3, 3 and 6.2.2.
- PSI-34 canonical object model and approved decision set.
- PSI-35 Draft 2020-12 schema implementation.
- PSI-36 conformance implementation.
- [PSI-37 Linear issue](https://linear.app/getpsi/issue/PSI-37/define-factory-identity-and-publisher-namespace).
- `docs/semantic-validation-boundary.md`.

## Change history

| Date | Change | Reason |
| --- | --- | --- |
| 2026-11-16 | Accepted identity model: opaque absolute URI, `efs-uri-c14n-1`, exact Factory pair comparison, permanent tombstones and no v1 transfer | Founder selected absolute URI and delegated resolution of the remaining identity-model choices |
