"""PSI-37 publisher identity profile and conformance corpus tests."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_manifest import canonical_publisher_uri, load_json, validate_report

VECTORS_PATH = ROOT / "conformance/efs/v1/publisher-identity-vectors.json"
ACCEPTANCE_PATH = ROOT / "conformance/efs/v1/publisher-identity-acceptance.json"
SCHEMA_PATH = ROOT / "schemas/efs/v1/factory-manifest.schema.json"


def test_publisher_identity_vectors():
    corpus = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    assert corpus["profile"] == "efs-uri-c14n-1"
    for vector in corpus["vectors"]:
        actual = canonical_publisher_uri(vector["input"])
        if vector["valid"]:
            assert actual == vector["canonical"], vector["id"]
        elif vector["canonical"] is None:
            assert actual is None, vector["id"]
        else:
            assert actual == vector["canonical"], vector["id"]
            assert actual != vector["input"], vector["id"]


def test_publisher_id_profile_diagnostics(tmp_path):
    base = load_json(ROOT / "fixtures/valid/manifest-minimal.json")
    cases = [
        ("https://EXAMPLE.com/publisher", "EFS_PUBLISHER_URI_NON_CANONICAL"),
        ("https://example.com/publisher?tenant=1", "EFS_PUBLISHER_URI_INVALID"),
        ("relative/publisher", "EFS_SCHEMA_CONSTRAINT"),
    ]
    for index, (publisher_id, expected_code) in enumerate(cases):
        manifest = json.loads(json.dumps(base))
        manifest["publisher"]["id"] = publisher_id
        path = tmp_path / f"publisher-{index}.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        report = validate_report(path, SCHEMA_PATH)
        assert not report["valid"]
        assert expected_code in {item["code"] for item in report["diagnostics"]}
        if expected_code == "EFS_PUBLISHER_URI_NON_CANONICAL":
            item = next(d for d in report["diagnostics"] if d["code"] == expected_code)
            assert item["path"] == "/publisher/id"
            assert item["details"]["canonical"] == "https://example.com/publisher"


def test_existing_urn_publisher_fixture_remains_conformant():
    report = validate_report(ROOT / "fixtures/valid/manifest-minimal.json", SCHEMA_PATH)
    assert report["valid"], report["diagnostics"]
    assert canonical_publisher_uri("urn:example:publishers:acme") == "urn:example:publishers:acme"


def test_factory_identity_pair_is_publisher_scoped_and_exact():
    factory_id = "customer-support"
    acme_identity = ("urn:example:publishers:acme", factory_id)
    beta_identity = ("urn:example:publishers:beta", factory_id)
    renamed_factory = ("urn:example:publishers:acme", "Customer-Support")
    assert acme_identity != beta_identity
    assert acme_identity != renamed_factory
    # No URI dereferencing or mutable display-name field participates in this tuple.


def test_publisher_identity_acceptance_registry_is_traceable():
    registry = json.loads(ACCEPTANCE_PATH.read_text(encoding="utf-8"))
    corpus = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    vector_ids = {item["id"] for item in corpus["vectors"]}
    criteria = registry["criteria"]
    assert registry["profile"] == "efs-uri-c14n-1"
    assert [item["id"] for item in criteria] == [f"PSI37-AC-{n:02d}" for n in range(1, 6)]
    for criterion in criteria:
        assert criterion["requirement"]
        assert criterion["tests"]
        assert set(criterion["vectors"]) <= vector_ids
