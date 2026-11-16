"""Conformance checks for the normative EFS v1 capability/contract model."""
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts.validate_manifest import validate_report

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/efs/v1/factory-manifest.schema.json"
CATALOG_PATH = ROOT / "conformance/efs/v1/fixture-catalog.json"


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _model_catalog():
    return _json(CATALOG_PATH)["capabilityContractModel"]


def test_contract_model_examples_pass_normative_manifest_validator():
    for relative in _model_catalog()["examples"]:
        report = validate_report(ROOT / relative, SCHEMA_PATH)
        assert report["valid"], (relative, report)
        assert all(value == "passed" for value in report["stages"].values())


def test_contract_model_examples_cover_all_interaction_modes():
    modes = set()
    for relative in _model_catalog()["examples"]:
        manifest = _json(ROOT / relative)
        assert len(manifest["capabilities"]) == 1
        capability = manifest["capabilities"][0]
        assert capability["executionProfiles"]
        selected = set(capability["executionProfiles"])
        profiles = manifest["execution"]["profiles"]
        resolved = [profile for profile in profiles if profile["id"] in selected]
        assert len(resolved) == len(selected)
        for profile in resolved:
            modes.update(profile["modes"])
        # The example deliberately contains no endpoint protocol or address:
        # interaction mode is not a transport selection.
        assert capability["endpoints"] == []
    assert modes == {"sync", "async", "streaming", "event"}


def test_contract_model_error_payload_schema_is_object_schema():
    schema = _json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    error_schema_ref = schema["$defs"]["contractError"]["properties"]["schema"]
    assert error_schema_ref == {"$ref": "#/$defs/objectPayloadSchema"}
    code_schema = schema["$defs"]["contractError"]["properties"]["code"]
    assert code_schema["pattern"] == "^[A-Za-z][A-Za-z0-9._-]{0,127}$"
    object_schema = schema["$defs"]["objectPayloadSchema"]
    assert object_schema["properties"]["type"]["const"] == "object"
    assert "type" in object_schema["required"]

    for relative in _model_catalog()["examples"]:
        manifest = _json(ROOT / relative)
        for capability in manifest["capabilities"]:
            for error in capability["contract"]["errors"]:
                assert re.fullmatch(code_schema["pattern"], error["code"])
                if "schema" in error:
                    assert error["schema"].get("type") == "object"
                    Draft202012Validator.check_schema(error["schema"])


def test_contract_model_vectors_are_complete_and_unambiguous():
    catalog = _model_catalog()
    vectors = _json(ROOT / catalog["vectors"])
    assert vectors["modelVersion"] == "1.0"
    assert vectors["authority"] == "docs/efs-v1-capability-contract-model.md"
    assert vectors["identityRules"]["capabilityId"]["uniqueWithinRelease"] is True
    assert vectors["identityRules"]["contractIdentity"]["tuple"] == [
        "contract.id", "contract.version"
    ]
    assert vectors["payloadRules"]["topLevelType"] == "object"
    assert vectors["errorRules"]["uniqueWithinContract"] is True
    assert vectors["errorRules"]["duplicateCodeExpectedDiagnostic"] == (
        "EFS_CONTRACT_ERROR_CODE_DUPLICATE"
    )
    assert vectors["transportIndependence"]["modeIsTransport"] is False
    semantic = vectors["semanticVectors"]
    ids = [item["id"] for item in semantic]
    assert len(ids) == len(set(ids))
    assert {
        "capability-id-duplicate-exact",
        "contract-id-not-dereferenced",
        "error-code-duplicate",
        "error-schema-object",
        "execution-profile-unresolved",
        "mode-does-not-select-transport",
        "undeclared-guarantee",
    } <= set(ids)
    assert any(
        item.get("diagnostic") == "EFS_CAPABILITY_ID_DUPLICATE"
        for item in semantic
    )
    assert any(
        item.get("diagnostic") == "EFS_CAPABILITY_EXECUTION_PROFILE_UNRESOLVED"
        for item in semantic
    )


def test_contract_model_acceptance_registry_maps_to_executable_tests():
    catalog = _model_catalog()
    acceptance = _json(ROOT / catalog["acceptance"])
    assert acceptance["issue"] == "PSI-42"
    assert acceptance["normativeDocument"] == "docs/efs-v1-capability-contract-model.md"
    tests = {
        "test_contract_model_examples_pass_normative_manifest_validator",
        "test_contract_model_examples_cover_all_interaction_modes",
        "test_contract_model_error_payload_schema_is_object_schema",
        "test_contract_model_vectors_are_complete_and_unambiguous",
        "test_contract_model_acceptance_registry_maps_to_executable_tests",
    }
    criteria = acceptance["acceptanceCriteria"]
    assert [item["id"] for item in criteria] == [
        f"PSI42-AC-{number:02d}" for number in range(1, 9)
    ]
    for criterion in criteria:
        assert criterion["tests"]
        assert set(criterion["tests"]) <= tests
        assert criterion["requirement"]
