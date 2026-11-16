# ruff: noqa: I001
import json
import pytest

from efs.compatibility import (
    CompatibilityDimension,
    CompatibilityError,
    ConsumerProfile,
    DimensionAssessment,
    EvidenceReference,
    Outcome,
    ReleaseCoordinates,
    assess_contract_change,
    assess_governance,
    assess_profile_mapping,
    assess_specification,
    evaluate_compatibility,
)


EVIDENCE = (EvidenceReference("ev-1", "https://evidence.example/contract", "sha256:abc"),)
SUBJECT = ReleaseCoordinates("urn:publisher:acme", "support", "1.2.3", "efs-jcs-sha256-v1",
                             "SHA-256", "a" * 64, "1.0.0")
CONSUMER = ConsumerProfile("consumer-a", "profile-a", "1", ">=1.0.0 <2.0.0", "runtime-a", ("https-json",))


def test_specification_requires_explicit_range_and_evidence():
    missing = assess_specification(supported_range="", consumer_profile_id="p", range_evaluator_result=True,
                                   evidence=EVIDENCE)
    assert missing.outcome is Outcome.UNKNOWN
    ok = assess_specification(supported_range=">=1.0.0 <2.0.0", consumer_profile_id="p",
                              range_evaluator_result=True, evidence=EVIDENCE)
    assert ok.outcome is Outcome.COMPATIBLE
    assert ok.rule_id == "EFC-SPEC-003"


def test_specification_range_mismatch_is_breaking_not_unknown():
    result = assess_specification(supported_range="<1.0.0", consumer_profile_id="p",
                                  range_evaluator_result=False, evidence=EVIDENCE)
    assert result.outcome is Outcome.BREAKING
    assert result.blockers == ("unsupported-efs-version",)


def test_contract_versions_are_opaque_and_definition_evidence_drives_result():
    same = assess_contract_change(capability_id="cap", contract_id="c", previous_version="VNext", selected_version="VNext",
                                  change_classification="unchanged", evidence=EVIDENCE)
    assert same.outcome is Outcome.COMPATIBLE
    assert dict(same.coordinates)["capabilityId"] == "cap"
    changed = assess_contract_change(capability_id="cap", contract_id="c", previous_version="2026-Q4", selected_version="vNext",
                                     change_classification="compatible-additive", evidence=EVIDENCE)
    assert changed.outcome is Outcome.COMPATIBLE
    unknown = assess_contract_change(capability_id="cap", contract_id="c", previous_version="1.0.0", selected_version="2.0.0",
                                     change_classification=None)
    assert unknown.outcome is Outcome.UNKNOWN
    assert "SemVer" not in unknown.explanation


def test_runtime_and_protocol_need_explicit_mapping_evidence():
    for dimension in (CompatibilityDimension.RUNTIME, CompatibilityDimension.PROTOCOL):
        absent = assess_profile_mapping(dimension, subject_profile_id="a", consumer_profile_id="b",
                                        mapping_id=None, mapping_outcome=None, evidence=())
        assert absent.outcome is Outcome.UNKNOWN
        mapped = assess_profile_mapping(dimension, subject_profile_id="a", consumer_profile_id="b",
                                        mapping_id="mapping-1", mapping_outcome=Outcome.COMPATIBLE, evidence=EVIDENCE)
        assert mapped.outcome is Outcome.COMPATIBLE


def test_governance_is_unknown_without_m5_authority_and_evidence():
    assert assess_governance(outcome=Outcome.COMPATIBLE, evidence=EVIDENCE, authority="M4").outcome is Outcome.UNKNOWN
    assert assess_governance(outcome=Outcome.COMPATIBLE, evidence=EVIDENCE, authority="M5").outcome is Outcome.COMPATIBLE
    assert assess_governance(outcome=Outcome.CONDITIONAL, evidence=EVIDENCE, authority="M5").outcome is Outcome.UNKNOWN


def test_aggregate_is_conservative_and_missing_evidence_is_unknown():
    spec = assess_specification(supported_range="*", consumer_profile_id="p", range_evaluator_result=True,
                                evidence=EVIDENCE)
    report = evaluate_compatibility(subject=SUBJECT, consumer=CONSUMER,
                                    assessments=[spec], ruleset_version="efs-compat-1")
    assert report.outcome is Outcome.UNKNOWN
    assert len(report.assessments) == len(CompatibilityDimension)
    assert all(item.outcome is Outcome.UNKNOWN for item in report.assessments
               if item.dimension is not CompatibilityDimension.SPECIFICATION)


def test_breaking_dominates_other_outcomes():
    results = [assess_specification(supported_range="<1", consumer_profile_id="p",
                                    range_evaluator_result=False, evidence=EVIDENCE),
               assess_governance(outcome=Outcome.COMPATIBLE, evidence=EVIDENCE, authority="M5")]
    report = evaluate_compatibility(subject=SUBJECT, consumer=CONSUMER,
                                    assessments=results, ruleset_version="1")
    assert report.outcome is Outcome.BREAKING


def test_duplicate_dimensions_and_unauthorized_governance_are_rejected():
    item = assess_specification(supported_range="*", consumer_profile_id="p", range_evaluator_result=True,
                                evidence=EVIDENCE)
    with pytest.raises(CompatibilityError, match="duplicate"):
        evaluate_compatibility(subject=SUBJECT, consumer=CONSUMER, assessments=[item, item], ruleset_version="1")
    forged = DimensionAssessment(CompatibilityDimension.GOVERNANCE, Outcome.COMPATIBLE,
                                 "X", "forged", EVIDENCE)
    with pytest.raises(CompatibilityError, match="M5"):
        evaluate_compatibility(subject=SUBJECT, consumer=CONSUMER, assessments=[forged], ruleset_version="1")


def test_report_is_deterministic_and_retains_exact_coordinates():
    assessments = [assess_specification(supported_range=">=1 <2", consumer_profile_id="p",
                                        range_evaluator_result=True, evidence=EVIDENCE),
                   assess_governance()]
    first = evaluate_compatibility(subject=SUBJECT, consumer=CONSUMER, assessments=assessments,
                                   ruleset_version="efs-compat-1")
    second = evaluate_compatibility(subject=SUBJECT, consumer=CONSUMER, assessments=reversed(assessments),
                                    ruleset_version="efs-compat-1")
    assert first.canonical_json() == second.canonical_json()
    assert first.fingerprint == second.fingerprint
    payload = json.loads(first.canonical_json())
    assert payload["subject"]["releaseVersion"] == "1.2.3"
    assert payload["subject"]["digest"]["value"] == "a" * 64
    assert payload["outcome"] == "unknown"


def test_conditional_requires_actionable_conditions():
    with pytest.raises(CompatibilityError, match="conditions"):
        DimensionAssessment(CompatibilityDimension.PROTOCOL, Outcome.CONDITIONAL, "R", "needs mapping")
