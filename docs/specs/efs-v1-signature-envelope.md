# EFS v1 — Detached Release Signature Envelope

- **Status:** Draft normative specification; pending independent review and PR acceptance
- **Profile:** `efs-ed25519-jcs-v1`
- **Owner:** PSI-50
- **Related ADR:** ADR-004 (Accepted)
- **Normative dependencies:** EFS v1 Baseline, PSI-34, PSI-37, PSI-40, ADR-001, ADR-003

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT and MAY are normative.

## 1. Scope and separation

This specification defines a detached signature envelope for one immutable EFS Factory Release. It defines serialization, signed bytes, cryptographic verification and the boundary to external trust decisions. It does not define key custody, publisher onboarding, namespace proof, trust-root governance, authorization, revocation propagation or lifecycle transitions.

A signature proves only that the holder of the corresponding private key produced a valid signature over the specified statement. It does not by itself prove that the key is trusted, that the signer controls the publisher namespace, or that the signer is authorized to publish, suspend or revoke a release.

## 2. Normative profile

The v1 profile identifier is `efs-ed25519-jcs-v1`.

- Signature algorithm: Ed25519 as specified by RFC 8032.
- Public key: exactly 32 raw octets.
- Signature: exactly 64 raw octets.
- Text encoding of public key and signature: canonical unpadded Base64URL (RFC 4648 §5), decoded length exactly 32 and 64 octets respectively, and re-encoding the decoded octets MUST reproduce the input byte-for-byte. Padding, non-URL alphabet characters, invalid lengths and non-zero unused pad bits MUST be rejected.
- Signed-object canonicalization: RFC 8785 JCS.
- Signed-message prefix: the exact ASCII octets `EFS-SIGNATURE-V1\n`.
- No algorithm fallback, negotiation, implicit parameter defaults or downgrade is permitted.
- Unknown profile or algorithm identifiers MUST produce an unsupported-profile/algorithm result and MUST NOT fall back to another verifier.

A deployment requiring a FIPS-validated algorithm/module MUST use a separately named and approved profile. Implementations MUST NOT relabel or silently substitute another algorithm under this profile.

## 3. Detached placement and digest compatibility

The signature envelope is stored as a separate immutable record associated with the release. It MUST NOT be inserted into or mutate the canonical manifest.

The canonical manifest MUST NOT contain `release.signature` under EFS v1. The member is reserved and MUST be rejected structurally by the normative manifest schema and by semantic validation if present. The manifest schema represents this prohibition as a forbidden property at `/release/signature`; the conformance diagnostic is `EFS_SCHEMA_CONSTRAINT` at that exact JSON Pointer. The PSI-51 implementation MUST preserve this rejection in the reference validator and release-admission pipeline. PSI-50 owns the normative prohibition and schema/vector; PSI-51 owns implementation integration and executable validator/admission tests. PSI-51 MUST NOT begin until PSI-50 acceptance. ADR-001's accepted digest projection continues to exclude both `release.digest` and `release.signature`; this profile does not change that definition. The exclusion of the reserved field is a digest-profile compatibility rule, not permission to place mutable signature material in the manifest.

The manifest's release digest MUST be independently verified under `efs-jcs-sha256-v1` before signature verification. The signature envelope binds the exact digest profile, digest algorithm and digest value. Implementations MUST NOT calculate a second release digest or reinterpret the existing profile.

## 4. Envelope data model

The envelope JSON object has exactly these top-level properties:

- `envelope_version`: string, exactly `1`.
- `profile_id`: string, exactly `efs-ed25519-jcs-v1`.
- `statement`: the release identity and digest statement.
- `signatures`: non-empty array of independent signer entries.

The statement has exactly:

- `purpose`: `efs.release.signature.v1`.
- `publisher_id`: the exact canonical absolute URI from the manifest, validated under `efs-uri-c14n-1`. Validation MUST apply the complete ADR-003 profile (absolute RFC 3986 ASCII URI; lowercase scheme and host; no query, fragment or userinfo; canonical percent-encoding; dot-segment removal; preserve all other components exactly). Generic JSON Schema `format: uri` is only a structural check and is not sufficient.
- `factory_id`: exact decoded JSON string from the manifest; case-sensitive, with no normalization.
- `release_version`: exact release version string from the immutable manifest; opaque and not parsed or normalized by this profile.
- `efs_version`: exact EFS version string from the manifest.
- `digest`: object with `profile_id` = `efs-jcs-sha256-v1`, `algorithm` = `SHA-256`, and `value` equal to the verified unpadded Base64URL SHA-256 digest. The algorithm token is exactly `SHA-256` (uppercase), matching ADR-001 and PSI-40; the lowercase spelling `sha-256` is invalid.

Each signer entry has exactly:

- `key_id`: opaque publisher-scoped identifier matching `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`.
- `algorithm`: exactly `Ed25519`.
- `signature`: unpadded Base64URL encoding of exactly 64 octets.

The envelope MUST reject unknown properties in these objects. It MUST reject duplicate `(key_id, algorithm)` entries. Negative-vector expected failure codes are stable conformance identifiers: `EFS_SIGNATURE_BINDING_MISMATCH`, `EFS_SIGNATURE_INVALID`, `EFS_SIGNATURE_ENCODING_INVALID`, `EFS_SIGNATURE_DUPLICATE_SIGNER`, `EFS_SIGNATURE_UNSUPPORTED_PROFILE`, `EFS_SIGNATURE_KEY_NOT_TRUSTED`, `EFS_SIGNATURE_KEY_BINDING_MISMATCH`, `EFS_SIGNATURE_KEY_REVOKED`, `EFS_SIGNATURE_KEY_EXPIRED`, `EFS_SIGNATURE_RESOLVER_UNAVAILABLE`, `EFS_SIGNATURE_KEY_NOT_FOUND`, `EFS_SCHEMA_CONSTRAINT` and `EFS_SIGNATURE_DIGEST_PROFILE_MISMATCH`. Signature-array order has no semantic meaning and MUST NOT change the verification result. Producers SHOULD sort entries by key_id using ordinal ASCII order for stable storage.

The envelope MUST NOT contain public keys, private keys, credentials, trust claims, authorization claims, caller-controlled trust status or a timestamp that is treated as authoritative.

## 5. Exact signing input

For each signer entry, construct the following JSON object:

```json
{
  "domain": "efs.release.signature.v1",
  "signer": {
    "algorithm": "Ed25519",
    "key_id": "<exact key_id>"
  },
  "statement": {
    "purpose": "efs.release.signature.v1",
    "publisher_id": "<exact canonical publisher URI>",
    "factory_id": "<exact factory id>",
    "release_version": "<exact release version>",
    "efs_version": "<exact EFS version>",
    "digest": {
      "profile_id": "efs-jcs-sha256-v1",
      "algorithm": "SHA-256",
      "value": "<verified digest value>"
    }
  }
}
```

The signed-message bytes are exactly:

```text
ASCII("EFS-SIGNATURE-V1\n") || UTF8(RFC8785_JCS(signed_object))
```

There is no trailing newline after the JCS bytes. No BOM, whitespace, NUL terminator, Unicode normalization, URI rewrite, number conversion, or alternate JSON serializer is permitted. All fields shown above are strings except the JSON object structure. The signed object MUST be reconstructed from the immutable manifest and envelope; it MUST NOT be accepted as an independently supplied opaque byte string.

The verifier MUST compare each statement coordinate to the manifest using the exact comparison rules of EFS v1 and ADR-003 before accepting cryptographic verification. Any mismatch is a binding failure, even if a signature over the mismatching statement is mathematically valid.

## 6. Verification sequence and outcomes

A conforming verifier performs these steps in order:

1. Parse JSON while rejecting duplicate member names, invalid UTF-8, unsupported I-JSON/JCS inputs and unknown properties.
2. Validate the envelope against the v1 schema and reject duplicate signer entries.
3. Validate the manifest identity fields and ensure `release.signature` is absent.
4. Recompute and verify the release digest using the unchanged `efs-jcs-sha256-v1` profile.
5. Compare the envelope statement to exact manifest coordinates and the verified digest tuple.
6. Reconstruct the signed object and exact preimage independently for each signer.
7. Resolve the public key through the explicit trusted key-resolver interface using exactly `(publisher_id, key_id)`; never trust a key embedded in the envelope.
8. Verify the Ed25519 signature using the resolved 32-byte public key.
9. Return cryptographic verification evidence separately from key/publisher trust and authorization decisions.

The implementation MUST expose stable typed outcomes at least for: malformed envelope, unsupported profile/algorithm, digest mismatch, release-coordinate binding mismatch, duplicate signer, invalid signature, key not found, key binding mismatch, key not trusted, key expired, key revoked and resolver unavailable. A caller MUST NOT collapse these outcomes into a generic trusted/valid boolean.

Cryptographic verification may be reported as valid even when the key resolver reports untrusted, expired or revoked; those are separate dimensions. The final release-admission decision MUST fail closed if required trust evidence is missing, stale, unavailable or negative. PSI-53 owns policy decisions and PSI-53's authoritative trust-state integration; PSI-50 owns the signed evidence format and cryptographic result taxonomy.

## 7. Key resolver interface contract

The resolver is an explicit dependency injected by the caller. Parsing, schema validation, publisher URI canonicalization and ordinary identity comparison MUST NOT perform network access.

Input:

```json
{
  "publisher_id": "urn:example:publishers:acme",
  "key_id": "release-2026-01",
  "required_algorithm": "Ed25519",
  "required_usage": "efs-release-signing"
}
```

A successful result MUST bind all of the following: exact canonical publisher_id, exact key_id, algorithm, 32-byte public key, permitted usage, authoritative trust state, validity interval and resolver evidence/version. The resolver MUST distinguish not-found, publisher/key binding mismatch, not-trusted, expired, revoked and unavailable. Resolver results are trusted only when returned by the configured authoritative trust provider; envelope-supplied fields cannot override them.

Key IDs are unique only within a publisher namespace. They are opaque, case-sensitive ASCII identifiers and MUST NOT be dereferenced as URLs. Key rotation creates a new key_id or a separately governed key version; a key_id MUST NOT be rebound to different key material. A key revoked now MUST NOT be made trusted by a caller-supplied signing timestamp. Historical verification requires a separately governed trusted timestamp/evidence profile, which is out of scope for v1.

## 8. Multiple signatures

An envelope may carry one or more signatures. Each signature is verified independently against the same release statement. Duplicate key IDs are invalid within one envelope. The envelope makes no threshold, quorum, ordering or “any one signer authorizes publication” assertion. The policy layer determines which trusted signer identities, if any, are required for an action. If any required signature is invalid or unavailable, the consuming policy/enforcement path MUST fail closed.

## 9. Security requirements

Implementations MUST test and reject:

- publisher, Factory ID, release version, EFS version, digest profile or digest value substitution;
- replay of a signature against another Factory or release;
- key substitution across publisher namespaces;
- altered key_id or algorithm;
- altered signature bytes, truncated or overlong key/signature encodings;
- padded or non-Base64URL encodings;
- duplicate JSON member names or duplicate signer entries;
- unknown profile/algorithm and downgrade attempts;
- embedded-key self-trust;
- expired/revoked/untrusted keys and resolver outage;
- non-canonical publisher URI and a present `release.signature` manifest member.

No signature result may be used as an authorization grant. No signature envelope may contain secrets or private keys.

## 10. Conformance

The language-neutral machine-readable vectors are in `tests/conformance/signatures-v1.json`. They include a deterministic Ed25519 known-answer vector, exact JCS preimage, canonical Base64URL boundary vectors, publisher URI canonicalization vectors, RFC 6902 JSON Patch negative mutation cases with deterministic expected failure categories, and RFC 8785 edge vectors for number serialization, UTF-16 property ordering, escaping and invalid I-JSON strings/numbers. Each negative vector names its base fixture, target document, executable patch and expected failure code. The detached-manifest negative fixture is `tests/conformance/fixtures/psi50-manifest-signature-forbidden-v1.json`. The independent Node verifier MUST implement the RFC 8785 constraints exercised by the edge vectors; a local key-sort-only approximation is not conformant. `tests/conformance/fixtures/psi50-release-interoperability-v1.json` binds a complete EFS manifest to its detached envelope and expected digest/preimage. `tests/conformance/verify_psi50_interop.mjs` independently verifies that fixture using Node.js built-in SHA-256 and Ed25519 APIs; it is intentionally independent of the Python reference KAT generation. Implementations MUST run the vectors and full fixture before claiming conformance. The vector's public/private test key material is synthetic and MUST NOT be used outside testing.

## 11. References

- RFC 8032 — Ed25519
- RFC 8785 — JSON Canonicalization Scheme
- RFC 4648 §5 — Base64URL
- ADR-001 — EFS v1 release digest profile
- ADR-003 — Publisher namespace and issuer/trust model
- ADR-004 — EFS v1 detached release-signature profile (Accepted)
