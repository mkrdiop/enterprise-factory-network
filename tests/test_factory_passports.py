"""PSI-41 deterministic Passport projection, provenance and schema tests."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from registry.passports import (
    PassportSourceMismatch,
    build_factory_passport,
    canonical_passport_json,
    render_factory_passport_markdown,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/passports"


def _manifest():
    return json.loads((ROOT / "fixtures/valid/manifest-minimal.json").read_text(encoding="utf-8"))


def _registry_record(manifest):
    return {
        "releaseRecordId": "00000000-0000-4000-8000-000000000041",
        "publisherId": manifest["publisher"]["id"],
        "factoryId": manifest["factory"]["id"],
        "version": manifest["release"]["version"],
        "digest": manifest["release"]["digest"],
        "publishedAt": "2026-11-16T09:00:00+00:00",
        "byteLength": 1315,
        "provider": "filesystem",
        "objectKey": "opaque-storage-key",
    }


def _resolve_pointer(document, pointer):
    value = document
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def test_passport_is_a_projection_of_exact_registered_release():
    manifest = _manifest()
    record = _registry_record(manifest)
    passport = build_factory_passport(manifest, record)

    assert passport["source"]["publisherId"] == manifest["publisher"]["id"]
    assert passport["source"]["factoryId"] == manifest["factory"]["id"]
    assert passport["source"]["releaseVersion"] == manifest["release"]["version"]
    assert passport["source"]["digest"] == manifest["release"]["digest"]
    assert passport["source"]["registry"]["releaseRecordId"] == record["releaseRecordId"]
    assert passport["capabilities"] == manifest["capabilities"]
    assert passport["execution"] == manifest["execution"]
    assert passport["dependencies"] == manifest["dependencies"]
    assert passport["policies"] == manifest["policies"]
    assert "id" not in passport
    assert "createdAt" not in passport["source"]


def test_every_passport_field_has_explicit_provenance_or_contract_derivation():
    manifest = _manifest()
    record = _registry_record(manifest)
    passport = build_factory_passport(manifest, record)
    provenance = passport["provenance"]

    assert provenance == sorted(
        provenance,
        key=lambda item: (item["target"], item["source"], item["sourcePointer"]),
    )
    for item in provenance:
        _resolve_pointer(passport, item["target"])
        if item["source"] == "manifest":
            _resolve_pointer(manifest, item["sourcePointer"])
        elif item["source"] == "registry":
            _resolve_pointer(
                {
                    "releaseRecordId": record["releaseRecordId"],
                    "publishedAt": record["publishedAt"],
                    "byteLength": record["byteLength"],
                },
                item["sourcePointer"].replace("/registry", "", 1),
            )
        else:
            assert item["source"] == "derivation"
            assert item["rule"] != "copy"

    assert any(item["target"] == "/assurance/artifactIntegrity" for item in provenance)
    assert any(item["target"] == "/summary/endpointCount" for item in provenance)


def test_passport_rejects_registry_manifest_identity_or_digest_mismatch():
    manifest = _manifest()
    record = _registry_record(manifest)
    record["factoryId"] = "different-factory"
    with pytest.raises(PassportSourceMismatch, match="do not match"):
        build_factory_passport(manifest, record)


def test_optional_fields_are_omitted_and_extensions_are_preserved():
    manifest = _manifest()
    manifest["extensions"] = {"https://extensions.example.org/ui": {"theme": "dark"}}
    manifest["publisher"].pop("name")
    record = _registry_record(manifest)
    passport = build_factory_passport(manifest, record)
    assert "name" not in passport["publisher"]
    assert "createdAt" not in passport["release"]
    assert passport["extensions"] == manifest["extensions"]
    assert any(item["target"].startswith("/extensions/") for item in passport["provenance"])


def test_machine_readable_passport_is_canonical_and_deterministic():
    manifest = _manifest()
    record = _registry_record(manifest)
    first = canonical_passport_json(build_factory_passport(manifest, record))
    second = canonical_passport_json(build_factory_passport(manifest, record))
    assert first == second
    assert first.endswith(b"}")
    assert b"publisherAuthentication" in first


def test_passport_conforms_to_its_draft_2020_12_schema():
    schema = json.loads(
        (ROOT / "schemas/passport/v1/factory-passport.schema.json").read_text(encoding="utf-8")
    )
    passport = build_factory_passport(_manifest(), _registry_record(_manifest()))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(passport)


def test_json_and_markdown_golden_fixtures():
    passport = json.loads((FIXTURES / "minimal-passport.json").read_text(encoding="utf-8"))
    expected_json = (FIXTURES / "minimal-passport.canonical.json").read_bytes()
    expected_markdown = (FIXTURES / "minimal-passport.md").read_text(encoding="utf-8")
    assert canonical_passport_json(passport) + b"\n" == expected_json
    assert render_factory_passport_markdown(passport) == expected_markdown



def test_external_execution_profiles_and_optional_policy_branches_are_preserved():
    manifest = _manifest()
    manifest["execution"] = {
        "source": "external",
        "profileReferences": [{
            "id": "https://profiles.example.org/execution/http/v1",
            "version": "1.0.0",
            "digest": {"algorithm": "SHA-256", "value": "A" * 43},
        }],
    }
    manifest["policies"] = {"declarations": []}
    passport = build_factory_passport(manifest, _registry_record(manifest))
    assert passport["execution"] == manifest["execution"]
    assert passport["policies"] == manifest["policies"]
    assert passport["summary"]["policyDeclarationCount"] == 0
    assert passport["summary"]["policyReferenceCount"] == 0
