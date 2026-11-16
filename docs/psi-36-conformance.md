# PSI-36 — EFS v1 conformance corpus and validator

**Status:** implementation baseline for PSI-36  
**Baseline:** PSI-35 merge commit `b9d9867c812a37ec2512bc4ee24dde450f81f313`  
**Normative inputs:** approved PSI-34 canonical object model; PSI-35 Draft 2020-12 schema  
**Reference implementation:** `scripts/validate_manifest.py`

## 1. PSI-35 baseline audit

| Area | PSI-35 baseline | PSI-36 disposition |
| --- | --- | --- |
| Normative schema | Draft 2020-12 schema, root and nested structures | Preserve; validate schema itself and retain open unknown-field behavior |
| Valid fixtures | Minimal manifest and external-execution example | Expand to full, multi-capability and boundary examples |
| Invalid fixtures | Several structural negatives | Broaden structural, embedded-schema and prohibited-reference coverage |
| Parser integrity | Duplicate object member rejection | Formalize malformed JSON, duplicate root/nested members, non-JSON constants and invalid UTF-8 diagnostics |
| Embedded schemas | Input/output meta-validation; error-schema path present | Test input, output and error schemas independently |
| Reference safety | Reject absolute/network and dynamic refs | Stable diagnostic codes and pointer paths; no network resolver |
| Date-time | Explicit Draft 2020-12 FormatChecker | Preserve timezone-aware RFC 3339 positive/negative vectors |
| Reporting | Human-readable messages only | Deterministic staged report and JSON CLI output |
| CI | Python 3.11, 3.12, 3.13 | Retain matrix; run full corpus and CLI smoke tests |
| Governance boundaries | Structural vs digest/signature/policy/runtime separation documented | Make limitations explicit in report and conformance guide |

### Baseline gaps addressed

PSI-35 did not provide a complete fixture taxonomy, a staged conformance report, stable diagnostic identifiers, RFC 6901 JSON Pointer paths, deterministic multi-error reporting, or an explicit AC-to-test traceability document. PSI-36 addresses these gaps without changing the normative schema or deciding open governance questions.

## 2. Validation architecture

The validator runs a fail-fast dependency pipeline:

1. **Parsing** — strict UTF-8; JSON syntax; duplicate-member rejection at every object depth; reject NaN and Infinity.
2. **Structural** — check the normative schema as Draft 2020-12, then validate the manifest with an explicit `FormatChecker`.
3. **Embedded schemas** — meta-validate contract input/output and optional error schemas; enforce top-level object payload schemas; reject absolute/network `$ref`, `$dynamicRef` and `$dynamicAnchor`. No network resolver is installed.
4. **Profile** — enforce only EFS v1 constraints not already expressed by the schema and already governed by PSI-34/35.

A failed prerequisite marks dependent stages `not_run`. The report is deterministic and contains:

- `reportVersion`: `1.0` (versioned report contract)\n- `conformanceProfile`: `efs-v1`
- `schemaDialect`: Draft 2020-12 URI
- `valid`: overall conformance result
- `stages`: `passed`, `failed` or `not_run`
- ordered `diagnostics`: `code`, `stage`, RFC 6901 `path`, `message`, optional `details`

### Diagnostic codes

| Code | Meaning |
| --- | --- |
| `EFS_JSON_INVALID` | Malformed JSON, unreadable input or non-JSON numeric constant |
| `EFS_JSON_INVALID_ENCODING` | Input is not strict UTF-8 |
| `EFS_JSON_DUPLICATE_MEMBER` | Duplicate JSON object member |
| `EFS_SCHEMA_INVALID` | Normative schema invalid or cannot be loaded |\n| `EFS_SCHEMA_REQUIRED` | Required property absent |\n| `EFS_SCHEMA_TYPE` | Incorrect JSON type |\n| `EFS_SCHEMA_ENUM` | Enum or const violation |\n| `EFS_SCHEMA_FORMAT` | Asserted format violation |\n| `EFS_SCHEMA_CONSTRAINT` | Other structural constraint violation |
| `EFS_EMBEDDED_SCHEMA_INVALID` | Embedded Draft 2020-12 schema is invalid |
| `EFS_SCHEMA_REF_REMOTE` | Absolute or network schema reference prohibited |
| `EFS_SCHEMA_REF_UNSUPPORTED` | Dynamic reference keyword outside the EFS v1 profile |
| `EFS_PROFILE_FORMAT_INVALID` | Reserved for a separately profiled format assertion diagnostic |
| `EFS_PROFILE_INVARIANT_FAILED` | Governed EFS v1 profile invariant failed |
| `EFS_VALIDATOR_INTERNAL_ERROR` | Reserved for unexpected implementation failures; never used to disguise invalid input |

All exit paths pass through one report finalizer, which sorts diagnostics by stage, path, code, message and stable details. Structural schema keywords map to stable diagnostic codes. Missing required properties receive a pointer to the missing property when unambiguous. Paths are JSON Pointers (root is the empty string); pointer escaping follows RFC 6901.

## 3. Fixture taxonomy

| Directory | Expected result | Coverage |
| --- | --- | --- |
| `fixtures/valid/` | Pass | Minimal/full manifests, embedded/external execution, policy declarations/references and multiple capabilities |
| `fixtures/invalid/` | Fail | Missing required members, wrong types/enums, digest shape, empty required collections, execution branch conflicts and invalid embedded schemas |
| `fixtures/boundary/` | Pass | Minimum valid cardinalities, optional empty dependencies, single execution mode and timezone-aware RFC 3339 offset timestamp |
| `fixtures/extensions/` | Pass | Namespaced opaque extension payload; unknown core properties remain open |
| `fixtures/adversarial/` | Fail at parsing | Malformed JSON; duplicate-member and invalid-encoding byte sequences are additionally exercised through exact temporary raw inputs |

Fixtures use synthetic identities and digest-shaped placeholders. A fixture digest is not a computed or verified release digest. The canonical inventory is `conformance/efs/v1/fixture-catalog.json`; catalogue-driven tests enumerate every manifest in each declared group. Exact parser inputs are stored under `fixtures/adversarial/parser/`, with invalid UTF-8 represented as Base64 to preserve raw bytes in Git.

The machine-readable source of truth is `conformance/efs/v1/acceptance-criteria.json`. CI verifies that AC-01 through AC-15 are present in order, every referenced test function exists, every referenced fixture group exists, and every catalogue path resolves. The table below is the human-readable view of that registry.\n\n## 4. Acceptance criteria traceability

| AC | Requirement | Evidence |
| --- | --- | --- |
| AC-01 | Normative schema is checked as Draft 2020-12 | `test_schema_is_draft_2020_12`; `Draft202012Validator.check_schema` |
| AC-02 | Positive fixtures pass | `test_valid_fixture_corpus`; valid and boundary fixture globs |
| AC-03 | Negative fixtures fail | `test_invalid_fixture_corpus`; negative fixture corpus |
| AC-04 | Boundary fixtures pass | `test_boundary_fixture_corpus`; offset timestamp test |
| AC-05 | Extension and unknown-core behavior preserved | `test_namespaced_extension_payload_is_accepted`; `test_unknown_core_field_remains_open_pending_governance` |
| AC-06 | Malformed JSON, invalid UTF-8 and duplicate root/nested members rejected | malformed/adversarial fixture tests; invalid UTF-8 and duplicate-member tests |
| AC-07 | Input/output/error embedded schemas meta-validated | `test_embedded_input_output_and_error_schemas_are_meta_validated` |
| AC-08 | Remote and dynamic refs rejected; local fragment refs accepted | `test_remote_and_dynamic_refs_are_rejected`; `test_local_fragment_schema_reference_is_accepted` |
| AC-09 | RFC 3339 date-time asserted and timezone required | `test_date_time_requires_valid_rfc3339_timestamp_with_timezone`; offset boundary fixture |
| AC-10 | Stable machine-readable diagnostics and JSON Pointer paths | diagnostics schema assertions; path assertions in schema/date-time tests |
| AC-11 | Deterministic multi-error ordering and dependent `not_run` stages | `test_diagnostics_are_machine_readable_and_deterministic`; parse-failure stage test |
| AC-12 | CLI exits correctly and emits JSON report | `test_cli_json_report_contract`; `test_cli_failure_exit_and_json_report_for_invalid_manifest` |
| AC-13 | CI matrix Python 3.11, 3.12 and 3.13 | `.github/workflows/efs-schema.yml` |
| AC-14 | Reproducible commands and corpus documentation | this document; `fixtures/README.md` |
| AC-15 | Conformance is not digest/signature/policy/runtime authorization | validator module/CLI wording; scope boundary below |

## 5. Reproducible commands

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts/validate_manifest.py fixtures/valid/manifest-minimal.json
python scripts/validate_manifest.py fixtures/valid/manifest-minimal.json --json
python scripts/validate_manifest.py fixtures/invalid/manifest-invalid-digest-length.json
```

The validator returns exit code 0 for a conformant manifest and 1 for invalid input or failed conformance. The JSON report is intended for CI and downstream tooling.

## 6. Explicit scope boundary

A passing PSI-36 report proves only that the input passed the implemented EFS v1 parsing, structural, embedded-schema and profile checks. It does **not** prove:

- JCS digest recomputation or digest correctness;
- signature verification, key discovery, publisher identity or trust;
- retrieval or verification of external execution profiles, policies or dependencies;
- policy evaluation, authorization or tenant/platform permission;
- compatibility, runtime support, execution safety, deployment or runtime admission.

Those concerns remain separate workstreams. PSI-36 does not introduce unrestricted network retrieval, a policy language, new core fields, a closed-object policy, dependency target grammar, version grammar or extension namespace governance.

## 7. Definition of done

- Every manifest fixture discovered by the machine-readable catalogue is executed and checked against its declared expected outcome.\n- Every raw parser input is decoded exactly as catalogued and checked against its expected diagnostic code.\n- AC-01–AC-15 registry references resolve to real tests and fixture groups.
- All P0 acceptance criteria pass in the Python 3.11/3.12/3.13 CI matrix.
- Diagnostics and JSON report are deterministic and documented.
- No test silently skips a fixture.
- Conformance limitations are explicit in CLI and documentation.
- The PR records test and CI evidence; Linear PSI-36 links the implementation PR and final commit.
