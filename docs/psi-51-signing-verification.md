# PSI-51 — Release signing and verification reference implementation

## Scope

This package implements the EFS v1 detached-signature profile accepted by PSI-50. It does not implement publisher onboarding, private-key custody, key rotation approval, policy evaluation, authorization grants, revocation propagation or lifecycle transitions. Those remain external trust/policy responsibilities (notably PSI-53).

## Public interface

- registry.signatures provides Ed25519Signer, an adapter for a provisioned Ed25519 private key. A raw 32-byte seed can be supplied only through the explicit from_private_bytes constructor; callers remain responsible for secure custody.
- create_signature_envelope(manifest_bytes, key_id, signer) verifies the existing EFS release digest, reconstructs exact release coordinates and returns a detached envelope.
- serialize_signature_envelope(envelope) schema-validates and RFC 8785 serializes the envelope.
- PublisherKeyResolver is an injected resolver contract keyed by the exact (publisher_id, key_id) tuple.
- EFSReleaseSignatureVerifier / ReleaseSignatureVerifier provide a transport-neutral verifier interface for Registry, Connect and Runtime.
- SignatureVerificationReport exposes digest validity, an envelope-processing outcome and an ordered tuple of independent per-signer cryptographic/trust outcomes.

## Verification order

1. Strict UTF-8 JSON parsing rejects duplicate member names and non-JSON constants.
2. The existing efs-jcs-sha256-v1 digest is recomputed and checked without changing its projection or encoding.
3. The reserved release.signature member is rejected.
4. The detached envelope is validated against schemas/efs-signature-envelope-v1.schema.json.
5. The envelope statement is compared to the exact publisher, Factory, release, EFS and verified digest coordinates.
6. The signed message is reconstructed as ASCII("EFS-SIGNATURE-V1\\n") concatenated with UTF8(RFC8785_JCS(signed_object)).
7. The configured resolver is called with exactly (publisher_id, key_id), algorithm Ed25519 and usage efs-release-signing.
8. Ed25519 is verified with the resolved raw 32-byte public key.

The verifier never fetches a URI, discovers a key, trusts envelope-supplied key material, falls back to another algorithm or evaluates policy. Resolver exceptions and malformed resolver responses fail closed.

## Typed results and security boundary

Stable outcomes include digest mismatch/profile mismatch, malformed envelope/encoding, unsupported profile/algorithm, binding mismatch, duplicate signer, invalid signature, key not found, key binding mismatch, untrusted/expired/revoked key and resolver unavailable.

Each SignerVerification entry carries its own cryptographic_valid value, trust_status and typed code. The report-level EVALUATED code means every envelope entry was processed; it does not aggregate signer success or select an authorization threshold. all_signers_cryptographically_valid and all_keys_trusted are explicitly diagnostic universal aggregates only, not authorization decisions. PSI-50 assigns no quorum, ordering or any-one-signer semantics; PSI-52/53 and the consuming policy determine which trusted signer identities are required. A resolver response marked trusted is rejected when its authoritative validity interval has not started or has already ended at verification time. The verifier uses its own UTC evaluation time, never the caller-supplied signing timestamp, for this consistency check.

The implementation is intentionally transport-neutral and contains no database-backed key store. A PSI-53 resolver can be injected without changing signing-input construction or cryptographic verification.

## Tests

tests/test_signatures.py covers the PSI-50 known-answer preimage/signature vector, deterministic Ed25519 signing, tampering, statement binding, malformed encodings, duplicate signers and JSON members, unsupported algorithms/profiles, publisher-scoped key substitution, resolver outages and trust-state separation. The existing manifest validator already rejects the reserved release.signature field with EFS_SCHEMA_CONSTRAINT at /release; Registry publication invokes that validator before reserving a publication operation.

Run: python -m pytest tests/test_signatures.py tests/test_schema.py -q
