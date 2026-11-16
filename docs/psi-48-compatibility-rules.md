# PSI-48 — Shared compatibility dimensions and rules

**Status:** Implementation baseline  
**Normative authority:** [EFS v1 version-dimension model](efs-v1-version-dimensions.md), [ADR-010](adr/ADR-010-efs-v1-version-dimension-model.md), PSI-42 capability/contract model, PSI-44 exact execution coordinates, and M5 governance authority when accepted.

## 1. Contract

This module consumes the exact PSI-46 release coordinates; it does not redefine the four version dimensions or introduce a new version grammar. A compatibility assessment is a derived, evidence-bound claim, not a manifest field, trust assertion, authorization decision or release-selection operation.

The five assessment dimensions are specification support, Factory release/capability contract, runtime/execution, protocol and governance. These are evaluation axes, not new version dimensions.

## 2. Inputs and evidence

Every report retains the exact subject `(publisherId, factoryId, releaseVersion, digest profile/algorithm/value, efsVersion)` and explicit consumer identity/profile/version. The consumer profile must declare its EFS supported range, runtime profile and protocol profiles. The specification assessor consumes the Boolean result of the shared PSI-47 SemVer range evaluator; PSI-48 does not parse or compare version strings itself.

Evidence references identify a source and may include a digest and owning authority. A reference is provenance, not proof that the source is authentic or trusted. Compatible/breaking outcomes require evidence. A conditional outcome must list actionable conditions. Breaking outcomes must list blockers. Missing evidence is unknown, never compatible.

## 3. Per-dimension rules

| Dimension | Required evidence / rule | Insufficient evidence |
| --- | --- | --- |
| Specification | Explicit consumer EFS range/profile and PSI-47 range-evaluator result with evidence | Unknown |
| Factory release/capability contract | Exact contract ID and opaque versions; explicit definition-change classification and evidence. Same version requires explicit unchanged-definition evidence; a matching opaque version alone is not proof. | Unknown |
| Runtime/execution | Explicit subject and consumer runtime profiles, named mapping, explicit mapping outcome and evidence | Unknown |
| Protocol | Explicit subject and consumer protocol profiles, named adapter/protocol mapping and evidence | Unknown |
| Governance | Only an explicit M5-authority result with M5 evidence | Unknown until M5 authority/evidence exists |

Contract versions are compared only by exact case-sensitive identity. When a contract version changes, compatibility is determined from the contract definition/change evidence, never from SemVer ordering or lexical/numeric appearance. Runtime/protocol profile names alone are not evidence of wire or execution compatibility.

## 4. Outcomes and aggregation

The only outcomes are `compatible`, `breaking`, `conditional` and `unknown`. The deterministic aggregate rank is `compatible < conditional < unknown < breaking`: any breaking dimension makes the aggregate breaking; otherwise unknown evidence prevents a compatible claim; otherwise unmet conditions produce conditional; only all-compatible dimensions produce compatible. The report lists each dimension, stable rule ID, explanation, evidence references, mappings, conditions and blockers.

Missing dimensions are materialized as `unknown`. Duplicate assessments are rejected. Governance outcomes other than unknown require `authority: M5` and evidence; the module does not define signatures, trust roots, policy or permission semantics. Those remain M5-owned.

## 5. Determinism and non-goals

Canonical report JSON sorts object keys and dimension entries and excludes observation timestamps. Identical subject, consumer, assessments and ruleset version produce identical bytes and SHA-256 fingerprint. The report is derived and does not change immutable manifests/releases.

No automatic latest/latest-compatible resolution, negotiation, release selection, dependency solving, signature/trust verification, authorization or policy evaluation is performed. PSI-49 will consume these shared rules; it must not duplicate them.

## 6. Verification

`tests/test_compatibility.py` covers explicit range/evidence, opaque contract handling, runtime/protocol mappings, M5 boundary, conservative aggregation, duplicate rejection and deterministic output. Run `python -m pytest tests/test_compatibility.py -q` and `python -m ruff check scripts tests efs`.
