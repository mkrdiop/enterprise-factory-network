"""Machine-enforced fixture inventory and AC-01–AC-15 traceability."""
import ast
import base64
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys_path = ROOT / "scripts"
sys.path.insert(0, str(sys_path))
from validate_manifest import validate_report

CATALOG_PATH = ROOT / "conformance/efs/v1/fixture-catalog.json"
AC_PATH = ROOT / "conformance/efs/v1/acceptance-criteria.json"
DIAGNOSTICS_PATH = ROOT / "conformance/efs/v1/diagnostic-catalog.json"
REPORT_SCHEMA_PATH = ROOT / "conformance/efs/v1/report-schema.json"
SCHEMA_PATH = ROOT / "schemas/efs/v1/factory-manifest.schema.json"


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _test_function_names():
    names = set()
    for path in (ROOT / "tests").glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names.update(node.name for node in ast.walk(tree)
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return names


def test_catalogued_manifest_fixtures():
    catalog = _json(CATALOG_PATH)
    for group in catalog["manifestGroups"]:
        paths = sorted(ROOT.glob(group["glob"]))
        assert paths, f'fixture group {group["id"]} is empty'
        for fixture in paths:
            report = validate_report(fixture, SCHEMA_PATH)
            assert report["valid"] is group["expectedValid"], (
                group["id"], fixture.relative_to(ROOT).as_posix(), report
            )
            if group["expectedValid"]:
                assert all(stage == "passed" for stage in report["stages"].values())
            else:
                assert any(stage == "failed" for stage in report["stages"].values())
                if group["stage"] in report["stages"]:
                    assert report["stages"][group["stage"]] == "failed"


def test_catalogued_raw_parser_inputs(tmp_path):
    catalog = _json(CATALOG_PATH)
    for item in catalog["rawInputs"]:
        source = ROOT / item["path"]
        encoded = source.read_bytes()
        raw = base64.b64decode(encoded.strip(), validate=True) if item["encoding"] == "base64" else encoded
        candidate = tmp_path / item["id"]
        candidate.write_bytes(raw)
        report = validate_report(candidate, SCHEMA_PATH)
        assert not report["valid"], item["id"]
        assert report["stages"]["parsing"] == "failed", item["id"]
        assert item["expectedCode"] in {d["code"] for d in report["diagnostics"]}, item["id"]


def test_catalog_and_acceptance_registry_are_complete():
    catalog = _json(CATALOG_PATH)
    registry = _json(AC_PATH)
    diagnostic_catalog = _json(DIAGNOSTICS_PATH)
    test_names = _test_function_names()

    assert catalog["catalogVersion"] == "1.0"
    group_ids = {group["id"] for group in catalog["manifestGroups"]}
    assert {"valid", "invalid", "boundary", "extensions", "adversarial-existing"} <= group_ids
    assert len({item["id"] for item in catalog["rawInputs"]}) == len(catalog["rawInputs"])
    for group in catalog["manifestGroups"]:
        assert list(ROOT.glob(group["glob"])), f'empty fixture group: {group["id"]}'
    for item in catalog["rawInputs"]:
        assert (ROOT / item["path"]).is_file(), item["path"]

    workflow = (ROOT / ".github/workflows/efs-schema.yml").read_text(encoding="utf-8")
    for version in ('"3.11"', '"3.12"', '"3.13"'):
        assert version in workflow
    assert "python -m pytest -q" in workflow
    assert (ROOT / "docs/psi-36-conformance.md").is_file()
    assert (ROOT / "docs/efs-v1-conformance.md").is_file()

    criteria = registry["acceptanceCriteria"]
    assert [item["id"] for item in criteria] == [f"AC-{n:02d}" for n in range(1, 16)]
    for criterion in criteria:
        assert criterion["requirement"]
        assert criterion["tests"], criterion["id"]
        assert set(criterion["tests"]) <= test_names, criterion["id"]
        assert set(criterion["fixtures"]) <= (group_ids | {"rawInputs"}), criterion["id"]

    codes = {item["code"] for item in diagnostic_catalog["diagnostics"]}
    assert len(codes) == len(diagnostic_catalog["diagnostics"])
    assert {"EFS_JSON_INVALID", "EFS_JSON_INVALID_ENCODING",
            "EFS_JSON_DUPLICATE_MEMBER", "EFS_SCHEMA_REQUIRED",
            "EFS_SCHEMA_TYPE", "EFS_SCHEMA_ENUM", "EFS_SCHEMA_FORMAT",
            "EFS_SCHEMA_CONSTRAINT", "EFS_EMBEDDED_SCHEMA_INVALID",
            "EFS_SCHEMA_REF_REMOTE", "EFS_SCHEMA_REF_UNSUPPORTED",
            "EFS_PROFILE_INVARIANT_FAILED"} <= codes


def test_conformance_report_claim_boundary():
    source = (ROOT / "scripts/validate_manifest.py").read_text(encoding="utf-8")
    docs = (ROOT / "docs/efs-v1-conformance.md").read_text(encoding="utf-8")
    for phrase in ("does not verify", "signatures", "policy", "runtime"):
        assert phrase.lower() in source.lower() + docs.lower()


def test_report_schema_validates_reference_report():
    report = validate_report(ROOT / "fixtures/valid/manifest-minimal.json", SCHEMA_PATH)
    report_schema = _json(REPORT_SCHEMA_PATH)
    Draft202012Validator.check_schema(report_schema)
    Draft202012Validator(report_schema).validate(report)
