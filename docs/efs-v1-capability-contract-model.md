# EFS v1 Capability and Contract Model

**Status:** Normative model for EFS v1; implementation baseline for PSI-43 and PSI-44  
**Owner:** Enterprise Factory Network (shared EFS reference definition)  
**Related work:** PSI-34, PSI-35, PSI-36, PSI-42, PSI-43, PSI-44, PSI-45  
**Affected products:** Factory Studio, Factory Connect, Factory Runtime, Enterprise Factory Network

## 1. Purpose and authority

This document defines the normative meaning and identity boundaries of EFS v1 capabilities and capability contracts. It refines, but does not replace, the approved EFS v1 canonical Factory Manifest object model (PSI-34), the Draft 2020-12 manifest schema (PSI-35), or the conformance baseline (PSI-36).

The manifest schema and this model are the single shared authority. The Enterprise Factory Network repository hosts the reference schema, validator, diagnostics, fixtures and conformance tests. Factory Studio, Factory Connect and Factory Runtime MUST consume the same definitions and conformance requirements. No product may introduce a competing capability identifier, contract identifier, version, error, payload-schema or guarantee vocabulary.

Normative terms MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are used as requirements.

## 2. Capability identity

A capability is a named, invocable or otherwise interactable function exposed by one Factory release.

- `capability.id` MUST be a non-empty string and MUST be unique within the exact Factory release manifest.
- Capability identifier comparison is exact and case-sensitive. No case folding, Unicode normalization, URI normalization, trimming, aliasing or publisher-identity canonicalization is performed.
- The scope of a capability identifier is the exact publisher / Factory / release coordinate selected from the registry. A capability identifier alone is not globally unique and MUST NOT be used as a global lookup key.
- `capability.name` is descriptive display text and MUST NOT be used as identity.
- EFS v1 does not assert that a capability identifier is stable across different Factory releases. Cross-release continuity and compatibility are separate assessments; consumers MUST NOT infer them from matching strings.
- Two capabilities in one release MUST NOT share the same `capability.id`, even if their names, endpoints or contracts differ.

The canonical Factory identity remains the exact pair `(publisher.id, factory.id)` under ADR-003. The release coordinate is the exact opaque `release.version` within that Factory identity. Capability identity is scoped below that release. No capability rule modifies publisher or Factory identity.

## 3. Contract identity and version

Every capability declares one `contract` object.

### 3.1 Contract identifier

- `contract.id` MUST be an absolute URI, as structurally constrained by the EFS v1 manifest schema.
- It is an opaque identifier, not a retrieval URL. Implementations MUST NOT dereference it, resolve DNS, follow redirects, perform key discovery, or fetch a schema/document from it.
- The URI MUST NOT be interpreted as a publisher identifier and MUST NOT be passed through the publisher-specific `efs-uri-c14n-1` profile.
- Contract identifier comparison is exact string comparison. EFS v1 does not define URI normalization, alias resolution, redirects, ownership proof or identity transfer for contract IDs.
- The contract ID is independent of endpoint addresses, hosting locations, protocol names, publisher IDs, Factory IDs and implementation builds.

### 3.2 Contract version

- `contract.version` MUST be a non-empty opaque string.
- It is independently governed from `efsVersion`, `release.version`, implementation/build versions, endpoint versions and execution-profile versions.
- EFS v1 does not parse it as Semantic Versioning, compare precedence, negotiate it, or infer compatibility.
- Version comparison is exact and case-sensitive at this layer. No normalization or implicit default is permitted.

The portable contract coordinate is the exact pair `(contract.id, contract.version)`. It identifies the contract definition independently of a particular Factory release. An invocation nevertheless MUST bind to an exact immutable Factory release and the capability declared in that release; a consumer MUST NOT resolve a contract by searching for a matching ID or silently selecting a newer version.

A change that alters the meaning of an existing error code or the interpretation of an existing input/output field MUST NOT be hidden behind the same contract version. EFS v1 does not prescribe a compatibility or version-increment policy; M4 owns compatibility assessment and PSI-43 validates only the normative structural and semantic invariants.

## 4. Input and output payload schemas

- `contract.schemaDialect` MUST equal `https://json-schema.org/draft/2020-12/schema`.
- `contract.inputs` and `contract.outputs` MUST each be complete JSON Schema Draft 2020-12 schema resources.
- Both schemas MUST declare top-level `"type": "object"`. The payload instance at these boundaries MUST therefore be a JSON object.
- The input schema describes the JSON value supplied to the capability. The output schema describes the JSON value produced by a successful capability result.
- The schemas are part of the immutable manifest/release artifact and are interpreted under the EFS v1 reference profile. They are not fetched by resolving `contract.id`.
- Schema references MUST be local to the immutable schema resource graph supplied with the release. Absolute/network references, remote retrieval, DNS, redirects and ambient schema registries are prohibited. Unsupported or unresolved references MUST fail deterministically; they MUST NOT be silently ignored.
- A consumer MUST validate against the schema belonging to the exact selected release, capability and contract version. It MUST NOT use an unpinned “latest” schema.
- Schema validity, payload validity, release digest verification, publisher trust, policy authorization and runtime admission are distinct claims.

The EFS v1 local-reference profile is intentionally conservative. PSI-43 implements and tests the exact supported subset, including deterministic behavior for local references and rejection of unsupported or unresolved references. A schema resource graph is immutable input to validation; it is not permission to retrieve arbitrary resources.

## 5. Declared errors

The required `contract.errors` array declares the capability's machine-readable error outcomes. An empty array is valid and means that the contract declares no capability-specific errors; absence of the property is not valid under the EFS v1 manifest schema.

Each error declaration MUST contain:

- `code`: a stable, machine-readable ASCII identifier matching `^[A-Za-z][A-Za-z0-9._-]{0,127}$`;
- `description`: human-readable explanatory text;
- optional `schema`: a Draft 2020-12 schema resource for structured error details.

Error-code comparison is exact and case-sensitive. Codes MUST be unique within one contract definition; duplicate codes are invalid even if descriptions or payload schemas differ. A code MUST NOT be reused for a different meaning within the same contract version. Consumers MUST branch on the code, not on localized description text.

An optional error `schema` MUST be a valid Draft 2020-12 schema with top-level `"type": "object"`. It describes structured details for that declared error. It follows the same immutable local-reference restrictions as input/output schemas. The error code remains the discriminator; the details schema does not replace it.

EFS v1 does not invent universal error codes or map native exception names into EFS codes. A product adapter MUST preserve a declared code when it can make a conformant mapping. If it cannot, it MUST report the mapping as unsupported or lossy; it MUST NOT silently fabricate a supposedly equivalent EFS error.

## 6. Guarantees and constraints

The optional `contract.guarantees` object carries governed machine-readable guarantee declarations. Its presence does not itself imply that any particular guarantee is supported.

- Only a guarantee whose key and value semantics are defined by an applicable, governed EFS profile may be interpreted as an EFS guarantee.
- A consumer MUST NOT infer idempotency, retry safety, ordering, delivery, consistency, cancellation, approval, compensation, isolation, durability or any other behavior from omission, endpoint shape, transport choice or interaction mode.
- Unknown or unsupported guarantee declarations MUST NOT be promoted into a positive runtime assurance. They must be preserved or surfaced as unsupported according to the consuming product's boundary.
- Product teams MUST NOT create local meanings for a guarantee key and present them as shared EFS semantics. A new shared guarantee vocabulary requires a governed specification/profile change and cross-product impact review.

The same rule applies to execution-profile `constraints` and `guarantees`: declaration is not proof of runtime support or enforcement. PSI-44 may carry these declarations but MUST NOT redefine them.

## 7. Interaction modes and execution-profile binding

EFS v1 distinguishes four interaction modes in an execution profile:

| Mode | Normative interaction meaning | Does not imply |
| --- | --- | --- |
| `sync` | The caller interacts through a single request/response operation whose result is returned as the operation's response. | A particular HTTP/RPC protocol, timeout, retry policy or delivery guarantee. |
| `async` | The request may be accepted before the final result is available; the lifecycle continues after initial acceptance. | A specific queue, broker, polling API, persistence guarantee or retry behavior. |
| `streaming` | The interaction may deliver a sequence of progress/data events associated with one operation before its terminal outcome. | A particular stream protocol, ordering guarantee, replay guarantee or transport. |
| `event` | The interaction is initiated or advanced by event occurrence rather than requiring one continuously open request/response exchange. | A particular event bus, delivery mode, ordering, deduplication or exactly-once behavior. |

These mode names describe interaction semantics, not transport protocols. Endpoint `protocol` and `address` fields remain separate endpoint/interface declarations. EFS v1 does not select MCP, A2A, OpenAPI, CloudEvents, HTTP, gRPC, WebSocket, a message broker or any other mandatory transport.

A capability MAY list `executionProfiles`. When present, each entry MUST identify exactly one profile in the selected execution source:

- for `execution.source = "manifest"`, it matches `execution.profiles[].id`;
- for `execution.source = "external"`, it matches `execution.profileReferences[].id`.

Profile identifiers are compared exactly. A capability that omits `executionProfiles` makes no capability-specific profile selection; it does not authorize a consumer to invent a default profile. If a selected profile is unavailable or unresolved, the caller must report that condition rather than silently falling back.

The input and output schemas remain the capability payload contract regardless of interaction mode. PSI-44 defines how those payloads are carried in request, acceptance, progress, result and error envelopes. PSI-45 defines lifecycle-state transitions. Neither may change the payload schema or error semantics defined here.

## 8. Validation responsibilities and diagnostic boundary

PSI-42 defines the normative model; it does not implement payload validation or a runtime.

PSI-43 MUST implement the following against this model:

1. Structural validation against the canonical EFS v1 manifest schema.
2. Draft 2020-12 meta-validation of input, output and optional error schemas.
3. EFS v1 local-reference-profile enforcement.
4. Semantic checks for unique capability IDs within the exact release, unique error codes within each contract, and exact capability-to-execution-profile references.
5. Deterministic validation of concrete input and output JSON objects against the exact selected contract schema.
6. Stable machine-readable diagnostics with RFC 6901 JSON Pointer paths and deterministic ordering.
7. Publication integration that rejects invalid contract definitions before immutable artifact commit.

The diagnostic catalogue additions required by PSI-43 MUST distinguish at least duplicate capability IDs, duplicate contract error codes, and unresolved/ambiguous capability execution-profile references. Proposed stable codes are:

- `EFS_CAPABILITY_ID_DUPLICATE`
- `EFS_CONTRACT_ERROR_CODE_DUPLICATE`
- `EFS_CAPABILITY_EXECUTION_PROFILE_UNRESOLVED`

These codes are reserved by this model for PSI-43 implementation. They are not yet evidence that the PSI-43 validator exists.

The existing conformance report contract remains `reportVersion: "1.0"` unless PSI-43 proves a versioned report change is required. No report schema or stage is silently redefined by this model. If a new stage/field is necessary, it requires a separately versioned report contract and compatibility tests. Digest/signature verification, external policy retrieval/evaluation, dependency resolution, compatibility and runtime admission remain outside the conformance claim.

## 9. Four-product responsibility boundary

| Product | Responsibility under this model | Prohibited divergence |
| --- | --- | --- |
| Factory Studio | Author capability IDs, contract versions, schemas, errors and profile bindings; invoke the shared validator while editing/packaging. | Private contract dialect, independent error-code semantics or alternate schema validator behavior. |
| Factory Connect | Map native interfaces to the canonical capability/contract model and validate the resulting EFS representation. | Treating native API identifiers, endpoint URLs or transport names as contract identity. |
| Factory Runtime | Resolve the exact published release/capability/contract coordinate, validate inputs and outputs, and consume the PSI-44 execution envelope. | Selecting an implicit latest contract, inferring guarantees, or changing payload/error semantics. |
| Enterprise Factory Network | Validate contract definitions before publication, store immutable release artifacts, expose exact-release data and render derived Passport information. | Creating a second contract registry/identity or treating Passport text as authoritative contract metadata. |

The Network registry remains authoritative for exact published release coordinates and immutable artifact bytes. The Factory Passport remains a deterministic, provenance-aware, read-only projection. Neither becomes an independent source of capability or contract identity.

## 10. Compatibility and change impact

PSI-42 preserves the existing EFS v1 field names and nesting from PSI-34/35:

- `capability.id`, `capability.contract`, `capability.executionProfiles`;
- `contract.id`, `contract.version`, `contract.schemaDialect`, `contract.inputs`, `contract.outputs`, `contract.errors`, optional `contract.guarantees`;
- error `code`, `description`, optional `schema`;
- execution-profile `id`, `modes`, optional `constraints` and `guarantees`.

No new top-level manifest property, transport field, execution envelope or runtime state is introduced.

The schema is tightened in one place: an optional error payload schema now references the same Draft 2020-12 object-payload definition as inputs and outputs. A previously accepted error schema that did not declare top-level `"type": "object"` is no longer conformant. The model also defines the lexical form of error codes; existing codes outside the ASCII token grammar require correction before publication. The repository's existing minimal fixture and the four new mode examples conform to the tightened rule. This is an explicit EFS v1 conformance clarification, not a reportVersion change.

The semantic uniqueness and reference checks are specified here but implemented by PSI-43. PSI-42 adds no new report stage and does not alter the `reportVersion: 1.0` report schema. The model introduces no required transport or runtime technology, so PSI-44 can define envelopes without creating protocol coupling.

Any future change to these normative meanings requires a versioned specification change, impact analysis across all four products, updated fixtures and explicit approval. Accepted definitions MUST NOT be silently reinterpreted by a product adapter.

## 11. Conformance examples and acceptance mapping

The machine-readable examples under `fixtures/valid/capability-contract-*.json` demonstrate the four interaction modes while keeping endpoint protocol/transport selection out of the examples. They are full EFS v1 manifests and MUST pass the normative manifest validator.

The language-neutral model vectors and acceptance registry are:

- `conformance/efs/v1/capability-contract-model-vectors.json`
- `conformance/efs/v1/capability-contract-model-acceptance.json`

The vectors record exact identity scopes, case-sensitive equality, duplicate-code rejection, object payload constraints, local-only schema references, guarantee non-inference and the separation of interaction mode from transport. PSI-43 MUST turn the semantic vectors into executable validator tests and stable diagnostics; PSI-44 MUST use the mode and payload definitions as its normative input.

## 12. Explicit non-goals

This model does not implement:

- concrete payload validation or registry publication rejection (PSI-43);
- invocation/result/error envelope definitions (PSI-44);
- execution state transitions (PSI-45);
- semantic-version compatibility or negotiation (M4);
- publisher authentication, signatures, trust, certification or revocation (M5);
- policy evaluation or authorization (M5);
- dependency resolution;
- runtime scheduling, worker execution, transport selection or deployment;
- marketplace discovery, procurement or product-specific integration (M6).

## 13. Change history

- 2026-11-16 — PSI-42 normative capability/contract model established; error payload schema aligned with the object-payload rule; four interaction-mode examples and machine-readable acceptance vectors added.
