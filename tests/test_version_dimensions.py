"""PSI-46 normative version-dimension model and language-neutral vector checks."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docs/efs-v1-version-dimensions.md"
ADR_PATH = ROOT / "docs/adr/ADR-010-efs-v1-version-dimension-model.md"
VECTOR_PATH = ROOT / "conformance/efs/v1/version-dimension-vectors.json"
ACCEPTANCE_PATH = ROOT / "conformance/efs/v1/version-dimension-acceptance.json"
CATALOG_PATH = ROOT / "conformance/efs/v1/fixture-catalog.json"


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _vectors():
    return _json(VECTOR_PATH)


def _all_vectors():
    vectors = _vectors()
    return {
        item["id"]: item
        for group in ("semverVectors", "semanticVectors")
        for item in vectors[group]
    }


def test_version_dimensions_are_complete_and_unique():
    dimensions = _vectors()["dimensions"]
    assert [item["id"] for item in dimensions] == [
        "efs-specification",
        "factory-release",
        "capability-contract",
        "implementation-build",
    ]
    assert len({item["field"] for item in dimensions}) == 4
    assert all(item["owner"] and item["scope"] and item["grammar"] and item["comparison"] for item in dimensions)


def test_semver_is_limited_to_spec_and_factory_release():
    dimensions = {item["id"]: item for item in _vectors()["dimensions"]}
    assert dimensions["efs-specification"]["grammar"] == "semver-2.0.0"
    assert dimensions["factory-release"]["grammar"] == "semver-2.0.0"
    assert dimensions["capability-contract"]["grammar"] == "opaque-non-empty-string"
    assert dimensions["implementation-build"]["grammar"] == "producer-defined-not-efs-governed"
    vectors = _all_vectors()
    for vector_id in ("SEM-001", "SEM-002", "SEM-005", "SEM-006", "SEM-007", "SEM-008", "SEM-009"):
        assert vectors[vector_id]["dimension"] in {"efs-specification", "factory-release"}


def test_contract_version_remains_opaque_and_exact():
    contract = next(item for item in _vectors()["dimensions"] if item["id"] == "capability-contract")
    assert contract["comparison"] == "exact-case-sensitive-equality-only"
    vectors = _all_vectors()
    assert vectors["CONTRACT-001"]["expected"] == "accept-as-opaque-non-empty-values-no-ordering"
    assert vectors["CONTRACT-002"]["expected"] == "equal"
    assert vectors["CONTRACT-003"]["expected"] == "not-equal"
    assert set(vectors["CONTRACT-001"]["values"]) >= {"1.0.0", "2026-Q4", "vNext", "vendor:blue"}


def test_build_identity_is_external_provenance():
    build = next(item for item in _vectors()["dimensions"] if item["id"] == "implementation-build")
    assert build["field"] == "external-provenance-only"
    manifest_schema = _json(ROOT / "schemas/efs/v1/factory-manifest.schema.json")
    assert "buildVersion" not in manifest_schema["properties"]


def test_release_comparison_scope_is_exact_factory_identity():
    vectors = _all_vectors()
    assert vectors["SCOPE-001"]["expected"] == "same-scope-comparable"
    assert vectors["SCOPE-002"]["expected"] == "not-comparable"
    assert "exact-publisher-factory-pair" == next(
        item["scope"] for item in _vectors()["dimensions"] if item["id"] == "factory-release"
    )


def test_cross_dimension_comparison_is_prohibited():
    rules = {item["id"]: item for item in _vectors()["rules"]}
    assert rules["VD-001"]["result"] == "reject"
    assert rules["VD-008"]["result"] == "no-coercion"


def test_build_metadata_precedence_requires_exact_selection():
    vectors = _all_vectors()
    assert vectors["PRECEDENCE-001"]["left"].split("+")[0] == vectors["PRECEDENCE-001"]["right"].split("+")[0]
    assert vectors["PRECEDENCE-001"]["expected"] == "equal-precedence-exact-selection-required"
    assert vectors["SEM-004"]["syntax"] == "valid"


def test_release_version_and_digest_are_independent_immutable_coordinates():
    vector = _all_vectors()["DIGEST-001"]
    assert vector["version"] == "1.2.0"
    assert vector["digestA"] != vector["digestB"]
    assert vector["expected"] == "immutable-release-conflict"
    spec = SPEC_PATH.read_text(encoding="utf-8")
    assert "efs-jcs-sha256-v1" in spec
    assert "MUST NOT rewrite or normalize" in spec


def test_version_dimension_catalogue_is_registered():
    catalog = _json(CATALOG_PATH)
    entry = catalog["versionDimensions"]
    assert entry["specification"] == "docs/efs-v1-version-dimensions.md"
    assert entry["vectors"] == "conformance/efs/v1/version-dimension-vectors.json"
    assert entry["acceptance"] == "conformance/efs/v1/version-dimension-acceptance.json"
    assert entry["testModule"] == "tests/test_version_dimensions.py"
    assert SPEC_PATH.is_file() and ADR_PATH.is_file() and ACCEPTANCE_PATH.is_file()
    assert "ADR-010" in (ROOT / "docs/adr/README.md").read_text(encoding="utf-8")


def test_version_dimension_acceptance_registry_is_complete():
    acceptance = _json(ACCEPTANCE_PATH)
    criteria = acceptance["criteria"]
    assert [item["id"] for item in criteria] == [f"PSI46-AC-{n:02d}" for n in range(1, 9)]
    test_names = {name for name in globals() if name.startswith("test_")}
    for criterion in criteria:
        assert criterion["requirement"]
        assert criterion["tests"]
        assert set(criterion["tests"]) <= test_names
        assert set(criterion["vectors"]) <= set(_all_vectors())
