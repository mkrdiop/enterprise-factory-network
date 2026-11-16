# ADR-005 — EFS v1 policy combination and content digest

- **Status:** Proposed — architecture decision for founder review
- **Date:** 2026-11-16
- **Owner:** EFS architecture
- **Related issue:** PSI-52
- **Normative dependencies:** PSI-34, EFS v1 Baseline

## Context

PSI-34 requires immutable, digest-pinned policy references, but the policy document digest and cross-policy combination semantics were not yet defined. A deterministic authorization profile needs one stable content digest and one fail-closed combining algorithm.

## Decision

This ADR proposes:

1. **Policy profile:** `efs-policy-v1`.
2. **Policy content digest:** `efs-policy-jcs-sha256-v1`, defined as SHA-256 over RFC 8785 JCS UTF-8 bytes of `{"domain":"efs.policy.v1","policy":<policy projection>}`, excluding only the policy's top-level `digest` member. This is a separate object profile and does not reuse or alter ADR-001's release digest profile.
3. **Immutable references:** every policy reference pins exact policy ID, opaque policy version, profile ID and digest. No “latest” fallback.
4. **Combining algorithm:** deny-overrides with indeterminate-overrides-permit. Any applicable deny yields deny; otherwise any indeterminate yields indeterminate; otherwise at least one permit yields permit; otherwise deny. The result is independent of policy order.
5. **Obligations:** all obligations from applicable permit rules are accumulated; duplicate identical obligations are deduplicated; same ID with differing parameters yields indeterminate. PEP must fulfill all obligations before executing the protected operation.
6. **Scope:** exact subject type/ID, exact resource type/ID and finite action vocabulary; no implicit inheritance, aliases, wildcard expansion or display-name matching in v1.

## Consequences

- Multiple policy documents can be evaluated consistently by independent PDPs.
- No applicable policy, missing required policy or indeterminate evaluation cannot grant access.
- Policy digest references remain immutable and distinct from release digest identity.
- Broad hierarchical authorization requires a future profile and explicit migration.

## References

- EFS v1 Requirements Baseline — EFS-GOV-001/002/003
- PSI-34 canonical object model
- `docs/specs/efs-v1-authorization-policy.md`
- `schemas/efs-policy-v1.schema.json`
- `tests/conformance/policy-v1.json`

## Change history

| Date | Change |
|---|---|
| 2026-11-16 | Proposed policy digest profile, deterministic combining algorithm and exact-scope semantics |
