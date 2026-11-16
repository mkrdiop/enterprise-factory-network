# EFS v1 semantic validation boundary — PSI-36 handoff

Rules requiring semantic conformance tests:
- `publisher.id` is an absolute RFC 3986 URI satisfying `efs-uri-c14n-1`; input must already be canonical, and validation performs no dereferencing, DNS lookup or network access.
- Publisher identity is distinct from namespace-ownership proof, issuer authentication, signing-key identity, trust and authorization. Publisher and Factory identities are immutable; retired identifiers are tombstoned and never reassigned.
- Factory identity is the exact pair `(canonical publisher.id, factory.id)`; `factory.id` is opaque and case-sensitive.
- (publisher.id, factory.id) is the stable logical Factory identity pair.
- Capability IDs are unique; endpoint IDs are unique within each capability.
- Execution profile IDs are unique; capability profile references resolve to root profiles.
- Dependency IDs are unique; target shape and version-constraint grammar follow the approved identity/dependency profile.
- Policy declaration/reference IDs and profile semantics follow governed policy profiles; mandatory sources resolve and verify before protected action.
- Contract $ref targets resolve only within the bundled immutable release package or local resource graph; no ambient network fetch.
- Embedded input/output/error schemas validate under Draft 2020-12 and the EFS conformance profile.
- JCS digest recomputation uses the approved domain-separated envelope and excludes only release.digest and release.signature; duplicate JSON member names and out-of-profile I-JSON values are rejected.
- Signature verification and publisher trust are separate from digest integrity.
- Extensions cannot redefine core semantics; exact namespace and unknown-field policy remains pending.
- Structural validity does not prove dependency availability, runtime support, policy approval, trust or compatibility.
