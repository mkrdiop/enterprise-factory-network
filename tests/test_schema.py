import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/efs/v1/factory-manifest.schema.json"
sys.path.insert(0, str(ROOT / "scripts"))
from validate_manifest import load_json, validate_report, DIALECT

SCHEMA = load_json(SCHEMA_PATH)
Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("fixture", sorted((ROOT / "fixtures/valid").glob("*.json")))
def test_valid_fixture_corpus(fixture):
    report = validate_report(fixture, SCHEMA_PATH)
    assert report["valid"], (fixture.name, report["diagnostics"])
    assert all(value == "passed" for value in report["stages"].values())


@pytest.mark.parametrize("fixture", sorted((ROOT / "fixtures/invalid").glob("*.json")))
def test_invalid_fixture_corpus(fixture):
    report = validate_report(fixture, SCHEMA_PATH)
    assert not report["valid"], fixture.name
    assert report["diagnostics"], fixture.name


def test_schema_is_draft_2020_12():
    assert SCHEMA["$schema"] == DIALECT
    Draft202012Validator.check_schema(SCHEMA)


def test_unknown_core_field_remains_open_pending_governance(tmp_path):
    doc = load_json(ROOT / "fixtures/valid/manifest-minimal.json")
    doc["futureCoreField"] = {"opaque": True}
    path = tmp_path / "unknown-core-field.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert validate_report(path, SCHEMA_PATH)["valid"]


def test_namespaced_extension_payload_is_accepted():
    report = validate_report(ROOT / "fixtures/extensions/manifest-namespaced-extension.json", SCHEMA_PATH)
    assert report["valid"], report["diagnostics"]


def test_execution_branches_are_mutually_exclusive():
    doc = load_json(ROOT / "fixtures/valid/manifest-minimal.json")
    doc["execution"]["profileReferences"] = [{
        "id": "https://profiles.example/p", "version": "1.0.0",
        "digest": {"algorithm": "SHA-256", "value": "opaque"}
    }]
    path = ROOT / "tmp-mixed-execution.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    try:
        report = validate_report(path, SCHEMA_PATH)
        assert not report["valid"]
        assert any(d["code"] == "EFS_SCHEMA_INVALID" for d in report["diagnostics"])
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.parametrize("bad_value", ["2026-13-40T25:61:61Z", "2026-11-16T05:30:00"])
def test_date_time_requires_valid_rfc3339_timestamp_with_timezone(tmp_path, bad_value):
    doc = load_json(ROOT / "fixtures/valid/manifest-minimal.json")
    doc["release"]["createdAt"] = bad_value
    path = tmp_path / "datetime.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    report = validate_report(path, SCHEMA_PATH)
    assert not report["valid"]
    assert any(d["path"] == "/release/createdAt" for d in report["diagnostics"])


@pytest.mark.parametrize("fixture", sorted((ROOT / "fixtures/boundary").glob("*.json")))
def test_boundary_fixture_corpus(fixture):
    report = validate_report(fixture, SCHEMA_PATH)
    assert report["valid"], (fixture.name, report["diagnostics"])


def test_offset_datetime_is_accepted():
    report = validate_report(ROOT / "fixtures/boundary/manifest-offset-datetime.json", SCHEMA_PATH)
    assert report["valid"], report["diagnostics"]


def test_embedded_input_output_and_error_schemas_are_meta_validated(tmp_path):
    doc = load_json(ROOT / "fixtures/valid/manifest-minimal.json")
    doc["capabilities"][0]["contract"]["errors"][0]["schema"] = {"type": "string", "minLength": "bad"}
    path = tmp_path / "invalid-error-schema.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    report = validate_report(path, SCHEMA_PATH)
    assert not report["valid"]
    assert any(d["code"] == "EFS_EMBEDDED_SCHEMA_INVALID" for d in report["diagnostics"])


@pytest.mark.parametrize("ref_keyword", ["$ref", "$dynamicRef"])
def test_remote_and_dynamic_refs_are_rejected(tmp_path, ref_keyword):
    doc = load_json(ROOT / "fixtures/valid/manifest-minimal.json")
    doc["capabilities"][0]["contract"]["inputs"][ref_keyword] = "https://schemas.example/remote.json"
    path = tmp_path / "remote-ref.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    report = validate_report(path, SCHEMA_PATH)
    assert not report["valid"]
    assert any(d["code"] in {"EFS_SCHEMA_REF_REMOTE", "EFS_SCHEMA_REF_UNSUPPORTED"} for d in report["diagnostics"])


def test_duplicate_json_members_are_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"efsVersion":"1","efsVersion":"2"}', encoding="utf-8")
    report = validate_report(path, SCHEMA_PATH)
    assert not report["valid"]
    assert report["stages"]["parsing"] == "failed"
    assert report["diagnostics"][0]["code"] == "EFS_JSON_DUPLICATE_MEMBER"


@pytest.mark.parametrize("fixture", sorted((ROOT / "fixtures/adversarial").glob("*.json")))
def test_adversarial_parser_fixture_corpus(fixture):
    report = validate_report(fixture, SCHEMA_PATH)
    assert not report["valid"]
    assert report["stages"]["parsing"] == "failed"


def test_malformed_json_is_rejected(tmp_path):
    path = tmp_path / "malformed.json"
    path.write_text('{"efsVersion":', encoding="utf-8")
    report = validate_report(path, SCHEMA_PATH)
    assert report["diagnostics"][0]["code"] == "EFS_JSON_INVALID"


def test_invalid_utf8_is_rejected(tmp_path):
    path = tmp_path / "invalid-utf8.json"
    path.write_bytes(b'{"name":"\\xff"}')
    report = validate_report(path, SCHEMA_PATH)
    assert report["diagnostics"][0]["code"] == "EFS_JSON_INVALID_ENCODING"


def test_diagnostics_are_machine_readable_and_deterministic(tmp_path):
    doc = load_json(ROOT / "fixtures/valid/manifest-minimal.json")
    del doc["factory"]["name"]
    doc["release"]["createdAt"] = "not-a-date"
    path = tmp_path / "multiple-errors.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    first = validate_report(path, SCHEMA_PATH)
    second = validate_report(path, SCHEMA_PATH)
    assert first == second
    assert first["diagnostics"]
    assert all(set(d) >= {"code", "stage", "path", "message"} for d in first["diagnostics"])
    assert first["stages"]["embedded_schemas"] == "not_run"


def test_report_marks_dependent_stages_not_run_after_parse_failure(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{", encoding="utf-8")
    report = validate_report(path, SCHEMA_PATH)
    assert report["stages"] == {
        "parsing": "failed", "structural": "not_run",
        "embedded_schemas": "not_run", "profile": "not_run"
    }


def test_local_fragment_schema_reference_is_accepted(tmp_path):
    doc = load_json(ROOT / "fixtures/valid/manifest-minimal.json")
    doc["capabilities"][0]["contract"]["inputs"] = {
        "type": "object",
        "$defs": {"question": {"type": "string"}},
        "properties": {"question": {"$ref": "#/$defs/question"}},
    }
    path = tmp_path / "local-ref.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    report = validate_report(path, SCHEMA_PATH)
    assert report["valid"], report["diagnostics"]


def test_cli_json_report_contract():
    import subprocess
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_manifest.py"),
         str(ROOT / "fixtures/valid/manifest-minimal.json"), "--json"],
        check=True, capture_output=True, text=True,
    )
    report = json.loads(result.stdout)
    assert set(report) == {"conformanceProfile", "schemaDialect", "valid", "stages", "diagnostics"}
    assert report["conformanceProfile"] == "efs-v1"
    assert report["valid"] is True
