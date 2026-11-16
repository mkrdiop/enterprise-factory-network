# ruff: noqa: I001
import json

import pytest

from efs.compatibility import (
    CompatibilityDimension,
    CompatibilityError,
    ConsumerProfile,
    EvidenceReference,
    Outcome,
    ReleaseCoordinates,
    assess_contract_change,
    assess_governance,
    assess_profile_mapping,
    assess_specification,
    evaluate_compatibility,
    validate_compatibility_report,
)
from efs.versioning import (
    ReleaseCoordinate,
    VersionError,
    require_exact_release_selection,
)


EVIDENCE_A = EvidenceReference("evidence-a", "https://evidence.example/a", "sha256:aaa", "PSI-47")
EVIDENCE_B = EvidenceReference("evidence-b", "https://evidence.example/b", "sha256:bbb", "PSI-48")
SUBJECT = ReleaseCoordinates(
    "urn:publisher:acme", "support", "1.2.3+build.7",
    "efs-jcs-sha256-v1", "SHA-256", "a" * 64, "1.0.0",
)
CONSUMER = ConsumerProfile("consumer-a", "profile-a", "1", ">=1.0.0 <2.0.0", "runtime-a", ("https-json",))


def make_report():
    assessments = [
        assess_specification(supported_range=">=1.0.0 <2.0.0", consumer_profile_id="profile-a",
                             range_evaluator_result=True, evidence=(EVIDENCE_A,)),
        assess_contract_change(capability_id="search", contract_id="search-input",
                               previous_version="2026-Q4", selected_version="2026-Q4",
                               change_classification="unchanged", evidence=(EVIDENCE_B,)),
        assess_profile_mapping(CompatibilityDimension.RUNTIME, subject_profile_id="runtime-2",
                               consumer_profile_id="runtime-a", mapping_id="runtime-adapter-v1",
                               mapping_outcome=Outcome.CONDITIONAL, evidence=(EVIDENCE_A,),
                               conditions=("install-runtime-adapter",)),
        assess_profile_mapping(CompatibilityDimension.PROTOCOL, subject_profile_id="https-json",
                               consumer_profile_id="https-json", mapping_id="https-json-v1",
                               mapping_outcome=Outcome.COMPATIBLE, evidence=(EVIDENCE_B,)),
        assess_governance(),
    ]
    return evaluate_compatibility(subject=SUBJECT, consumer=CONSUMER, assessments=assessments,
                                  ruleset_version="efs-compatibility/1.0")


def test_report_schema_and_provenance_are_present():
    report = make_report()
    payload = report.as_dict()
    validate_compatibility_report(payload)
    assert payload["reportVersion"] == "1.0"
    assert payload["rulesetVersion"] == "efs-compatibility/1.0"
    assert payload["provenance"]["normativeAuthorities"] == ["PSI-46", "PSI-47", "PSI-48"]
    assert payload["provenance"]["canonicalization"] == "RFC8785"
    assert payload["outcome"] == "unknown"


def test_canonical_report_is_order_independent_and_has_no_volatile_metadata():
    first = make_report()
    second = evaluate_compatibility(subject=SUBJECT, consumer=CONSUMER, assessments=reversed(first.assessments),
                                    ruleset_version="efs-compatibility/1.0")
    assert first.canonical_json() == second.canonical_json()
    assert first.fingerprint == second.fingerprint
    assert "timestamp" not in json.loads(first.canonical_json())
    assert "observedAt" not in json.loads(first.canonical_json())


def test_evidence_and_action_arrays_are_canonicalized_as_sets():
    left = assess_profile_mapping(
        CompatibilityDimension.RUNTIME, subject_profile_id="runtime-2", consumer_profile_id="runtime-a",
        mapping_id="adapter-b", mapping_outcome=Outcome.CONDITIONAL,
        evidence=(EVIDENCE_A, EVIDENCE_B), conditions=("install-b", "install-a"),
    )
    right = assess_profile_mapping(
        CompatibilityDimension.RUNTIME, subject_profile_id="runtime-2", consumer_profile_id="runtime-a",
        mapping_id="adapter-b", mapping_outcome=Outcome.CONDITIONAL,
        evidence=(EVIDENCE_B, EVIDENCE_A), conditions=("install-a", "install-b"),
    )
    one = evaluate_compatibility(subject=SUBJECT, consumer=CONSUMER, assessments=(left,),
                                 ruleset_version="rules-1")
    two = evaluate_compatibility(subject=SUBJECT, consumer=CONSUMER, assessments=(right,),
                                 ruleset_version="rules-1")
    assert one.canonical_json() == two.canonical_json()


def test_schema_rejects_unknown_fields_and_incomplete_coordinates():
    payload = make_report().as_dict()
    payload["subject"]["latest"] = True
    with pytest.raises(CompatibilityError, match="schema violation"):
        validate_compatibility_report(payload)
    payload = make_report().as_dict()
    del payload["subject"]["digest"]["value"]
    with pytest.raises(CompatibilityError, match="schema violation"):
        validate_compatibility_report(payload)


def test_exact_subject_coordinates_and_consumer_ranges_are_preserved():
    payload = make_report().as_dict()
    assert payload["subject"]["releaseVersion"] == "1.2.3+build.7"
    assert payload["subject"]["digest"]["value"] == "a" * 64
    assert payload["subject"]["efsVersion"] == "1.0.0"
    assert payload["consumer"]["supportedEfsRange"] == ">=1.0.0 <2.0.0"
    assert payload["consumer"]["protocolProfileIds"] == ["https-json"]
    dimensions = {item["dimension"]: item for item in payload["dimensions"]}
    assert dimensions["specification"]["coordinates"] == {
        "consumerProfileId": "profile-a",
        "subjectEfsVersion": "1.0.0",
        "supportedEfsRange": ">=1.0.0 <2.0.0",
    }
    assert dimensions["runtime-execution"]["coordinates"] == {
        "consumerProfileId": "runtime-a",
        "mappingId": "runtime-adapter-v1",
        "subjectProfileId": "runtime-2",
    }


def test_opaque_contract_version_is_not_normalized_or_parsed():
    assessment = assess_contract_change(
        capability_id="cap", contract_id="contract", previous_version="VNext",
        selected_version="vnext", change_classification=None,
    )
    report = evaluate_compatibility(subject=SUBJECT, consumer=CONSUMER, assessments=(assessment,),
                                    ruleset_version="rules-1")
    item = next(row for row in report.as_dict()["dimensions"]
                if row["dimension"] == "factory-release-capability-contract")
    assert item["coordinates"]["previousContractVersion"] == "VNext"
    assert item["coordinates"]["selectedContractVersion"] == "vnext"
    assert item["outcome"] == "unknown"


def test_unknown_or_non_boolean_range_evaluator_result_stays_unknown():
    for result in (None, "false", 0):
        assessment = assess_specification(
            supported_range="not-interpreted-here", consumer_profile_id="profile-a",
            range_evaluator_result=result, evidence=(EVIDENCE_A,),
        )
        assert assessment.outcome is Outcome.UNKNOWN


def test_breaking_and_conditional_outcomes_keep_diagnostics_in_report():
    breaking = assess_specification(supported_range="<1.0.0", consumer_profile_id="profile-a",
                                    range_evaluator_result=False, evidence=(EVIDENCE_A,))
    conditional = assess_profile_mapping(
        CompatibilityDimension.RUNTIME, subject_profile_id="runtime-2", consumer_profile_id="runtime-a",
        mapping_id="adapter-v1", mapping_outcome=Outcome.CONDITIONAL,
        evidence=(EVIDENCE_B,), conditions=("install-adapter",),
    )
    report = evaluate_compatibility(subject=SUBJECT, consumer=CONSUMER, assessments=(breaking, conditional),
                                    ruleset_version="rules-1")
    payload = report.as_dict()
    assert report.outcome is Outcome.BREAKING
    assert payload["blockers"] == ["unsupported-efs-version"]
    assert "install-adapter" in payload["warnings"]


def test_equal_precedence_release_labels_are_never_implicitly_selected():
    first = ReleaseCoordinate("urn:publisher:acme", "support", "1.2.3+one", "efs-jcs-sha256-v1",
                              "SHA-256", "a" * 64)
    second = ReleaseCoordinate("urn:publisher:acme", "support", "1.2.3+two", "efs-jcs-sha256-v1",
                               "SHA-256", "b" * 64)
    with pytest.raises(VersionError, match="equal-precedence"):
        require_exact_release_selection([first, second])


def test_report_is_derived_and_does_not_mutate_source_coordinates():
    report = make_report()
    assert report.subject is SUBJECT
    assert report.subject.release_version == "1.2.3+build.7"
    assert report.subject.digest_value == "a" * 64
