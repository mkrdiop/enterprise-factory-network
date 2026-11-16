# ADR-004 — EFS v1 detached release-signature profile

- **Status:** Proposed — architecture decision for founder review
- **Date:** 2026-11-16
- **Owners:** EFS architecture
- **Related issues:** PSI-50, PSI-51, PSI-52, PSI-53
- **Supersedes:** None
- **Normative inputs:** ADR-001, ADR-003, EFS v1 Baseline, PSI-34

## Context

EFS v1 needs a portable signature contract for an immutable release. ADR-001 already fixes the release digest profile and explicitly excludes `release.digest` and `release.signature` from the digest projection. PSI-50 requires signatures not to mutate the immutable manifest. The signing algorithm, signed preimage, key resolution and trust boundary must be interoperable without changing the accepted digest profile.

## Decision

This ADR proposes the following v1 decisions. It is not accepted until the EFS decision owner records approval.

1. **Detached envelope.** A signature envelope is a separate immutable registry/security record associated with the exact release coordinates and digest. It is not embedded in, nor does it mutate, the canonical manifest.
2. **Reserved manifest field.** For EFS v1, `release.signature` MUST be absent from a conforming canonical manifest. ADR-001's projection rule remains unchanged and continues to exclude that reserved field for profile compatibility; its exclusion MUST NOT be interpreted as permission to carry mutable signature data in the manifest. A semantic validator MUST reject a present `release.signature` member under this v1 profile. A future in-manifest signature design requires a new profile and ADR.
3. **Digest unchanged.** The release digest remains exactly `efs-jcs-sha256-v1`: RFC 8785 JCS over `{"domain":"efs.factory-release.v1","manifest":<release-defining projection>}`, SHA-256, unpadded Base64URL. PSI-50 MUST NOT change its domain, projection, canonicalization, algorithm or encoding.
4. **Signature profile.** The initial signature profile is `efs-ed25519-jcs-v1`, using Ed25519 (RFC 8032), a 32-byte raw public key and 64-byte raw signature. Public key and signature octets are encoded as unpadded Base64URL. No algorithm negotiation, fallback or downgrade is permitted. A future FIPS-constrained profile MUST have a distinct identifier and separately approved vectors; it MUST NOT silently replace this profile.
5. **Signing statement.** Each signature covers the exact release coordinates and digest tuple, plus the signer key ID and algorithm. The preimage is ASCII `EFS-SIGNATURE-V1\n` concatenated with RFC 8785 JCS UTF-8 bytes of the signed object defined in `docs/specs/efs-v1-signature-envelope.md`.
6. **Key lookup.** Key IDs are opaque publisher-scoped identifiers. Resolution uses the exact pair `(canonical publisher.id, key_id)`. An embedded key is never trusted. Resolver results must bind the key to the publisher, algorithm, usage and authoritative trust state. URI identity processing remains local-only under ADR-003.
7. **Trust separation.** Signature mathematics, key binding, publisher namespace proof, key trust/expiry/revocation and authorization are separate outcomes. PSI-50 defines the envelope and cryptographic result; PSI-53 consumes authoritative trust evidence and makes authorization decisions. Caller-supplied signing time cannot override current revocation or expiry.
8. **Multiple signatures.** An envelope MAY contain multiple signatures. Each signature is independently verified. Duplicate `(key_id, algorithm)` entries are invalid. The envelope itself grants no quorum or threshold meaning; any required signer set is a PSI-52 policy decision.

## Consequences

- Signature records can be added without changing an immutable manifest or its digest.
- Independent implementations have one exact signing preimage and algorithm profile.
- Trust and authorization remain external and cannot be inferred from possession of a valid signature.
- Deployments requiring a FIPS-validated cryptographic module need a separately governed profile; this v1 profile does not claim FIPS validation.

## Rejected alternatives

- Embedding signature metadata in the manifest: rejected because it conflicts with immutable release semantics.
- Treating a key supplied with the envelope as trusted: rejected because an attacker could self-assert a key.
- Algorithm fallback or negotiation: rejected because it creates downgrade and implementation-divergence risk.
- Using signing-time metadata as proof of historical trust: rejected because it is not a trusted timestamp.

## References

- RFC 8032 — Edwards-Curve Digital Signature Algorithm (EdDSA)
- RFC 8785 — JSON Canonicalization Scheme
- ADR-001 — EFS v1 release digest profile
- ADR-003 — Publisher namespace and issuer/trust model
- `docs/specs/efs-v1-signature-envelope.md`
- `tests/conformance/signatures-v1.json`

## Change history

| Date | Change |
|---|---|
| 2026-11-16 | Proposed detached Ed25519/JCS v1 profile and resolved the reserved manifest signature-field ambiguity for founder review |
