# EFS v1 — Authorization Policy and Evaluation Contract

- **Status:** Draft normative specification; pending independent review and PR acceptance
- **Policy profile:** `efs-policy-v1`
- **Policy digest:** `efs-policy-jcs-sha256-v1`
- **Owner:** PSI-52
- **Normative dependencies:** EFS v1 Baseline, PSI-34, PSI-37, PSI-46–49

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT and MAY are normative.

## 1. Scope and responsibility

This specification defines one deterministic, engine-neutral authorization model for EFS publisher, Factory, release, capability, registry and execution-target operations. It defines policy documents, evaluation requests, condition semantics, combination behavior and decision results.

The evaluator is a pure function of a verified policy bundle, an authenticated subject, an exact resource/action and an explicit trusted evaluation context. It MUST NOT perform network access, read ambient process state, resolve identities, retrieve policies implicitly or infer missing attributes.

PSI-52 owns the normative policy language and pure evaluation semantics. PSI-53 owns server-side policy enforcement, trust/revocation integration, policy retrieval and freshness controls at protected operation boundaries. Authentication providers establish subject identity and claims; the policy evaluator does not authenticate callers.

## 2. Core separation

The following are separate inputs and decisions: authentication, publisher namespace ownership, key trust/revocation, signature validity, release digest integrity, authorization, lifecycle admission, compatibility and runtime execution support. A valid signature is evidence, not an authorization grant. A trusted publisher is not automatically authorized for every Factory/action. Lifecycle state is not inferred from a policy allow.

## 3. Policy profile and immutable reference

The v1 policy semantics identifier is `efs-policy-v1`. A policy document MUST declare:

- `policy_profile`: exactly `efs-policy-v1`;
- `policy_id`: stable opaque non-empty identifier;
- `policy_version`: exact non-empty opaque version string; no parsing, coercion or implicit “latest”;
- `digest`: `profile_id` = `efs-policy-jcs-sha256-v1`, `algorithm` = `sha-256`, and unpadded Base64URL digest value;
- `rules`: one or more explicit rules.

The policy digest is SHA-256 over RFC 8785 JCS UTF-8 bytes of `{"domain":"efs.policy.v1","policy":<policy projection>}`. The projection excludes only the top-level `digest` member. Duplicate JSON member names and unsupported JCS/I-JSON values MUST be rejected. A policy reference MUST pin exact `policy_id`, `policy_version`, `policy_profile` and digest tuple. A resolver MUST NOT replace an unresolved reference with a different version or “latest”.

Unsupported profile/version, digest mismatch, missing required policy, unresolved reference or unavailable required resolver is an indeterminate evaluation and MUST NOT yield permit.

## 4. Subject model and provenance

Subject types are exactly: `user`, `service_principal`, `tenant`, and `publisher_principal`. A subject has an exact, non-empty, case-sensitive `id`. Subject identity MUST be established by the authentication boundary and passed to the evaluator as authenticated evidence. An untrusted request body MUST NOT establish its own authenticated subject.

Subject attributes are typed claims with provenance. Every attribute consumed by a condition MUST be supplied in the explicit evaluation request (in the subject attribute map or context attribute map) with its trusted source, observation time and freshness bound. The evaluator MUST NOT treat caller-supplied role, tenant, publisher ownership, key trust or authentication claims as trusted merely because they appear in JSON. Trust in each source is configured outside the policy document by the enforcement environment.

A rule subject selector matches only an exact subject type and exact subject ID. No implicit groups, aliases, case folding, wildcard IDs, role expansion or parent/child subject inheritance exists in v1. Additional claims can be tested only through typed conditions over authenticated, provenance-bearing attributes.

## 5. Resource model and exact scope

Resource types are exactly:

- `publisher`
- `factory`
- `release`
- `capability`
- `registry`
- `execution_target`

A resource is supplied by the trusted Policy Enforcement Point (PEP) with exact `type`, stable non-empty `id` and a typed `coordinates` object. Coordinates, when present, use exact EFS values: `publisher_id`, `factory_id`, `release_version`, `capability_id`, `registry_id`, `execution_target_id`. For a Factory resource, publisher_id and factory_id are required; for a Release resource, publisher_id, factory_id and release_version are required; for a Capability resource, publisher_id, factory_id, release_version and capability_id are required. The PEP MUST derive these coordinates from authoritative records, not caller assertions.

Resource selectors match exact resource type and exact resource ID. Coordinates in a rule, when specified, MUST match every specified coordinate exactly. No implicit hierarchy, inheritance, aliases, display-name matching, prefix matching or wildcard expansion exists in v1. A publisher-level rule does not automatically grant access to its Factories or releases. Any future hierarchical scope requires a new policy profile/version and explicit migration.

## 6. Finite action vocabulary

The only v1 actions are:

- `publisher.read`
- `publisher.manage`
- `factory.discover`
- `factory.read`
- `factory.register`
- `factory.publish`
- `release.read`
- `release.publish`
- `capability.invoke`
- `registry.policy.read`
- `registry.policy.manage`
- `publisher.key.manage`
- `release.suspend`
- `release.deprecate`
- `release.revoke`
- `release.archive`

Unknown actions MUST be rejected before evaluation. The PEP MUST validate action/resource compatibility:

| Action | Permitted resource types |
|---|---|
| publisher.read, publisher.manage, publisher.key.manage | publisher |
| factory.discover, factory.read, factory.register, factory.publish | factory |
| release.read, release.publish, release.suspend, release.deprecate, release.revoke, release.archive | release |
| capability.invoke | capability |
| registry.policy.read, registry.policy.manage | registry |

An action/resource mismatch is invalid input and MUST return indeterminate (never permit). The vocabulary is finite; broad verbs such as `admin`, `write`, `manage-all` and wildcard actions are not defined.

## 7. Condition language

Conditions are JSON abstract-syntax trees, not source code. The v1 profile has fixed engine-neutral resource limits: maximum depth 16 (root condition is depth 1), maximum 256 condition nodes, maximum 32 children for each `all`/`any`, maximum 64 values in an `in` literal array, and maximum 1,024 Unicode scalar values in any string literal. A condition exceeding any limit MUST be rejected as invalid policy before evaluation; implementations MUST NOT publish different v1 limits. Implementations MAY enforce stricter operational request-size limits, but MUST report resource exhaustion as indeterminate and MUST NOT evaluate a truncated condition. Conditions MUST be acyclic and MUST NOT execute scripts, templates, regular expressions, dynamic property access, arbitrary functions or I/O.

Attribute references are exactly `subject.attributes.<name>`, `resource.coordinates.<name>` or `context.attributes.<name>`. Attribute names are exact case-sensitive strings. The only operators are:

- `all`: every child condition is true;
- `any`: at least one child condition is true;
- `not`: logical negation of one child condition;
- `exists`: whether a trusted attribute exists and is fresh;
- `eq`: exact typed equality;
- `in`: exact typed membership in a non-empty literal array;
- `gt`, `gte`, `lt`, `lte`: numeric comparison only.

There is no implicit type coercion. Equality requires the same JSON scalar type. Strings compare by exact Unicode scalar sequence, without normalization or case folding. Numeric operators accept JSON numbers only; NaN and infinities are not valid JSON values. Boolean values support equality only. Arrays/objects are not valid condition literals. A missing attribute referenced by `eq`, `in` or a comparison operator produces an indeterminate condition. For `exists`, an absent attribute evaluates false; a present but stale, malformed or untrusted attribute evaluates indeterminate. An unavailable attribute source produces indeterminate. A condition that is well-formed and evaluates false makes its rule not applicable; an evaluation error makes the rule indeterminate. Three-valued composition is deterministic: `all` is false if any child is false, otherwise indeterminate if any child is indeterminate, otherwise true; `any` is true if any child is true, otherwise indeterminate if any child is indeterminate, otherwise false; `not` preserves indeterminate and inverts true/false. The `exists` operator returns false when the named attribute is absent, indeterminate when a supplied attribute is stale or its source is untrusted, and true only when the attribute is present and fresh.

## 8. Evaluation request and trusted context

Every evaluation request MUST include:

- authenticated `subject`;
- authoritative `resource`;
- one finite `action`;
- explicit `context.evaluation_time` from a trusted clock;
- explicit `context.attributes`, each with value, source identifier, observed_at and expires_at;
- a verified, immutable policy bundle, including every policy required by the operation.

The evaluator MUST NOT obtain missing context implicitly. The PEP supplies source identifiers and verifies them against configured trusted issuers. An attribute is fresh only when its source is trusted, its observation time is not in the future relative to evaluation_time, and evaluation_time is strictly earlier than expires_at; equality with expires_at is stale. Every timestamp MUST be RFC 3339 date-time, and schema validators MUST assert the `date-time` format using an enabled format checker rather than treating `format` as an annotation. A source-specific maximum age MAY impose a stricter bound; it MUST NOT extend expires_at. Missing or invalid freshness metadata makes the attribute indeterminate when referenced.

## 9. Rule semantics and deterministic policy combination

A rule contains a unique `rule_id` within its policy document (duplicate identifiers make the policy invalid), effect (`permit` or `deny`), exact subject selector, exact resource selector, one or more finite actions, optional condition and optional obligations.

A rule is:
- **not applicable** when subject, resource or action selectors do not match, or its valid condition evaluates false;
- **permit** when all selectors match and its condition is true (or absent), and effect is permit;
- **deny** when all selectors match and its condition is true (or absent), and effect is deny;
- **indeterminate** when required input, attribute, policy or condition evaluation is invalid or unavailable.

The combining algorithm is **deny-overrides with indeterminate-overrides-permit** and is order-independent:

1. If any applicable rule produces deny, the final decision is `deny`.
2. Otherwise, if any applicable rule or required policy input is indeterminate, the final decision is `indeterminate`.
3. Otherwise, if one or more applicable permit rules exist, the final decision is `permit`.
4. Otherwise (including no applicable rule or no applicable policy), the final decision is `deny`.

An explicit deny takes precedence over permit. Indeterminate never permits. Policy/rule order MUST NOT affect the decision. Policy documents required by the protected operation are combined as one bundle using the same algorithm. The PEP MUST identify the required policy set; the evaluator MUST NOT guess it.

Obligations from all applicable permit rules are combined as a set keyed by obligation id. Identical duplicates are deduplicated. The same obligation id with conflicting parameters makes the decision indeterminate. A PEP MUST execute every returned obligation before performing the protected operation. If an obligation is unsupported, cannot be fulfilled or fails, the operation MUST be denied and MUST NOT proceed. A policy engine MUST NOT silently discard an obligation.

## 10. Decision response and reason codes

A response contains `decision` (`permit`, `deny`, `indeterminate`), stable `reason_codes`, exact subject/resource/action coordinates, evaluated policy IDs/versions/digests, matched rule IDs and obligations. Reason codes are machine-stable identifiers, not localized prose. At minimum:

- `PERMIT_RULE_MATCHED`
- `DENY_RULE_MATCHED`
- `DEFAULT_DENY_NO_APPLICABLE_PERMIT`
- `INDETERMINATE_MISSING_ATTRIBUTE`
- `INDETERMINATE_STALE_ATTRIBUTE`
- `INDETERMINATE_UNTRUSTED_ATTRIBUTE_SOURCE`
- `INDETERMINATE_POLICY_UNAVAILABLE`
- `INDETERMINATE_POLICY_VERSION_UNSUPPORTED`
- `INDETERMINATE_POLICY_DIGEST_MISMATCH`
- `INDETERMINATE_CONDITION_TYPE_MISMATCH`
- `INDETERMINATE_OBLIGATION_CONFLICT`
- `INDETERMINATE_UNSUPPORTED_OBLIGATION`
- `INDETERMINATE_INVALID_ACTION_RESOURCE_PAIR`

A response MUST NOT expose secrets or sensitive attribute values in diagnostics. It SHOULD expose stable policy/rule provenance sufficient for audit, subject to authorization to read policy internals. A `permit` response with obligations is not permission to skip PEP obligation execution.

## 11. Enforcement and audit boundary

The evaluator is a pure Policy Decision Point (PDP). PSI-53 implements PEP enforcement at every protected server-side registry and runtime operation. UI-only enforcement is non-conformant. Every publish, register, key/policy administration, lifecycle transition and capability invocation path MUST have an identified PEP and an auditable decision record. A PEP MUST fail closed on PDP timeout, invalid response, missing required policy, stale trust evidence or unfulfilled obligation.

PSI-53 MUST NOT redefine policy syntax, combination semantics, action vocabulary or condition semantics. It consumes this profile and enforces its result.

## 12. Security and conformance

The machine-readable schema is `schemas/efs-policy-v1.schema.json`. The independently validated vector package is `tests/conformance/policy-v1.json`, described by `tests/conformance/policy-v1.schema.json`. CI MUST validate both Draft 2020-12 schemas, apply the policy schema with RFC 3339 `FormatChecker`, validate the complete vector package and every vector record, recompute the `pol-kat-001` JCS/SHA-256 known-answer vector, and execute the policy-structure semantic checks. The package includes explicit negative vectors for every invalid action/resource pair, wildcard identifiers, missing resource coordinates, duplicate rule IDs, AST bounds, malformed timestamps and the exact freshness boundary. Implementations MUST pass all applicable normative vectors before claiming `efs-policy-v1` conformance. These contract-validation tests do not claim to implement a PDP; independent PDP implementations consume the language-neutral vectors as their behavioral oracle.

## 13. References

- EFS v1 Requirements Baseline — EFS-GOV-001/002/003 and EFS-MAN-007
- PSI-34 — canonical Factory Manifest and immutable digest-pinned policy references
- PSI-37 — publisher/Factory identity
- PSI-46–49 — exact version dimensions and compatibility
- ADR-001 — release digest profile (not reused for policy documents)
- `docs/adr/ADR-005-efs-v1-policy-combination-and-digest.md` (Proposed)


## 12.1 Conformance-vector package contract

The machine-readable package at `tests/conformance/policy-v1.json` is a normative, independently consumable test oracle. Each validation vector MUST be self-contained: an action/resource compatibility vector contains a complete `evaluation_request` (subject, authoritative resource coordinates, action, trusted context and at least one policy), not an informal pair that requires an implementation to guess how to construct a request. The expected result is the closed object `{ "classification": "invalid-input", "reason_code": "INVALID_ACTION_RESOURCE_COMBINATION" }`.

A semantic-policy vector MUST declare the exact semantic-invalid classification and reason code. Duplicate `rule_id` values produce `{ "classification": "semantic-invalid", "reason_code": "DUPLICATE_RULE_ID" }`; JSON Schema validation alone is not sufficient to establish uniqueness across array items.

The vector-package schema MUST use a closed, kind-discriminated shape for every validation-vector kind. Each kind has its own required fields and expected-result vocabulary; unknown fields, missing payloads and incompatible expected values are invalid package data. A conforming implementation MUST execute every vector according to its declared kind and compare the observed classification/reason code with `expected`. The repository's contract tests validate the vector package and the normative validation rules; they do not purport to implement the full policy decision point.
