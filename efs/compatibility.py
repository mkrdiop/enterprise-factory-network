"""Evidence-bound EFS v1 compatibility assessment and report engine.

Normative authorities: PSI-46 version dimensions, PSI-47 version evaluator,
and PSI-48 compatibility dimensions/rules. This module consumes their outputs;
it does not define version grammars, range parsing, trust, or admission policy.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
import rfc8785

from efs.versioning import (
    VersionDimension,
    VersionError,
    VersionRangeError,
    evaluate_efs_version_range,
    parse_field_version,
)


class CompatibilityError(ValueError):
    """Invalid compatibility input, report, or unsupported inference."""


class CompatibilityDimension(str, Enum):
    SPECIFICATION = "specification"
    FACTORY_CONTRACT = "factory-release-capability-contract"
    RUNTIME = "runtime-execution"
    PROTOCOL = "protocol"
    GOVERNANCE = "governance"


class Outcome(str, Enum):
    COMPATIBLE = "compatible"
    BREAKING = "breaking"
    CONDITIONAL = "conditional"
    UNKNOWN = "unknown"


_AGGREGATE_RANK = {
    Outcome.COMPATIBLE: 0,
    Outcome.CONDITIONAL: 1,
    Outcome.UNKNOWN: 2,
    Outcome.BREAKING: 3,
}
_REPORT_VERSION = "1.0"
_ENGINE_VERSION = "1.0.0"
_RULESET_AUTHORITIES = ("PSI-46", "PSI-47", "PSI-48")


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """Pointer to evidence; a reference is provenance, not proof of trust."""

    evidence_id: str
    source: str
    digest: str | None = None
    authority: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_id, str) or not self.evidence_id:
            raise CompatibilityError("evidence_id must be a non-empty exact string")
        if not isinstance(self.source, str) or not self.source:
            raise CompatibilityError("evidence source must be a non-empty exact string")
        for name, value in (("digest", self.digest), ("authority", self.authority)):
            if value is not None and (not isinstance(value, str) or not value):
                raise CompatibilityError(f"evidence {name} must be null or a non-empty exact string")


@dataclass(frozen=True, slots=True)
class ReleaseCoordinates:
    """Exact PSI-46 release coordinate; version and digest remain separate."""

    publisher_id: str
    factory_id: str
    release_version: str
    digest_profile: str
    digest_algorithm: str
    digest_value: str
    efs_version: str

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (
            self.publisher_id, self.factory_id, self.release_version,
            self.digest_profile, self.digest_algorithm, self.digest_value, self.efs_version,
        )):
            raise CompatibilityError("all exact release coordinates must be non-empty strings")
        try:
            parse_field_version(VersionDimension.FACTORY_RELEASE, self.release_version)
            parse_field_version(VersionDimension.EFS_SPECIFICATION, self.efs_version)
        except VersionError as exc:
            raise CompatibilityError(f"subject release coordinate contains an invalid SemVer value: {exc}") from exc

    def as_dict(self) -> dict[str, Any]:
        return {
            "publisherId": self.publisher_id,
            "factoryId": self.factory_id,
            "releaseVersion": self.release_version,
            "digest": {
                "profile": self.digest_profile,
                "algorithm": self.digest_algorithm,
                "value": self.digest_value,
            },
            "efsVersion": self.efs_version,
        }


@dataclass(frozen=True, slots=True)
class ConsumerProfile:
    consumer_id: str
    profile_id: str
    profile_version: str
    supported_efs_range: str
    runtime_profile_id: str
    protocol_profile_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        required = (
            self.consumer_id, self.profile_id, self.profile_version,
            self.supported_efs_range, self.runtime_profile_id,
        )
        if not all(isinstance(value, str) and value for value in required):
            raise CompatibilityError("consumer identity and explicit profile/range fields are required")
        if not isinstance(self.protocol_profile_ids, tuple) or not all(
            isinstance(value, str) and value for value in self.protocol_profile_ids
        ):
            raise CompatibilityError("protocol_profile_ids must be a tuple of non-empty exact strings")
        if len(set(self.protocol_profile_ids)) != len(self.protocol_profile_ids):
            raise CompatibilityError("protocol_profile_ids must not contain duplicates")


@dataclass(frozen=True, slots=True)
class DimensionAssessment:
    dimension: CompatibilityDimension
    outcome: Outcome
    rule_id: str
    explanation: str
    evidence: tuple[EvidenceReference, ...] = ()
    conditions: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    mappings: tuple[str, ...] = ()
    authority: str | None = None
    coordinates: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, CompatibilityDimension) or not isinstance(self.outcome, Outcome):
            raise CompatibilityError("assessment dimension and outcome must use the shared enums")
        if not isinstance(self.rule_id, str) or not self.rule_id or not isinstance(self.explanation, str) or not self.explanation:
            raise CompatibilityError("each assessment requires a stable rule ID and explanation")
        for name, values in (
            ("evidence", self.evidence), ("conditions", self.conditions),
            ("blockers", self.blockers), ("mappings", self.mappings),
        ):
            if not isinstance(values, tuple):
                raise CompatibilityError(f"{name} must be an immutable tuple")
        if not all(isinstance(item, EvidenceReference) for item in self.evidence):
            raise CompatibilityError("assessment evidence must use EvidenceReference")
        for name, values in (("conditions", self.conditions), ("blockers", self.blockers), ("mappings", self.mappings)):
            if not all(isinstance(value, str) and value for value in values):
                raise CompatibilityError(f"{name} entries must be non-empty exact strings")
        if self.outcome is Outcome.CONDITIONAL and not self.conditions:
            raise CompatibilityError("conditional assessment must state its unmet conditions")
        if self.outcome in (Outcome.COMPATIBLE, Outcome.BREAKING) and not self.evidence:
            raise CompatibilityError("compatible/breaking conclusions require explicit evidence")
        if self.outcome is Outcome.BREAKING and not self.blockers:
            raise CompatibilityError("breaking assessment must identify blockers")
        if self.authority is not None and (not isinstance(self.authority, str) or not self.authority):
            raise CompatibilityError("assessment authority must be null or a non-empty exact string")
        if not isinstance(self.coordinates, tuple) or not all(
            isinstance(pair, tuple) and len(pair) == 2
            and all(isinstance(value, str) and value for value in pair)
            for pair in self.coordinates
        ):
            raise CompatibilityError("assessment coordinates must be immutable exact string pairs")
        keys = [pair[0] for pair in self.coordinates]
        if len(keys) != len(set(keys)):
            raise CompatibilityError("assessment coordinate keys must be unique")


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    report_version: str
    ruleset_version: str
    subject: ReleaseCoordinates
    consumer: ConsumerProfile
    assessments: tuple[DimensionAssessment, ...]
    outcome: Outcome
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Return the schema-defined report representation with order-independent sets."""
        dimensions = []
        for item in sorted(self.assessments, key=lambda result: result.dimension.value):
            evidence = sorted(
                (asdict(ref) for ref in item.evidence),
                key=lambda ref: (ref["evidence_id"], ref["source"], ref["digest"] or "", ref["authority"] or ""),
            )
            dimensions.append({
                "dimension": item.dimension.value,
                "outcome": item.outcome.value,
                "ruleId": item.rule_id,
                "explanation": item.explanation,
                "evidence": evidence,
                "conditions": sorted(set(item.conditions)),
                "blockers": sorted(set(item.blockers)),
                "mappings": sorted(set(item.mappings)),
                "authority": item.authority,
                "coordinates": {key: value for key, value in sorted(item.coordinates)},
            })
        return {
            "reportVersion": self.report_version,
            "rulesetVersion": self.ruleset_version,
            "subject": self.subject.as_dict(),
            "consumer": {
                "consumerId": self.consumer.consumer_id,
                "profileId": self.consumer.profile_id,
                "profileVersion": self.consumer.profile_version,
                "supportedEfsRange": self.consumer.supported_efs_range,
                "runtimeProfileId": self.consumer.runtime_profile_id,
                "protocolProfileIds": sorted(self.consumer.protocol_profile_ids),
            },
            "dimensions": dimensions,
            "outcome": self.outcome.value,
            "warnings": sorted(set(self.warnings)),
            "blockers": sorted(set(self.blockers)),
            "provenance": {
                "engine": "efs.compatibility",
                "engineVersion": _ENGINE_VERSION,
                "normativeAuthorities": list(_RULESET_AUTHORITIES),
                "canonicalization": "RFC8785",
            },
        }

    def canonical_json(self) -> str:
        """Return RFC 8785 canonical JSON; no observation time or volatile metadata."""
        payload = self.as_dict()
        validate_compatibility_report(payload)
        return rfc8785.dumps(payload).decode("utf-8")

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _report_schema() -> dict[str, Any]:
    import json

    schema_path = Path(__file__).resolve().parents[1] / "conformance/efs/v1/compatibility-report.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CompatibilityError(f"compatibility report schema is unavailable: {exc}") from exc
    jsonschema.Draft202012Validator.check_schema(schema)
    return schema


def validate_compatibility_report(payload: dict[str, Any]) -> None:
    """Validate every serialized report against the local, versioned Draft 2020-12 schema."""
    if not isinstance(payload, dict):
        raise CompatibilityError("compatibility report must be a JSON object")
    errors = sorted(
        jsonschema.Draft202012Validator(_report_schema()).iter_errors(payload),
        key=lambda error: (tuple(str(part) for part in error.absolute_path), error.message),
    )
    if errors:
        error = errors[0]
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        raise CompatibilityError(f"compatibility report schema violation at {path}: {error.message}")


def _unknown(dimension: CompatibilityDimension, rule_id: str, reason: str) -> DimensionAssessment:
    return DimensionAssessment(dimension, Outcome.UNKNOWN, rule_id, reason)


def assess_specification(
    *, supported_range: str, consumer_profile_id: str,
    range_evaluator_result: bool | None, evidence: Iterable[EvidenceReference] = (),
) -> DimensionAssessment:
    """Consume the PSI-47 SemVer range-evaluator result; never parse ranges here."""
    coordinates = tuple(sorted(
        (key, value) for key, value in (
            ("supportedEfsRange", supported_range),
            ("consumerProfileId", consumer_profile_id),
        ) if isinstance(value, str) and value
    ))
    if not isinstance(supported_range, str) or not supported_range or not isinstance(consumer_profile_id, str) or not consumer_profile_id:
        return DimensionAssessment(CompatibilityDimension.SPECIFICATION, Outcome.UNKNOWN, "EFC-SPEC-001",
                                   "No explicit consumer EFS support range/profile was supplied.",
                                   coordinates=coordinates)
    refs = tuple(evidence)
    if not isinstance(range_evaluator_result, bool) or not refs:
        return DimensionAssessment(CompatibilityDimension.SPECIFICATION, Outcome.UNKNOWN, "EFC-SPEC-002",
                                   "EFS range evaluation or its supporting evidence is unavailable.",
                                   coordinates=coordinates)
    if range_evaluator_result:
        return DimensionAssessment(CompatibilityDimension.SPECIFICATION, Outcome.COMPATIBLE,
                                   "EFC-SPEC-003", "Subject EFS version is within the declared consumer range.",
                                   refs, coordinates=coordinates)
    return DimensionAssessment(CompatibilityDimension.SPECIFICATION, Outcome.BREAKING,
                               "EFC-SPEC-004", "Subject EFS version is outside the declared consumer range.",
                               refs, blockers=("unsupported-efs-version",), coordinates=coordinates)


def assess_efs_specification(
    *, subject_efs_version: str, supported_range: str, consumer_profile_id: str,
    evidence: Iterable[EvidenceReference] = (),
) -> DimensionAssessment:
    """Evaluate the EFS v1 range with PSI-47, then apply PSI-48 evidence rules.

    Invalid candidate versions or unsupported range syntax fail closed to
    unknown. This adapter does not implement or normalize range semantics.
    """
    refs = tuple(evidence)
    if not isinstance(supported_range, str) or not supported_range or not isinstance(consumer_profile_id, str) or not consumer_profile_id:
        assessment = assess_specification(
            supported_range=supported_range, consumer_profile_id=consumer_profile_id,
            range_evaluator_result=None, evidence=refs,
        )
    else:
        try:
            result = evaluate_efs_version_range(subject_efs_version, supported_range)
        except VersionRangeError:
            assessment = assess_specification(
                supported_range=supported_range, consumer_profile_id=consumer_profile_id,
                range_evaluator_result=None, evidence=refs,
            )
            assessment = replace(
                assessment,
                rule_id="EFC-SPEC-005",
                explanation="Subject efsVersion or supported-range expression is invalid or unsupported; evaluation failed closed.",
            )
        else:
            assessment = assess_specification(
                supported_range=supported_range, consumer_profile_id=consumer_profile_id,
                range_evaluator_result=result, evidence=refs,
            )
    coordinates = dict(assessment.coordinates)
    if isinstance(subject_efs_version, str) and subject_efs_version:
        coordinates["subjectEfsVersion"] = subject_efs_version
    return replace(assessment, coordinates=tuple(sorted(coordinates.items())))


def assess_contract_change(
    *, capability_id: str, contract_id: str, previous_version: str, selected_version: str,
    change_classification: str | None, evidence: Iterable[EvidenceReference] = (),
) -> DimensionAssessment:
    """Assess contract definitions/evidence; contract versions are opaque exact strings."""
    dimension = CompatibilityDimension.FACTORY_CONTRACT
    if not all(isinstance(value, str) and value for value in (capability_id, contract_id, previous_version, selected_version)):
        return _unknown(dimension, "EFC-CONTRACT-001", "Exact capability/contract coordinate is incomplete.")
    refs = tuple(evidence)
    coordinate = (("capabilityId", capability_id), ("contractId", contract_id),
                  ("previousContractVersion", previous_version), ("selectedContractVersion", selected_version))
    if previous_version == selected_version:
        if not refs or change_classification != "unchanged":
            return DimensionAssessment(dimension, Outcome.UNKNOWN, "EFC-CONTRACT-002",
                                       "Exact opaque contract version matches, but unchanged definition evidence is not established.",
                                       coordinates=coordinate)
        return DimensionAssessment(dimension, Outcome.COMPATIBLE, "EFC-CONTRACT-003",
                                   "Exact opaque contract version and unchanged definition are evidenced.", refs,
                                   coordinates=coordinate)
    if not refs or change_classification is None:
        return DimensionAssessment(dimension, Outcome.UNKNOWN, "EFC-CONTRACT-004",
                                   "Contract version differs; no explicit definition-change classification/evidence was supplied.",
                                   coordinates=coordinate)
    if change_classification == "compatible-additive":
        return DimensionAssessment(dimension, Outcome.COMPATIBLE, "EFC-CONTRACT-005",
                                   "Contract definition change is explicitly classified as compatible additive.", refs,
                                   coordinates=coordinate)
    if change_classification == "breaking":
        return DimensionAssessment(dimension, Outcome.BREAKING, "EFC-CONTRACT-006",
                                   "Contract definition change is explicitly classified as breaking.", refs,
                                   blockers=("breaking-contract-change",), coordinates=coordinate)
    if change_classification == "conditional":
        return DimensionAssessment(dimension, Outcome.CONDITIONAL, "EFC-CONTRACT-007",
                                   "Contract change requires an explicit consumer action.", refs,
                                   conditions=("consumer-must-apply-declared-contract-mapping",), coordinates=coordinate)
    return DimensionAssessment(dimension, Outcome.UNKNOWN, "EFC-CONTRACT-008",
                               "Contract change classification is not recognized.", coordinates=coordinate)


def assess_profile_mapping(
    dimension: CompatibilityDimension, *, subject_profile_id: str | None,
    consumer_profile_id: str | None, mapping_id: str | None,
    mapping_outcome: Outcome | str | None,
    evidence: Iterable[EvidenceReference] = (), conditions: Iterable[str] = (),
    blockers: Iterable[str] = (),
) -> DimensionAssessment:
    """Evaluate runtime/protocol only from explicit profiles and named mapping evidence."""
    if dimension not in (CompatibilityDimension.RUNTIME, CompatibilityDimension.PROTOCOL):
        raise CompatibilityError("profile mapping is valid only for runtime or protocol dimensions")
    refs = tuple(evidence)
    coordinate_values = {
        "subjectProfileId": subject_profile_id,
        "consumerProfileId": consumer_profile_id,
    }
    if mapping_id:
        coordinate_values["mappingId"] = mapping_id
    coordinates = tuple(sorted(
        (key, value) for key, value in coordinate_values.items()
        if isinstance(value, str) and value
    ))
    if not subject_profile_id or not consumer_profile_id:
        return DimensionAssessment(dimension, Outcome.UNKNOWN, "EFC-PROFILE-001",
                                   "Subject or consumer profile identity is missing.", coordinates=coordinates)
    if not mapping_id or not refs or mapping_outcome is None:
        return DimensionAssessment(dimension, Outcome.UNKNOWN, "EFC-PROFILE-002",
                                   "No explicit mapping result and supporting evidence were supplied.",
                                   coordinates=coordinates)
    try:
        result = Outcome(mapping_outcome)
    except (ValueError, TypeError):
        return _unknown(dimension, "EFC-PROFILE-004", "Profile mapping result is not recognized.")
    if result is Outcome.UNKNOWN:
        return _unknown(dimension, "EFC-PROFILE-005", "Profile mapping evidence leaves compatibility unknown.")
    return DimensionAssessment(dimension, result, "EFC-PROFILE-003",
                               "Explicit subject-to-consumer profile mapping result is evidenced.", refs,
                               conditions=tuple(conditions), blockers=tuple(blockers), mappings=(mapping_id,),
                               coordinates=coordinates)


def assess_governance(
    *, outcome: Outcome | str | None = None, evidence: Iterable[EvidenceReference] = (),
    authority: str | None = None, conditions: Iterable[str] = (), blockers: Iterable[str] = (),
) -> DimensionAssessment:
    """M5 boundary: governance is unknown without M5 authority and evidence."""
    dimension = CompatibilityDimension.GOVERNANCE
    refs, condition_items, blocker_items = tuple(evidence), tuple(conditions), tuple(blockers)
    if authority != "M5" or not refs:
        return _unknown(dimension, "EFC-GOV-001",
                        "Governance result is unknown until authoritative M5 rules and evidence are supplied.")
    try:
        result = Outcome(outcome)
    except (ValueError, TypeError):
        return _unknown(dimension, "EFC-GOV-002", "M5 evidence does not provide a recognized outcome.")
    if result is Outcome.UNKNOWN:
        return _unknown(dimension, "EFC-GOV-003", "M5 evidence explicitly leaves governance compatibility unknown.")
    if result is Outcome.CONDITIONAL and not condition_items:
        return _unknown(dimension, "EFC-GOV-004", "M5 conditional result omitted required conditions.")
    if result is Outcome.BREAKING and not blocker_items:
        return _unknown(dimension, "EFC-GOV-005", "M5 breaking result omitted required blockers.")
    return DimensionAssessment(dimension, result, "EFC-GOV-006",
                               "Governance assessment is supplied by the M5 authority.", refs,
                               condition_items, blocker_items, authority="M5")


def evaluate_compatibility(
    *, subject: ReleaseCoordinates, consumer: ConsumerProfile,
    assessments: Iterable[DimensionAssessment], ruleset_version: str,
) -> CompatibilityReport:
    """Build a deterministic, schema-validated report from exact selected coordinates."""
    if not isinstance(subject, ReleaseCoordinates) or not isinstance(consumer, ConsumerProfile):
        raise CompatibilityError("exact subject release coordinates and consumer profile are required")
    if not isinstance(ruleset_version, str) or not ruleset_version:
        raise CompatibilityError("ruleset version is required")
    by_dimension: dict[CompatibilityDimension, DimensionAssessment] = {}
    for item in assessments:
        if not isinstance(item, DimensionAssessment):
            raise CompatibilityError("assessments must use the shared DimensionAssessment type")
        if item.dimension in by_dimension:
            raise CompatibilityError(f"duplicate assessment for {item.dimension.value}")
        if item.dimension is CompatibilityDimension.GOVERNANCE and item.authority != "M5" and item.outcome is not Outcome.UNKNOWN:
            raise CompatibilityError("non-unknown governance outcomes require explicit M5 authority")
        by_dimension[item.dimension] = item
    for dimension in CompatibilityDimension:
        by_dimension.setdefault(dimension, _unknown(
            dimension, "EFC-EVIDENCE-001", "No assessment/evidence supplied for this dimension."
        ))
    specification = by_dimension[CompatibilityDimension.SPECIFICATION]
    specification_coordinates = dict(specification.coordinates)
    specification_coordinates.setdefault("subjectEfsVersion", subject.efs_version)
    specification_coordinates.setdefault("consumerProfileId", consumer.profile_id)
    specification_coordinates.setdefault("supportedEfsRange", consumer.supported_efs_range)
    by_dimension[CompatibilityDimension.SPECIFICATION] = replace(
        specification, coordinates=tuple(sorted(specification_coordinates.items()))
    )
    ordered = tuple(by_dimension[key] for key in CompatibilityDimension)
    aggregate = max((item.outcome for item in ordered), key=lambda value: _AGGREGATE_RANK[value])
    blockers = tuple(sorted({blocker for item in ordered for blocker in item.blockers}))
    warnings = tuple(sorted({condition for item in ordered for condition in item.conditions}))
    report = CompatibilityReport(_REPORT_VERSION, ruleset_version, subject, consumer, ordered, aggregate, warnings, blockers)
    validate_compatibility_report(report.as_dict())
    return report
