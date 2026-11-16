import json, sys
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parents[1]
SCHEMA_PATH=ROOT/"schemas/efs/v1/factory-manifest.schema.json"
sys.path.insert(0,str(ROOT/"scripts"))
from validate_manifest import validate, load
SCHEMA=load(SCHEMA_PATH)
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR=Draft202012Validator(SCHEMA)

@pytest.mark.parametrize("fixture",sorted((ROOT/"fixtures/valid").glob("*.json")))
def test_valid_fixtures(fixture):
    assert validate(fixture,SCHEMA_PATH)==[]

@pytest.mark.parametrize("fixture",sorted((ROOT/"fixtures/invalid").glob("*.json")))
def test_invalid_fixtures(fixture):
    assert validate(fixture,SCHEMA_PATH), fixture.name

def test_unknown_core_field_behavior_is_not_decided():
    doc=load(ROOT/"fixtures/valid/manifest-minimal.json")
    doc["futureCoreField"]={"opaque":True}
    assert not list(VALIDATOR.iter_errors(doc))

def test_execution_branches_are_mutually_exclusive():
    doc=load(ROOT/"fixtures/valid/manifest-minimal.json")
    doc["execution"]["profileReferences"]=[{"id":"https://x.example/p","version":"1","digest":{"algorithm":"SHA-256","value":"x"}}]
    assert list(VALIDATOR.iter_errors(doc))

def test_contract_schema_rejects_absolute_remote_reference(tmp_path):
    doc=load(ROOT/"fixtures/valid/manifest-minimal.json")
    doc["capabilities"][0]["contract"]["inputs"]["$ref"]="https://attacker.example/schema.json"
    path=tmp_path/"remote-ref.json"
    path.write_text(json.dumps(doc),encoding="utf-8")
    assert any("$ref" in e for e in validate(path,SCHEMA_PATH))

def test_contract_schema_rejects_dynamic_reference(tmp_path):
    doc=load(ROOT/"fixtures/valid/manifest-minimal.json")
    doc["capabilities"][0]["contract"]["inputs"]["$dynamicRef"]="#/$defs/value"
    path=tmp_path/"dynamic-ref.json"
    path.write_text(json.dumps(doc),encoding="utf-8")
    assert any("dynamic-reference" in e for e in validate(path,SCHEMA_PATH))

def test_embedded_schema_meta_validation(tmp_path):
    doc=load(ROOT/"fixtures/valid/manifest-minimal.json")
    doc["capabilities"][0]["contract"]["inputs"]["minLength"]="not-an-integer"
    path=tmp_path/"bad-schema.json"
    path.write_text(json.dumps(doc),encoding="utf-8")
    assert validate(path,SCHEMA_PATH)

def test_duplicate_json_members_are_rejected(tmp_path):
    path=tmp_path/"duplicate.json"
    path.write_text('{"efsVersion":"1","efsVersion":"2"}',encoding="utf-8")
    with pytest.raises(ValueError,match="duplicate JSON object member"):
        load(path)

def test_schema_uses_draft_2020_12():
    assert SCHEMA["$schema"]=="https://json-schema.org/draft/2020-12/schema"


def test_release_created_at_accepts_rfc3339_datetime(tmp_path):
    doc=load(ROOT/"fixtures/valid/manifest-minimal.json")
    doc["release"]["createdAt"]="2026-11-16T05:30:00Z"
    path=tmp_path/"valid-datetime.json"
    path.write_text(json.dumps(doc),encoding="utf-8")
    assert validate(path,SCHEMA_PATH)==[]

def test_release_created_at_rejects_invalid_datetime(tmp_path):
    doc=load(ROOT/"fixtures/valid/manifest-minimal.json")
    doc["release"]["createdAt"]="2026-13-40T25:61:61Z"
    path=tmp_path/"invalid-datetime.json"
    path.write_text(json.dumps(doc),encoding="utf-8")
    errors=validate(path,SCHEMA_PATH)
    assert errors
    assert any("date-time" in error for error in errors)

def test_release_created_at_rejects_datetime_without_timezone(tmp_path):
    doc=load(ROOT/"fixtures/valid/manifest-minimal.json")
    doc["release"]["createdAt"]="2026-11-16T05:30:00"
    path=tmp_path/"timezone-less-datetime.json"
    path.write_text(json.dumps(doc),encoding="utf-8")
    errors=validate(path,SCHEMA_PATH)
    assert errors
    assert any("date-time" in error for error in errors)
