# PSI-49 — Deterministic compatibility report engine

**Status:** Implementation baseline  
**Normative authorities:** PSI-46 / ADR-010 version dimensions; PSI-47 field-aware parser and release rules; PSI-48 compatibility dimensions, outcomes, evidence and aggregation.

## Contract

The engine consumes the shared `efs.compatibility` assessment primitives and the PSI-47 versioning API. It does not implement SemVer parsing or range grammar, interpret contract versions, evaluate trust, authorize execution, select releases, or redefine compatibility outcomes. `assess_efs_specification` calls PSI-47 `evaluate_efs_version_range(subject_efs_version, supported_range)` and passes its Boolean result to the PSI-48 specification assessor. Missing or malformed candidate/range inputs fail closed to `unknown`; a valid non-match is `breaking` only when PSI-48 evidence requirements are met. `ReleaseCoordinates` validates both `releaseVersion` and `efsVersion` with PSI-47's field-aware parser while retaining the exact strings.

A report binds the exact subject coordinate `(publisherId, factoryId, releaseVersion, digest profile, digest algorithm, digest value, efsVersion)` to the exact consumer identity/profile/version, declared EFS range, runtime profile and protocol profiles. It rejects specification-assessment coordinates that differ from the report's exact subject EFS version, consumer profile or declared range. It records all five PSI-48 dimensions, including explicit `unknown` assessments when evidence is absent.

## Report contract

`conformance/efs/v1/compatibility-report.schema.json` is the Draft 2020-12 schema for this derived artifact. Every report produced by `evaluate_compatibility` is validated against it before return. The schema is deliberately separate from the EFS conformance report schema.

The report includes report and ruleset versions; exact subject and consumer coordinates; each dimension's outcome, stable rule ID, explanation, evidence references, mappings, conditions, blockers, authority and evaluated coordinates; deterministic aggregate outcome, warnings and blockers; and provenance naming the engine version, canonicalization algorithm and normative PSI-46/47/48 authorities.

## Determinism

Report arrays that represent sets (dimensions, evidence references, mappings, conditions, blockers, protocol profiles) are canonically ordered. Canonical bytes use RFC 8785 JSON Canonicalization Scheme; SHA-256 fingerprint is computed over those bytes. Observation timestamps and other volatile metadata are excluded. Identical immutable inputs, evidence set and ruleset version therefore produce identical report bytes and fingerprint.

## Boundaries

- Contract versions remain opaque exact strings; no SemVer parsing or normalization.
- Release version and digest remain distinct exact coordinates.
- The engine accepts an already selected exact subject; it does not implement latest/latest-compatible selection. PSI-47's `require_exact_release_selection(candidates, requested_coordinate)` requires the caller to supply the exact requested `ReleaseCoordinate` and matches its complete six-field identity. Equal-precedence labels may therefore be selected explicitly; SemVer precedence never ranks candidates or supplies an implicit tie-breaker.
- Compatible/breaking conclusions require evidence; conditional outcomes require conditions; breaking outcomes require blockers; missing evidence remains unknown.
- Governance remains unknown unless M5 authority and evidence are explicitly supplied.
- A compatibility report does not establish publisher trust, signature validity, authorization, policy compliance or runtime admission.
- The report is derived and never mutates a manifest, Passport, registry release or digest.

## Verification

Run `python -m pytest tests/test_compatibility.py tests/test_compatibility_vectors.py tests/test_compatibility_report.py -q` and `python -m ruff check scripts tests efs`.
