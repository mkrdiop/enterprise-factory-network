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
| `EFS_JSON_INVALID_ENCODING` | Input is not valid UTF-8 |
| `EFS_JSON_DUPLICATE_MEMBER` | Duplicate JSON object member |
| `EFS_SCHEMA_INVALID` | Manifest schema invalid or manifest violates it |
| `EFS_EMBEDDED_SCHEMA_INVALID` | Embedded Draft 2020-12 schema is invalid |
| `EFS_SCHEMA_REF_REMOTE` | Absolute or network schema reference prohibited |
| `EFS_SCHEMA_REF_UNSUPPORTED` | Dynamic reference behavior is outside the EFS v1 subset |
| `EFS_PROFILE_INVARIANT_FAILED` | A profiled EFS v1 invariant failed |

Paths use RFC 6901 escaping (`~0` for tilde and `~1` for slash); the root path is
the empty string.

## Commands

Install development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

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
- Draft 2020-12 `date-time` format assertion is explicitly enabled; timezone-less
  timestamps are invalid.
- Embedded input, output and optional error schemas are meta-validated.
- External/network schema retrieval is never attempted.
- Unknown core fields and extension namespace grammar remain open as governed in PSI-34/35.
- The release digest is shape-validated by the manifest schema; digest computation and
  verification are separate work.
