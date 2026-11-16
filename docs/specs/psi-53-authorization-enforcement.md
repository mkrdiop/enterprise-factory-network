# PSI-53 — Authorization, trust and revocation enforcement

- **Status:** Normative specification proposal; pending explicit acceptance and independent review
- **Version:** 1.1.0
- **Dependencies:** PSI-37, PSI-40, PSI-45, PSI-50, PSI-51, PSI-52

## 1. Enforcement invariant
One mandatory server-side Policy Enforcement Point (PEP) guards every protected API route, job, administrative command, Runtime entry point and internal service call. UI checks are not enforcement. The PDP remains the pure, deterministic PSI-52 evaluator.

A protected operation is allowed only when the authenticated principal is established by a trusted identity boundary; every required authorization check is derived from server-side context and has an exact PSI-52 action/resource pair; every exact policy reference is digest-verified; every PDP result is `permit`; all returned obligations are fulfilled; required publisher/key trust is current; required PSI-54 lifecycle admission succeeds; consumed evidence generations remain unchanged and fresh at commit; and the applicable durable audit/intent protocol succeeds.

## 2. Authorization check-set semantics
An operation maps to an ordered, immutable set of one or more authorization checks, not necessarily one action. Each check contains exactly one PSI-52 finite action, one authoritative resource, one exact policy bundle reference and one PDP result. **Every required check MUST return permit.** A deny rejects the operation; absent deny, any indeterminate check makes the composite result indeterminate; otherwise every check must permit. No check may be omitted because another check permitted.

The PEP derives subject, action and resource coordinates from authenticated identity, route metadata and authoritative records. Client-supplied role, publisher, Factory, release or capability coordinates are not trusted. The route-to-check-set mapping is versioned and tested.

### Normative action/resource map

| Operation | Required PSI-52 checks | Exact resource coordinates |
|---|---|---|
| Publisher read/manage | `publisher.read` / `publisher.manage` | publisher; `publisher_id` |
| Publisher key management | `publisher.key.manage` | publisher; `publisher_id` |
| Factory discovery/read | `factory.discover` / `factory.read` | factory; `publisher_id`, `factory_id` |
| Factory registration | `factory.register` | prospective factory; `publisher_id`, `factory_id` |
| Release publication | `factory.publish` AND `release.publish`; additionally `factory.register` when the same request creates a new Factory | separate factory resource (`publisher_id`, `factory_id`) and release resource (`publisher_id`, `factory_id`, `release_version`) |
| Release/passport read | `release.read` | release; `publisher_id`, `factory_id`, `release_version` |
| Capability invocation | `capability.invoke` | capability; `publisher_id`, `factory_id`, `release_version`, `capability_id` |
| Lifecycle transition | exactly one of `release.suspend`, `release.deprecate`, `release.revoke`, `release.archive` matching the requested transition | exact release coordinates above |
| Policy read/manage | `registry.policy.read` / `registry.policy.manage` | registry; `registry_id` |

This table is exhaustive for PSI-52 v1. Unknown actions are rejected before PDP invocation. An action/resource type mismatch is PSI-52 invalid evaluation input and therefore produces an indeterminate, fail-closed outcome, never a policy deny or permit. PSI-53 MUST NOT extend the PSI-52 vocabulary. The implementation MUST maintain a machine-testable inventory covering HTTP routes, jobs, admin commands, Runtime adapters and internal service entry points. Every protected entry point maps to a check set and is tested for PEP invocation; unlisted protected entry points fail closed. This is a required implementation artifact, not an assertion that this specification enumerates repository-specific route paths.

## 3. PSI-52 policy evaluation and obligations
Each check pins `policy_id`, `policy_version`, `policy_profile=efs-policy-v1` and the exact JCS/SHA-256 digest. No latest-version substitution is permitted. The PEP supplies the complete PSI-52 evaluation request, including authenticated subject provenance, exact resource coordinates, finite action and trusted evaluation context. PSI-52 owns policy syntax, action vocabulary, resource compatibility, combination semantics and PDP result. PSI-53 owns check-set composition and enforcement.

Every obligation returned by every permit result is retained with its exact ID and parameters. The PEP records a fulfillment result and durable evidence reference for each obligation; a boolean success flag without evidence is insufficient for a state-changing operation. Identical obligation IDs with identical parameters are deduplicated; conflicting parameters, unsupported obligations or unfulfilled obligations reject the operation. Audit captures obligation IDs, fulfillment outcomes and evidence references, not secret values. Policy digest verification is explicit for each check; a missing/unavailable reference or digest mismatch is indeterminate and never permits.

## 4. Publisher/key trust evidence
Trust is explicit per operation: the policy/operation contract supplies the exact required signer identity set; callers cannot select it. If no signature trust is required, that set is empty and PSI-53 does not infer a signer threshold. If signers are required, each required `(publisher_id, key_id, algorithm, usage)` is checked independently against PSI-51's per-signer cryptographic result and the authoritative trust resolver. Every required signer must have a cryptographically valid PSI-51 result and fresh trust evidence bound to the exact publisher/key, algorithm and usage; evidence version is monotonic; `observed_at <= commit_time < expires_at`; and age does not exceed configured `max_evidence_age_seconds`. A missing signer, missing/unavailable evidence, invalid signature, untrusted key or revoked key fails closed with its distinct reason. PSI-50 defines no quorum, all-envelope-signers or any-one-signer aggregate; PSI-53 enforces only the exact signer identities required by policy, independently per signer.

PSI-53 implements the PSI-51 `PublisherKeyResolver.resolve(publisher_id, key_id, required_algorithm, required_usage)` seam. PSI-51 remains responsible for cryptographic verification using verifier UTC time. Signature validity, publisher/key trust, policy authorization and release lifecycle are separate decisions. Caller signing timestamps never extend key trust.

## 5. Commit-time freshness and atomicity
The positive integer `max_evidence_age_seconds` is required deployment configuration. No default is invented; production startup fails if unset. Every consumed policy, trust, authorization and lifecycle evidence generation is captured during evaluation and compared with authoritative current generations at commit. A mismatch requires re-evaluation; stale preflight permits cannot commit.

For a database-backed protected mutation, state mutation and append-only audit outbox row MUST commit in one database transaction. Outbox failure rolls back the mutation. Object-store I/O is outside that transaction.

### External side effects and PSI-45 boundary
A capability invocation or other external effect cannot be transactionally atomic with a local database. Before dispatch, the PEP/Runtime persistence adapter MUST durably commit (a) a stable operation/invocation identity and scoped idempotency key, (b) the exact release/capability coordinate, authorization decision reference and canonical payload fingerprint, (c) the audit/dispatch intent, and (d) the corresponding PSI-45 execution snapshot/event using PSI-45's schemas and atomic expected-revision compare-and-swap. A validated PSI-44 request is projected through PSI-45's `created → requested` transition before dispatch. `accepted` is only a receiver disposition; `queued` is explicitly not a durability or delivery guarantee. Neither state may be used as proof that the external effect occurred.

Dispatch occurs only after that durable local commit and uses the same stable invocation/operation identity. Completion is recorded through the PSI-45 event model and a durable audit outcome. PSI-45's pure validator does not persist, authorize, schedule, retry or guarantee delivery; its persistence adapter owns atomic revision CAS. PSI-45 event-ID replay semantics only make applying the same lifecycle event idempotent; they do not make the underlying capability side effect idempotent. A downstream retry is allowed only when the adapter has a documented idempotency guarantee for that same operation identity. Otherwise, reconcile/query the downstream outcome first and never blindly dispatch a duplicate. Unknown outcome is reported as PSI-53 `indeterminate`; it does not introduce a new PSI-45 state. If durable intent cannot be written, dispatch is forbidden.

PSI-45 remains authoritative for execution lifecycle, state vocabulary, event replay and revision semantics. PSI-53 defines only the authorization/audit gate and durable hand-off contract; it creates no competing execution state machine and promises no cross-system atomicity.

## 6. Stable enforcement reasons
`AUTHN_REQUIRED`, `ACTION_UNMAPPED`, `RESOURCE_COORDINATES_INVALID`, `INDETERMINATE_INVALID_ACTION_RESOURCE_PAIR`, `INDETERMINATE_INVALID_ACTION_RESOURCE_PAIR`, `POLICY_DENIED`, `PDP_INDETERMINATE`, `OBLIGATION_UNFULFILLED`, `TRUST_UNAVAILABLE`, `KEY_NOT_TRUSTED`, `KEY_REVOKED`, `SIGNATURE_INVALID`, `RELEASE_NOT_ADMISSIBLE`, `EVIDENCE_STALE`, `AUDIT_DURABILITY_FAILURE`, `AUTHORIZATION_REVISION_CHANGED`, `EXECUTION_INTENT_NOT_DURABLE`, `EXECUTION_OUTCOME_UNKNOWN`.

## 7. Conformance and acceptance
The v1.1 vector package exercises exact action/resource compatibility, composite all-permit semantics, deny/indeterminate composition, trust-required and trust-not-required behavior, evidence freshness, obligations, commit-generation changes and external-effect intent/outcome handling. It is a composition oracle, not a replacement for PSI-52 PDP vectors.

Implementation acceptance additionally requires exhaustive route inventory/bypass tests, PSI-45 integration tests, PostgreSQL mutation/outbox atomicity, external-effect crash/retry/reconciliation tests, property-based tests and the Python 3.11–3.13 CI matrix.
