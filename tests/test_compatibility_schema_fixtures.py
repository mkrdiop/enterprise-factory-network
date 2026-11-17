"""Portable PSI-49 report-schema fixtures and engine/schema consistency checks."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from efs.compatibility import (
    CompatibilityDimension,
    CompatibilityError,
    ConsumerProfile,
    EvidenceReference,
    ReleaseCoordinates,
    assess_specification,
    evaluate_compatibility,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "conformance/efs/v1/compatibility-report-fixtures"
SCHEMA_PATH = ROOT / "conformance/efs/v1/compatibility-report.schema.json"


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_compatibility_report_dimension_fixtures_are_schema_conformant():
    schema = _json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    positive = sorted((FIXTURES / "valid").glob("*.json"))
    negative = sorted((FIXTURES / "invalid").glob("*.json"))
    assert [path.name for path in positive] == ["all-five-dimensions.json"]
    assert len(negative) >= 7

    for path in positive:
        errors = list(validator.iter_errors(_json(path)))
        assert not errors, (path.name, [error.message for error in errors])

    for path in negative:
        assert not validator.is_valid(_json(path)), path.name


def test_engine_materializes_missing_dimensions_and_rejects_duplicates():
    subject = ReleaseCoordinates(
        "urn:publisher:fixture", "fixture-factory", "1.2.3",
        "efs-jcs-sha256-v1", "SHA-256", "a" * 64, "1.0.0",
    )
    consumer = ConsumerProfile(
        "fixture-consumer", "fixture-profile", "1", "*", "fixture-runtime", ("https-json",),
    )
    evidence = EvidenceReference("fixture-evidence", "https://evidence.example/fixture")
    specification = assess_specification(
        supported_range="*", consumer_profile_id=consumer.profile_id,
        range_evaluator_result=True, evidence=(evidence,),
    )

    report = evaluate_compatibility(
        subject=subject, consumer=consumer, assessments=(specification,),
        ruleset_version="efs-compatibility/1.0",
    )
    payload = report.as_dict()
    schema = _json(SCHEMA_PATH)
    validator = Draft202012Validator(schema)
    assert validator.is_valid(payload)
    assert len(payload["dimensions"]) == 5
    by_dimension = {item["dimension"]: item for item in payload["dimensions"]}
    assert set(by_dimension) == {dimension.value for dimension in CompatibilityDimension}
    assert by_dimension[CompatibilityDimension.SPECIFICATION.value]["outcome"] == "compatible"
    for dimension in CompatibilityDimension:
        if dimension is not CompatibilityDimension.SPECIFICATION:
            assert by_dimension[dimension.value]["outcome"] == "unknown"

    with pytest.raises(CompatibilityError, match="duplicate assessment"):
        evaluate_compatibility(
            subject=subject, consumer=consumer,
            assessments=(specification, specification),
            ruleset_version="efs-compatibility/1.0",
        )
