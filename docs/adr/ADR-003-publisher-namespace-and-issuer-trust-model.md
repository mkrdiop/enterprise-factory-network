# ADR-003 — Publisher namespace and issuer/trust model

- **Status:** Proposed
- **Date:** 2026-11-16
- **Decision owners:** Founder / EFS architecture
- **Related Linear issues:** [PSI-37](https://linear.app/getpsi/issue/PSI-37/define-factory-identity-and-publisher-namespace), [PSI-50](https://linear.app/getpsi/issue/PSI-50/define-signing-and-digest-envelope)
- **Related specifications:** [EFS v1 Canonical Factory Manifest Object Model](https://app.notion.com/p/41af741d651181ac9488d932f13051f0), [EFS v1 Requirements Baseline](https://app.notion.com/p/41af741d651181ee87d5e868b6167d54)
- **Supersedes / superseded by:** None

## Context

EFS v1 defines the stable logical Factory identity as the pair `(publisher.id, factory.id)`. The publisher and factory identifiers must remain stable across release versions. The manifest schema currently validates `publisher.id` as a non-empty string; the PSI-36 semantic-validation handoff explicitly identifies the identity pair but does not prescribe the publisher identifier grammar.

The registry needs a publisher namespace that works across independent publishers and registry deployments. It must avoid conflating identity with authentication, trust, authorization, hosting location, or a mutable display name. A publisher identifier is a durable name, not evidence that the party presenting it controls that name.

The existing schema and conformance corpus intentionally leave this decision open. This ADR is therefore a proposal for founder review, not an accepted normative rule.

## Decision drivers

- Global uniqueness without requiring a single central registry operator.
- Stable identity across hosting, domain, key and organizational changes.
- Clear comparison and collision behavior across implementations.
- No network lookup as a prerequisite for parsing or comparing identity.
- Separation of identifier ownership claims from cryptographic authentication and trust.
- Compatibility with the existing EFS manifest shape and future federation.

## Options considered

### Option A — Absolute URI as an opaque publisher identifier

Require `publisher.id` to be an absolute URI. Treat the URI as an opaque identifier after syntax validation; do not dereference it during validation, registration or comparison. The namespace authority is responsible for choosing an identifier it is entitled to use. Registry uniqueness constraints prevent duplicate registration within the registry.

**Benefits**
- Reuses a mature, extensible identifier syntax already used by EFS capability contracts and policy profiles.
- Supports multiple URI schemes and decentralized namespace authorities.
- Does not require the identifier to resolve or imply that a web endpoint is authoritative.
- Separates stable identity from the registry's retrieval URL and from trust/key-discovery mechanisms.

**Costs / risks**
- URI syntax is broad; a stricter canonical representation and comparison profile is required.
- Different URI spellings can be semantically related but textually distinct unless canonicalization rules are explicit.
- A URI namespace does not itself prove that the registrant controls the corresponding namespace.

### Option B — Registry-issued opaque UUID

The registry assigns a UUID to each publisher and becomes the authoritative allocator for that namespace.

**Benefits**
- Straightforward syntax and exact comparison.
- Low collision probability without URI normalization.
- Simple database uniqueness constraints.

**Costs / risks**
- Introduces registry allocation and portability semantics.
- Multiple registries need a global allocation or identity-migration strategy.
- Publishers cannot independently establish a stable identity before choosing a registry.
- UUID possession still does not authenticate a publisher.

### Option C — Reverse-DNS publisher identifier

Use a reverse-domain string derived from a publisher-controlled DNS name.

**Benefits**
- Human-readable and familiar to many software ecosystems.
- Naturally scoped by a domain namespace.

**Costs / risks**
- Couples identity to DNS naming and domain lifecycle.
- Requires explicit rules for domain transfer, expiration, and organizational change.
- Less extensible than URI syntax and can be confused with proof of current domain control.
- DNS ownership checks would be trust/verification procedures, not identity parsing.

### Option D — Defer

Keep the current non-empty-string schema and postpone the publisher namespace decision.

**Benefits**
- Avoids prematurely constraining the ecosystem before registry federation requirements are fully tested.

**Costs / risks**
- Registry persistence, uniqueness, API routing and interoperability remain underspecified.
- Different implementations may silently adopt incompatible grammars.

## Proposed direction (not yet accepted)

Prefer **Option A: absolute URI identifiers with opaque identity semantics**, subject to a stricter EFS publisher-identifier profile being agreed.

The proposed profile should:
1. Require an absolute URI and reject whitespace, control characters, relative references and malformed percent-encoding.
2. Define one canonical serialization/comparison rule before any implementation uses the identifier as a database key. Do not invent ad hoc case-folding or Unicode normalization.
3. Treat the identifier as an opaque name: no dereferencing, DNS resolution, HTTP fetch, or key lookup during structural validation or identity comparison.
4. Permit an identifier to remain stable if the publisher changes its website, hosting, legal name, or signing keys.
5. Prohibit silent reassignment. Namespace control challenges, if required, belong to a separate publisher-verification/trust workflow.
6. Keep registry record IDs, artifact locations, publisher IDs, factory IDs, release versions and runtime execution identities separate.

A possible illustrative form is `https://identity.example/publishers/acme`; it is an example only, not a selected required namespace or an endorsed domain.

## Decision

**Pending founder approval.** No publisher URI grammar, canonicalization algorithm, issuer verification method, or identity-transfer policy is normative until the founder explicitly accepts this ADR or a revised successor.

The stable logical Factory identity remains `(publisher.id, factory.id)`, as already approved in PSI-34. This ADR addresses the still-open syntax and namespace semantics of `publisher.id`; it does not reopen the canonical object model.

## Rationale and evidence

- PSI-34 approved the stable identity pair and separated identity from location/trust.
- The EFS v1 schema currently constrains `publisher.id` only to a non-empty string.
- `docs/semantic-validation-boundary.md` explicitly lists the identity pair as a semantic invariant and leaves the identity/dependency profile to follow-up work.
- The PSI-36 conformance corpus does not claim to validate a publisher namespace grammar.

No benchmark or interoperability test has yet established the final URI canonicalization profile. That is an open acceptance requirement, not an assumed fact.

## Consequences

### Positive

- Prevents publisher identity from being conflated with key material, web endpoints or registry-local database IDs.
- Preserves the existing EFS identity pair and leaves room for federated registries.
- Establishes a clear boundary between identity parsing and publisher trust verification.

### Negative / trade-offs

- An absolute URI profile and canonical comparison rules add specification work.
- URI syntax does not prove namespace ownership; a later trust/verification layer is required where publisher authenticity matters.

### Follow-up work

- [ ] Founder selects or revises the proposed publisher identifier profile.
- [ ] Define exact URI canonicalization/comparison and forbidden components.
- [ ] Define publisher/factory deletion, tombstone and non-reassignment behavior.
- [ ] Add machine-readable valid/invalid identity vectors and semantic conformance tests.
- [ ] Reconcile JSON Schema and validator behavior with the accepted profile.
- [ ] Keep issuer authentication, signing keys, trust roots and revocation in PSI-50/51 and M5.

## Security, privacy and operations

A syntactically valid identifier is not an authenticated identity. Registry registration must not grant ownership merely because a client submits an unused publisher ID. Authentication, namespace-control verification, signing-key binding, trust evaluation and authorization are separate controls and must be designed independently.

No identity parser may fetch a URI, follow redirects, resolve DNS, or trust content at the identifier URI. This prevents validation-time SSRF and keeps offline conformance deterministic.

Registry audit events should record who attempted to claim or modify a publisher namespace, which verification procedure (if any) was applied, and the resulting decision. Do not store credentials or private keys in the publisher identity record.

## Compatibility and migration

The current EFS v1 schema accepts any non-empty publisher ID string. Tightening this to a URI profile is a compatibility-affecting semantic restriction. Before acceptance, inspect existing fixtures and any external manifests; define whether v1 adopts the stricter profile through a validator/conformance update or whether a new profile/version is required. Do not silently invalidate previously conforming manifests.

## References

- [PSI-34 canonical object model and approved decision set](https://app.notion.com/p/41af741d651181ac9488d932f13051f0)
- [PSI-35 schema implementation](https://github.com/mkrdiop/enterprise-factory-network/pull/1)
- [PSI-36 conformance implementation](https://github.com/mkrdiop/enterprise-factory-network/pull/2)
- [PSI-37 Linear issue](https://linear.app/getpsi/issue/PSI-37/define-factory-identity-and-publisher-namespace)
- `docs/semantic-validation-boundary.md`

## Change history

| Date | Change | Reason |
| --- | --- | --- |
| 2026-11-16 | Initial Proposed record | PSI-37 identity namespace review |
