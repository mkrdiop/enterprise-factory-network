"""Schema and semantic conformance checks for PSI-53 and PSI-54."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
VECTOR_DIR = ROOT / "tests" / "conformance"


def test_psi53_vectors_validate_and_execute() -> None:
    schema = json.loads((SCHEMA_DIR / "psi-53-enforcement-v1.schema.json").read_text())
    vectors = json.loads((VECTOR_DIR / "psi-53-enforcement-v1.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(vectors)


def test_psi54_vectors_validate_and_execute() -> None:
    schema = json.loads((SCHEMA_DIR / "psi-54-lifecycle-v1.schema.json").read_text())
    vectors = json.loads((VECTOR_DIR / "psi-54-lifecycle-v1.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(vectors)


def test_psi53_psi54_reference_oracle() -> None:
    runner = VECTOR_DIR / "run_psi_53_54_vectors.py"
    subprocess.run([sys.executable, str(runner)], cwd=ROOT, check=True)


def test_psi54_schema_rejects_authoring_candidate_states() -> None:
    schema = json.loads((SCHEMA_DIR / "psi-54-lifecycle-v1.schema.json").read_text())
    vectors = json.loads((VECTOR_DIR / "psi-54-lifecycle-v1.json").read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    candidate = json.loads(json.dumps(vectors["vectors"][0]))
    candidate["input"]["from"] = "draft"
    candidate["input"]["to"] = "validated"
    assert not validator.is_valid({**vectors, "vectors": [candidate]})


def test_psi53_composite_publication_has_three_independent_checks() -> None:
    vectors = json.loads((VECTOR_DIR / "psi-53-enforcement-v1.json").read_text())
    vector = next(item for item in vectors["vectors"] if item["id"] == "psi53-021")
    assert [check["action"] for check in vector["input"]["checks"]] == [
        "factory.register", "factory.publish", "release.publish"
    ]


def test_psi54_initial_publication_event_is_complete() -> None:
    vectors = json.loads((VECTOR_DIR / "psi-54-lifecycle-v1.json").read_text())
    vector = next(item for item in vectors["vectors"] if item["id"] == "psi54-010")
    event = vector["input"]["publication"]
    assert event["event_id"] and event["event_type"] == "factory_release.published"
    assert event["action"] == "release.publish" and event["revision"] == 1
    assert event["from_state"] is None
    assert event["coordinate_snapshot"] and event["digest_snapshot"]
    assert event["same_database_transaction"]


def test_psi53_external_effect_intent_uses_psi45_invocation_state() -> None:
    vectors = json.loads((VECTOR_DIR / "psi-53-enforcement-v1.json").read_text())
    vector = next(item for item in vectors["vectors"] if item["id"] == "psi53-013")
    commit = vector["input"]["commit"]
    intent = commit["side_effect"]
    execution = commit["execution_state"]
    assert intent["operation_id"] == execution["invocation_id"]
    assert execution["initial_state"] == "requested"
    assert execution["initial_revision"] == 1
    assert execution["persisted_with_intent"] and execution["revision_cas"]


def test_psi54_request_fingerprint_uses_sha256_base64url_profile() -> None:
    vectors = json.loads((VECTOR_DIR / "psi-54-lifecycle-v1.json").read_text())
    for vector in vectors["vectors"]:
        assert re.fullmatch(r"sha256:[A-Za-z0-9_-]{43}", vector["input"]["request_fingerprint"])
