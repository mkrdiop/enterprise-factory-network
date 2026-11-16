# EFS v1 conformance corpus

This directory is a language-neutral corpus for EFS v1 Factory Manifest conformance.
Each JSON manifest is evaluated by the reference Python validator, but the expected
outcome and taxonomy are part of the fixture contract—not Python-specific behavior.

## Taxonomy

| Directory | Expected result | Purpose |
| --- | --- | --- |
| `valid/` | Pass | Minimal manifest and externally referenced execution profile |
| `invalid/` | Fail | Structural, profile, embedded-schema and prohibited-reference cases |
| `boundary/` | Pass | Valid boundary values, including RFC 3339 offset timestamps |
| `extensions/` | Pass | Namespaced opaque extension payloads; unknown core fields remain open pending governance |
| `adversarial/` | Fail at parsing | Raw parser inputs such as malformed JSON and duplicate object members |

## Fixture authoring rules

- Keep examples small and focused on one conformance property.
- Use synthetic identifiers, domains and digest-shaped placeholders. A fixture digest
  is not evidence that a release digest was actually computed or verified.
- Do not add external schema or policy retrieval requirements.
- Every new fixture must be included in the appropriate test glob or explicit parser test.
- Preserve PSI-35's open unknown-core-field behavior until a separate governance decision
  changes it.
- Do not infer signature, policy, dependency, compatibility or runtime guarantees from
  a passing fixture.

## Current coverage

- Positive: minimal and multi-capability manifests; manifest-sourced and external execution profiles.
- Negative: missing required property, wrong field type, empty required collections, mutually exclusive execution branches, timezone-less timestamp, invalid embedded schema, remote `$ref`, unsupported dynamic reference.
- Boundary: minimum valid collection cardinalities, empty optional dependencies, and timezone-aware RFC 3339 offset timestamp.
- Extensions: namespaced opaque extension data.
- Parser/adversarial cases are generated in isolated temporary files by tests so malformed
  byte sequences and duplicate-member inputs remain exact and portable.
