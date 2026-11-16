"""Evidence-bound compatibility assessment primitives for Enterprise Factory.

This module consumes exact PSI-46 coordinates. It defines assessment outcomes,
not version dimensions or new version grammars. Governance semantics remain
owned by M5 and are accepted here only as explicitly identified M5 evidence.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable, Mapping


class CompatibilityError(ValueError):
    """Invalid compatibility input or unsupported inference."""


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


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """Pointer to evidence; the report does not claim that the evidence is trusted."""

    evidence_id: str
    source: str
    digest: str | None = None
    authority: str | None = None
    coordinates: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.source:
            raise CompatibilityError("evidence_id and source must be non-empty exact strings")


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

    def as_dict(self) -> dict[str, str]:
        return {
            "publisherId": self.publisher_id,
            "factoryId": self.factory_id,
            "releaseVersion": self.release_version,
            "digest": {"profile": self.digest_profile, "algorithm": self.digest_algorithm,
                       "value": self.digest_value},
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
        if not all(isinstance(value, str) and value for value in (
            self.consumer_id, self.profile_id, self.profile_version,
            self.supported_efs_range, self.runtime_profile_id,
        )):
            raise CompatibilityError("consumer identity and explicit profile/range fields are required")


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

    def __post_init__(self) -> None:
        if not self.rule_id or not self.explanation:
            raise CompatibilityError("each assessment requires a stable rule ID and explanation")
        if self.outcome is Outcome.CONDITIONAL and not self.conditions:
            raise CompatibilityError("conditional assessment must state its unmet conditions")
        if self.outcome in (Outcome.COMPATIBLE, Outcome.BREAKING) and not self.evidence:
            raise CompatibilityError("compatible/breaking conclusions require explicit evidence")
        if self.outcome is Outcome.BREAKING and not self.blockers:
            raise CompatibilityError("breaking assessment must identify blockers")


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

    def as_dict(self) -> dict:
        return {
            "reportVersion": self.report_version,
            "rulesetVersion": self.ruleset_version,
            "subject": self.subject.as_dict(),
            "consumer": asdict(self.consumer),
            "dimensions": [
                {
                    "dimension": item.dimension.value,
                    "outcome": item.outcome.value,
                    "ruleId": item.rule_id,
                    "explanation": item.explanation,
                    "evidence": [asdict(ref) for ref in item.evidence],
                    "conditions": list(item.conditions),
                    "blockers": list(item.blockers),
                    "mappings": list(item.mappings),
                    "authority": item.authority,
                    "coordinates": dict(item.coordinates),
                }
                for item in sorted(self.assessments, key=lambda result: result.dimension.value)
            ],
            "outcome": self.outcome.value,
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
        }

    def canonical_json(self) -> str:
        """Stable report core: sorted keys, compact UTF-8 JSON, no observation time."""
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _unknown(dimension: CompatibilityDimension, rule_id: str, reason: str) -> DimensionAssessment:
    return DimensionAssessment(dimension, Outcome.UNKNOWN, rule_id, reason)


def assess_specification(
    *, supported_range: str, consumer_profile_id: str,
    range_evaluator_result: bool | None, evidence: Iterable[EvidenceReference] = (),
) -> DimensionAssessment:
    """Consume a result from the PSI-47 SemVer range evaluator; do not parse versions here."""
    if not supported_range or not consumer_profile_id:
        return _unknown(CompatibilityDimension.SPECIFICATION, "EFC-SPEC-001",
                        "No explicit consumer EFS support range/profile was supplied.")
    refs = tuple(evidence)
    if range_evaluator_result is None or not refs:
        return _unknown(CompatibilityDimension.SPECIFICATION, "EFC-SPEC-002",
                        "EFS range evaluation or its supporting evidence is unavailable.")
    if range_evaluator_result:
        return DimensionAssessment(CompatibilityDimension.SPECIFICATION, Outcome.COMPATIBLE,
                                   "EFC-SPEC-003", "Subject EFS version is within the declared consumer range.", refs)
    return DimensionAssessment(CompatibilityDimension.SPECIFICATION, Outcome.BREAKING,
                               "EFC-SPEC-004", "Subject EFS version is outside the declared consumer range.",
                               refs, blockers=("unsupported-efs-version",))


def assess_contract_change(
    *, capability_id: str, contract_id: str, previous_version: str, selected_version: str,
    change_classification: str | None, evidence: Iterable[EvidenceReference] = (),
) -> DimensionAssessment:
    """Assess contract definitions/evidence; contract versions are never parsed or ordered."""
    dimension = CompatibilityDimension.FACTORY_CONTRACT
    if not all(isinstance(value, str) and value for value in (capability_id, contract_id, previous_version, selected_version)):
        return _unknown(dimension, "EFC-CONTRACT-001", "Exact capability/contract coordinate is incomplete.")
    refs = tuple(evidence)
    coordinate = (("capabilityId", capability_id), ("contractId", contract_id),
                  ("previousContractVersion", previous_version), ("selectedContractVersion", selected_version))
    if previous_version == selected_version:
        if not refs:
            return _unknown(dimension, "EFC-CONTRACT-002",
                            "Exact contract version matches, but definition identity/evidence is absent.")
        return DimensionAssessment(dimension, Outcome.COMPATIBLE, "EFC-CONTRACT-003",
                                   "Exact opaque contract version matches and definition evidence was supplied.", refs,
                                   coordinates=coordinate)
    if not refs or change_classification is None:
        return _unknown(dimension, "EFC-CONTRACT-004",
                        "Contract version differs; no explicit definition-change classification/evidence was supplied.")
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
    evidence: Iterable[EvidenceReference] = (),
) -> DimensionAssessment:
    """Evaluate runtime/protocol only from explicit profiles and a named mapping."""
    if dimension not in (CompatibilityDimension.RUNTIME, CompatibilityDimension.PROTOCOL):
        raise CompatibilityError("profile mapping is valid only for runtime or protocol dimensions")
    refs = tuple(evidence)
    if not subject_profile_id or not consumer_profile_id:
        return _unknown(dimension, "EFC-PROFILE-001", "Subject or consumer profile identity is missing.")
    if not mapping_id or not refs:
        return _unknown(dimension, "EFC-PROFILE-002",
                        "No explicit profile mapping and supporting evidence were supplied.")
    return DimensionAssessment(dimension, Outcome.COMPATIBLE, "EFC-PROFILE-003",
                               "Explicit subject-to-consumer profile mapping is evidenced.", refs,
                               mappings=(mapping_id,))


def assess_governance(
    *, outcome: Outcome | str | None = None, evidence: Iterable[EvidenceReference] = (),
    authority: str | None = None, conditions: Iterable[str] = (), blockers: Iterable[str] = (),
) -> DimensionAssessment:
    """M5 boundary: do not synthesize governance semantics before M5 authority exists."""
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
    """Build a deterministic report; absent dimensions are explicitly unknown."""
    if not ruleset_version:
        raise CompatibilityError("ruleset version is required")
    by_dimension: dict[CompatibilityDimension, DimensionAssessment] = {}
    for item in assessments:
        if item.dimension in by_dimension:
            raise CompatibilityError(f"duplicate assessment for {item.dimension.value}")
        if item.dimension is CompatibilityDimension.GOVERNANCE and item.authority != "M5" and item.outcome is not Outcome.UNKNOWN:
            raise CompatibilityError("non-unknown governance outcomes require explicit M5 authority")
        by_dimension[item.dimension] = item
    for dimension in CompatibilityDimension:
        by_dimension.setdefault(dimension, _unknown(
            dimension, "EFC-EVIDENCE-001", "No assessment/evidence supplied for this dimension."
        ))
    ordered = tuple(by_dimension[key] for key in CompatibilityDimension)
    aggregate = max((item.outcome for item in ordered), key=lambda value: _AGGREGATE_RANK[value])
    blockers = tuple(sorted({blocker for item in ordered for blocker in item.blockers}))
    warnings = tuple(sorted({condition for item in ordered for condition in item.conditions}))
    return CompatibilityReport("1.0", ruleset_version, subject, consumer, ordered, aggregate, warnings, blockers)
