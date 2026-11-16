# EFS v1 conformance corpus

This directory is a language-neutral corpus for EFS v1 Factory Manifest conformance.
Each JSON manifest is evaluated by the reference Python validator, but the expected
outcome and taxonomy are part of the fixture contract—not Python-specific behavior.

## Taxonomy

| Directory | Expected result | Purpose |
| --- | --- | --- |
| `valid/` | Pass | Minimal, full and multi-capability manifests; manifest/external execution and policy variants |
| `invalid/` | Fail | Structural, profile, embedded-schema and prohibited-reference cases |
| `boundary/` | Pass | Valid boundary values, including RFC 3339 offset timestamps |
| `extensions/` | Pass | Namespaced opaque extension payloads; unknown core fields remain open pending governance |
| `adversarial/` | Fail at parsing | Raw parser inputs such as malformed JSON, non-standard numeric constants and duplicate object members |

## Fixture authoring rules

- Keep examples small and focused on one conformance property.
- Use synthetic identifiers, domains and digest-shaped placeholders. A fixture digest
  is not evidence that a release digest was actually computed or verified.
- Do not add external schema or policy retrieval requirements.
- Every new manifest fixture must fall under a catalogue glob in `conformance/efs/v1/fixture-catalog.json`; every raw parser vector must be registered there with encoding and expected diagnostic code. The catalogue-driven tests enforce this inventory.
- Preserve PSI-35's open unknown-core-field behavior until a separate governance decision
  changes it.
- Do not infer signature, policy, dependency, compatibility or runtime guarantees from
  a passing fixture.

## Current coverage

- Positive: minimal, full and multi-capability manifests; manifest-sourced and external execution profiles; declarations and references.
- Negative: missing required property, wrong field type, empty required collections, invalid digest length, execution-mode enum/branch violations, invalid contract URI, empty policy declarations, timezone-less timestamp, invalid embedded schema, remote `$ref`, unsupported dynamic reference.
- Boundary: minimum valid collection cardinalities, empty optional dependencies, one execution mode, absolute URN/HTTPS identifiers, timezone-aware RFC 3339 offset timestamp and leap-day timestamp.
- Extensions: namespaced opaque extension data.
- Parser/adversarial inputs are explicit files under `adversarial/parser/`. Invalid UTF-8 is stored as Base64 and decoded by tests, preserving exact bytes across Git and checkout environments. Duplicate-member files intentionally contain invalid JSON object texts.
