# EFS v1 conformance validation

## Purpose and claim boundary

The reference validator implements layered EFS v1 manifest conformance checks. A passing
result means the input was parsed, validated against the normative Draft 2020-12 manifest
schema, had its embedded contract schemas meta-validated, and passed the currently
profiled EFS v1 invariants.

It does **not** mean the release digest or signature was verified, external references
were retrieved, dependencies resolved, policies evaluated, compatibility established,
or runtime execution authorized.

## Validation stages

The machine-readable report contains:

- `reportVersion`: `1.0` (versioned report contract)
- `conformanceProfile`: `efs-v1`
- `schemaDialect`: the Draft 2020-12 dialect URI
- `valid`: overall result
- `stages`: `parsing`, `structural`, `embedded_schemas`, and `profile`, each
  marked `passed`, `failed`, or `not_run`
- `diagnostics`: ordered objects with stable `code`, `stage`, RFC 6901 JSON Pointer
  `path`, human-readable `message`, and optional structured `details`

A stage is not run when a prerequisite stage fails. Structural errors are collected and
sorted deterministically. The validator does not fetch remote schemas: absolute/network
`$ref` values and unprofiled dynamic-reference keywords are rejected.

## Diagnostic codes

| Code | Meaning |
| --- | --- |
| `EFS_JSON_INVALID` | Malformed JSON or unreadable input |
| `EFS_JSON_INVALID_ENCODING` | Input is not valid UTF-8 |
| `EFS_JSON_DUPLICATE_MEMBER` | Duplicate JSON object member |
| `EFS_SCHEMA_INVALID` | Normative manifest schema cannot be loaded or validated |
| `EFS_SCHEMA_REQUIRED` | Required property is absent |
| `EFS_SCHEMA_TYPE` | Incorrect JSON type |
| `EFS_SCHEMA_ENUM` | Enum or const violation |
| `EFS_SCHEMA_FORMAT` | Asserted format violation |
| `EFS_SCHEMA_CONSTRAINT` | Other structural constraint violation |
| `EFS_EMBEDDED_SCHEMA_INVALID` | Embedded Draft 2020-12 schema is invalid |
| `EFS_SCHEMA_REF_REMOTE` | Absolute or network schema reference prohibited |
| `EFS_SCHEMA_REF_UNSUPPORTED` | Dynamic reference behavior is outside the EFS v1 subset |
| `EFS_PROFILE_INVARIANT_FAILED` | A profiled EFS v1 invariant failed |
| `EFS_PUBLISHER_URI_INVALID` | Publisher ID is not a valid absolute URI under `efs-uri-c14n-1` |
| `EFS_PUBLISHER_URI_NON_CANONICAL` | Publisher ID is valid but not in canonical `efs-uri-c14n-1` form |

Paths use RFC 6901 escaping (`~0` for tilde and `~1` for slash); the root path is
the empty string.

## Commands

Install development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

The machine-readable inventories are maintained under `conformance/efs/v1/`: `fixture-catalog.json`, `diagnostic-catalog.json`, `report-schema.json`, `acceptance-criteria.json`, `publisher-identity-vectors.json`, `publisher-identity-acceptance.json`, and `capability-contract-model-vectors.json` / `capability-contract-model-acceptance.json`. The normative capability/contract semantics and four interaction-mode examples are defined in `docs/efs-v1-capability-contract-model.md` and `fixtures/valid/capability-contract-*.json`. The publisher identity corpus defines `efs-uri-c14n-1` with positive, negative and canonicalization vectors. `tests/test_publisher_identity.py` executes every vector, verifies deterministic diagnostics, preserves the existing URN example, and checks publisher-scoped Factory identity semantics. The catalogue-driven tests discover every manifest matching each fixture group and test it against the declared outcome. Raw parser vectors are stored under `fixtures/adversarial/parser/`; invalid UTF-8 is stored as Base64 so Git can preserve the fixture bytes. The acceptance registry maps every AC-01–AC-15 to real test functions and fixture groups, and CI executes these checks as part of pytest.

Run the full test corpus:

```bash
python -m pytest -q
```

Validate a manifest:

```bash
python scripts/validate_manifest.py fixtures/valid/manifest-minimal.json
```

Emit the machine-readable report:

```bash
python scripts/validate_manifest.py fixtures/valid/manifest-minimal.json --json
```

## Reference implementation constraints

- Python is a reference consumer, not the normative definition of EFS.
- JSON parsing rejects duplicate object members, invalid UTF-8, malformed JSON and non-standard numeric constants (NaN/Infinity).
- `publisher.id` is an absolute URI and must already use the canonical `efs-uri-c14n-1` serialization; validation is local-only and never dereferences the identifier.
- Draft 2020-12 `date-time` format assertion is explicitly enabled; timezone-less
  timestamps are invalid.
- Embedded input, output and optional error schemas are meta-validated as Draft 2020-12 resources; each top-level payload schema is an object schema. Optional error schemas use the same object-payload definition.
- Contract error codes follow the EFS v1 ASCII token grammar and are compared exactly; duplicate codes within a contract are a semantic violation implemented by PSI-43.
- Capability and contract identity semantics, execution-profile binding and interaction-mode/transport separation are defined in `docs/efs-v1-capability-contract-model.md`.
- External/network schema retrieval is never attempted.
- Unknown core fields and extension namespace grammar remain open as governed in PSI-34/35.
- The release digest is shape-validated by the manifest schema; digest computation and
  verification are separate work.
