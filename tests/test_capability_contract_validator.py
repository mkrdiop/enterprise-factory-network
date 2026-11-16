"""PSI-43 executable capability contract definition and payload conformance."""
import copy
import json
from pathlib import Path

from registry.capability_contracts import ContractCoordinate, validate_contract_payload
from registry.publication_service import (
    ManifestValidationError,
    RegistryPublicationService,
)
from scripts.validate_manifest import validate_report

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/efs/v1/factory-manifest.schema.json"
FIXTURE = ROOT / "fixtures/valid/capability-contract-sync.json"


def _manifest():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _report(tmp_path, manifest):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return validate_report(path, SCHEMA)


def _coordinate(manifest):
    digest = manifest["release"]["digest"]
    return ContractCoordinate(
        publisher_id=manifest["publisher"]["id"],
        factory_id=manifest["factory"]["id"],
        release_version=manifest["release"]["version"],
        release_digest_profile=digest["profile"],
        release_digest_algorithm=digest["algorithm"],
        release_digest_value=digest["value"],
        capability_id=manifest["capabilities"][0]["id"],
        contract_id=manifest["capabilities"][0]["contract"]["id"],
        contract_version=manifest["capabilities"][0]["contract"]["version"],
    )


def test_duplicate_capability_ids_are_rejected_with_stable_pointer(tmp_path):
    manifest = _manifest()
    manifest["capabilities"].append(copy.deepcopy(manifest["capabilities"][0]))
    report = _report(tmp_path, manifest)
    matches = [d for d in report["diagnostics"] if d["code"] == "EFS_CAPABILITY_ID_DUPLICATE"]
    assert not report["valid"]
    assert len(matches) == 1
    assert matches[0]["path"] == "/capabilities/1/id"
    assert matches[0]["details"]["firstPath"] == "/capabilities/0/id"


def test_duplicate_contract_error_codes_are_exact_and_case_sensitive(tmp_path):
    manifest = _manifest()
    errors = manifest["capabilities"][0]["contract"]["errors"]
    errors.append(copy.deepcopy(errors[0]))
    report = _report(tmp_path, manifest)
    assert "EFS_CONTRACT_ERROR_CODE_DUPLICATE" in {
        item["code"] for item in report["diagnostics"]
    }

    manifest = _manifest()
    errors = manifest["capabilities"][0]["contract"]["errors"]
    errors.append({**copy.deepcopy(errors[0]), "code": errors[0]["code"].lower()})
    report = _report(tmp_path, manifest)
    assert report["valid"]  # IDs compare exactly; no case folding.


def test_capability_execution_profile_must_resolve_exactly(tmp_path):
    manifest = _manifest()
    manifest["capabilities"][0]["executionProfiles"] = ["missing-profile"]
    report = _report(tmp_path, manifest)
    matches = [d for d in report["diagnostics"]
               if d["code"] == "EFS_CAPABILITY_EXECUTION_PROFILE_UNRESOLVED"]
    assert not report["valid"]
    assert len(matches) == 1
    assert matches[0]["path"] == "/capabilities/0/executionProfiles/0"

    manifest["execution"]["profiles"].append(
        {"id": "profile-sync", "modes": ["async"]}
    )
    report = _report(tmp_path, manifest)
    assert "EFS_CAPABILITY_EXECUTION_PROFILE_UNRESOLVED" in {
        item["code"] for item in report["diagnostics"]
    }  # ambiguous duplicate profile IDs are not accepted


def test_schema_reference_profile_rejects_remote_and_unresolved_refs(tmp_path):
    manifest = _manifest()
    manifest["capabilities"][0]["contract"]["inputs"]["properties"]["requestId"] = {
        "$ref": "#/$defs/not-present"
    }
    report = _report(tmp_path, manifest)
    assert "EFS_SCHEMA_REF_UNRESOLVED" in {d["code"] for d in report["diagnostics"]}

    manifest = _manifest()
    manifest["capabilities"][0]["contract"]["inputs"]["properties"]["requestId"] = {
        "$ref": "https://schemas.example.invalid/request.json"
    }
    report = _report(tmp_path, manifest)
    assert "EFS_SCHEMA_REF_REMOTE" in {d["code"] for d in report["diagnostics"]}


def test_valid_local_json_pointer_reference_is_accepted(tmp_path):
    manifest = _manifest()
    schema = manifest["capabilities"][0]["contract"]["inputs"]
    schema["$defs"] = {"requestId": {"type": "string"}}
    schema["properties"]["requestId"] = {"$ref": "#/$defs/requestId"}
    report = _report(tmp_path, manifest)
    assert report["valid"], report


def test_payload_validation_uses_exact_release_contract_and_direction():
    manifest = _manifest()
    coordinate = _coordinate(manifest)
    good = validate_contract_payload(
        manifest, coordinate, "inputs", {"requestId": "req-123"}
    )
    assert good["valid"], good

    bad = validate_contract_payload(
        manifest, coordinate, "inputs", {"requestId": 123}
    )
    assert not bad["valid"]
    assert bad["diagnostics"][0]["code"] == "EFS_CONTRACT_PAYLOAD_INVALID"
    assert bad["diagnostics"][0]["path"] == "/requestId"
    assert "123" not in json.dumps(bad["diagnostics"])  # payload values are not leaked

    wrong_release = ContractCoordinate(
        **{**coordinate.__dict__, "release_version": "latest"}
    ) if hasattr(coordinate, "__dict__") else ContractCoordinate(
        publisher_id=coordinate.publisher_id,
        factory_id=coordinate.factory_id,
        release_version="latest",
        release_digest_profile=coordinate.release_digest_profile,
        release_digest_algorithm=coordinate.release_digest_algorithm,
        release_digest_value=coordinate.release_digest_value,
        capability_id=coordinate.capability_id,
        contract_id=coordinate.contract_id,
        contract_version=coordinate.contract_version,
    )
    rejected = validate_contract_payload(
        manifest, wrong_release, "inputs", {"requestId": "req-123"}
    )
    assert not rejected["valid"]
    assert rejected["diagnostics"][0]["code"] == "EFS_CONTRACT_RELEASE_COORDINATE_MISMATCH"


def test_payload_validation_supports_only_preloaded_local_resource_graph():
    manifest = _manifest()
    schema = manifest["capabilities"][0]["contract"]["inputs"]
    schema["$id"] = "https://schemas.example.test/input.json"
    schema["properties"]["requestId"] = {
        "$ref": "common.json#/$defs/requestId"
    }
    resources = {
        "https://schemas.example.test/common.json": {
            "$id": "https://schemas.example.test/common.json",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {"requestId": {"type": "string", "minLength": 1}},
        }
    }
    result = validate_contract_payload(
        manifest, _coordinate(manifest), "inputs",
        {"requestId": "req-123"}, schema_resources=resources,
    )
    assert result["valid"], result


class _NeverCalled:
    def __getattr__(self, name):
        raise AssertionError(f"{name} must not be called for invalid contracts")


def test_publication_rejects_invalid_contract_before_digest_storage_or_commit():
    manifest = _manifest()
    manifest["capabilities"][0]["contract"]["errors"].append(
        copy.deepcopy(manifest["capabilities"][0]["contract"]["errors"][0])
    )
    service = RegistryPublicationService(
        operation_repository=_NeverCalled(),
        digest_service=_NeverCalled(),
        artifact_store=_NeverCalled(),
        schema_path=SCHEMA,
    )
    try:
        service.publish(json.dumps(manifest).encode("utf-8"), "psi43-invalid-contract")
    except ManifestValidationError as exc:
        assert "EFS_CONTRACT_ERROR_CODE_DUPLICATE" in {
            item["code"] for item in exc.report["diagnostics"]
        }
    else:
        raise AssertionError("invalid contract definition was published")


def test_validator_acceptance_registry_maps_to_executable_tests():
    registry = json.loads(
        (ROOT / "conformance/efs/v1/capability-contract-validator-acceptance.json")
        .read_text(encoding="utf-8")
    )
    names = {
        "test_duplicate_capability_ids_are_rejected_with_stable_pointer",
        "test_duplicate_contract_error_codes_are_exact_and_case_sensitive",
        "test_capability_execution_profile_must_resolve_exactly",
        "test_schema_reference_profile_rejects_remote_and_unresolved_refs",
        "test_valid_local_json_pointer_reference_is_accepted",
        "test_payload_validation_uses_exact_release_contract_and_direction",
        "test_payload_validation_supports_only_preloaded_local_resource_graph",
        "test_declared_error_details_are_validated_by_the_contract_error_schema",
        "test_definition_reference_graph_resolves_only_prebundled_resources",
        "test_duplicate_schema_resource_ids_are_rejected",
        "test_publication_rejects_invalid_contract_before_digest_storage_or_commit",
        "test_validator_acceptance_registry_maps_to_executable_tests",
    }
    criteria = registry["acceptanceCriteria"]
    assert [item["id"] for item in criteria] == [
        f"PSI43-AC-{number:02d}" for number in range(1, 9)
    ]
    for item in criteria:
        assert item["tests"]
        assert set(item["tests"]) <= names


def test_declared_error_details_are_validated_by_the_contract_error_schema():
    manifest = _manifest()
    coordinate = _coordinate(manifest)
    valid = validate_contract_payload(
        manifest, coordinate, "errors", {"message": "bad request"},
        error_code="INVALID_REQUEST",
    )
    assert valid["valid"], valid
    invalid = validate_contract_payload(
        manifest, coordinate, "errors", {"message": 123},
        error_code="INVALID_REQUEST",
    )
    assert not invalid["valid"]
    assert invalid["diagnostics"][0]["code"] == "EFS_CONTRACT_PAYLOAD_INVALID"
    undeclared = validate_contract_payload(
        manifest, coordinate, "errors", {"message": "x"},
        error_code="NOT_DECLARED",
    )
    assert not undeclared["valid"]
    assert undeclared["diagnostics"][0]["code"] == "EFS_CONTRACT_ERROR_CODE_UNDECLARED"


def test_definition_reference_graph_resolves_only_prebundled_resources(tmp_path):
    manifest = _manifest()
    inputs = manifest["capabilities"][0]["contract"]["inputs"]
    outputs = manifest["capabilities"][0]["contract"]["outputs"]
    inputs["$id"] = "https://schemas.example.test/input.json"
    inputs["properties"]["requestId"] = {
        "$ref": "shared.json#/$defs/requestId"
    }
    outputs["$id"] = "https://schemas.example.test/shared.json"
    outputs["$defs"] = {"requestId": {"type": "string", "minLength": 1}}
    report = _report(tmp_path, manifest)
    assert report["valid"], report

    outputs["$id"] = "https://schemas.example.test/different.json"
    report = _report(tmp_path, manifest)
    assert "EFS_SCHEMA_REF_UNRESOLVED" in {
        item["code"] for item in report["diagnostics"]
    }


def test_duplicate_schema_resource_ids_are_rejected(tmp_path):
    manifest = _manifest()
    inputs = manifest["capabilities"][0]["contract"]["inputs"]
    outputs = manifest["capabilities"][0]["contract"]["outputs"]
    inputs["$id"] = "https://schemas.example.test/shared.json"
    outputs["$id"] = "https://schemas.example.test/shared.json"
    report = _report(tmp_path, manifest)
    assert "EFS_SCHEMA_RESOURCE_ID_DUPLICATE" in {
        item["code"] for item in report["diagnostics"]
    }
