# PSI-47 — EFS v1 version parser and Factory release rules

**Status:** Implementation baseline  
**Normative authority:** [EFS v1 version-dimension model](efs-v1-version-dimensions.md), [ADR-010](adr/ADR-010-efs-v1-version-dimension-model.md), and `conformance/efs/v1/version-dimension-vectors.json`.

## Scope

The reference implementation in `efs.versioning` parses SemVer 2.0.0 only for the root `efsVersion` and `release.version` fields. It retains the field dimension in comparison calls. Factory release comparison requires the exact `(publisher.id, factory.id)` pair. No cross-dimension or cross-Factory ordering is possible through the public comparison API.

`capability.contract.version` remains an opaque non-empty exact string. `contract_versions_equal` performs ordinal, case-sensitive equality only. Passing that field, a build identifier, protocol, policy, execution-profile or dependency constraint to the SemVer parser is rejected. Implementation build identity remains outside the EFS v1 manifest.

## Release rules

`validate_release_transition` requires an explicit reviewed classification (`breaking`, `additive`, or `fix`); it does not infer API impact from an arbitrary manifest diff. Breaking public-surface changes require a MAJOR increment, compatible additive changes a MINOR increment without changing MAJOR, and backward-compatible fixes a PATCH increment. Every proposed release must have greater SemVer precedence. Callers remain responsible for immutable registry uniqueness by exact release string and digest conflict handling; this module never rewrites identifiers or replaces digest checks.

`ReleaseCoordinate` retains the exact publisher, Factory, version and digest tuple. `require_exact_release_selection` finds the highest precedence only within one exact Factory stream and rejects multiple distinct exact labels at equal precedence. Build metadata is not a tie-breaker.

## Diagnostics and API boundary

Invalid values raise `VersionError`; invalid release transitions raise `ReleaseChangeError`. The parser rejects prefixes, whitespace, shorthand, leading zeroes, non-ASCII syntax and malformed identifiers. The implementation is a semantic utility and does not alter manifest schema, historical records, digest verification, signature/trust, policy or runtime admission.

## Verification

`tests/test_versioning.py` covers SemVer grammar and precedence, contract opacity, dimension/scope guards, release classification, version/digest separation and ambiguous build-metadata labels. Run `python -m pytest tests/test_versioning.py -q` and `python -m ruff check scripts tests efs`.


## EFS supported-range evaluator integration contract

PSI-48 owns the supported-range language and its compatibility meaning. PSI-47 supplies the shared evaluator API `evaluate_efs_version_range(candidate, supported_range)`; it is deliberately limited to the EFS specification-version field (`efsVersion`). It reuses the strict PSI-47 SemVer parser and precedence comparator and does not define Factory release selection, dependency solving or a general-purpose version constraint system.

The EFS v1 range grammar and normative behavior are specified in [PSI-48 compatibility rules](psi-48-compatibility-rules.md). The accepted forms are `*`, `MAJOR.x`, `MAJOR.MINOR.x`, one exact full SemVer value, or a conjunction of full-SemVer comparisons using `>`, `>=`, `<`, `<=` or `=`. Each comparison term concatenates its operator directly with its full SemVer bound (for example, `>=1.0.0`); terms are separated by one ASCII space and use AND semantics. Unsupported or malformed expressions raise `VersionRangeError`; callers must not coerce them or treat them as a match.

The evaluator returns a Boolean only after both the candidate and every range bound pass strict SemVer parsing. Build metadata is ignored for precedence; prerelease values use SemVer 2.0.0 precedence without an additional stable-only filter. The evaluator never changes or normalizes the exact input strings. PSI-49 must call this API and pass its Boolean result to the PSI-48 specification assessor; missing/malformed inputs remain `unknown`.
