import json, sys
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parents[1]
SCHEMA_PATH=ROOT/"schemas/efs/v1/factory-manifest.schema.json"
sys.path.insert(0,str(ROOT/"scripts"))
from validate_manifest import validate
SCHEMA=json.loads(SCHEMA_PATH.read_text())
Draft202012Validator.check_schema(SCHEMA)

@pytest.mark.parametrize("fixture",sorted((ROOT/"fixtures/valid").glob("*.json")))
def test_valid_fixtures(fixture): assert validate(fixture,SCHEMA_PATH)==[]

@pytest.mark.parametrize("fixture",sorted((ROOT/"fixtures/invalid").glob("*.json")))
def test_invalid_fixtures(fixture): assert validate(fixture,SCHEMA_PATH)

def test_unknown_core_field_behavior_is_not_decided():
    doc=json.loads((ROOT/"fixtures/valid/manifest-minimal.json").read_text())
    doc["futureCoreField"]={"opaque":True}
    assert not list(Draft202012Validator(SCHEMA).iter_errors(doc))

def test_execution_branches_are_exclusive():
    doc=json.loads((ROOT/"fixtures/valid/manifest-minimal.json").read_text())
    doc["execution"]["profileReferences"]=[{"id":"https://x.example/p","version":"1","digest":{"algorithm":"SHA-256","value":"x"}}]
    assert list(Draft202012Validator(SCHEMA).iter_errors(doc))

def test_schema_dialect():
    assert SCHEMA["$schema"]=="https://json-schema.org/draft/2020-12/schema"
