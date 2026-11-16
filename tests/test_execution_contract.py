"""PSI-44 executable tests for the shared transport-neutral execution contract."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from registry.execution_contract import (
    validate_execution_envelope,
    validate_execution_transition,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "conformance/execution/v1/examples.json"
SCHEMA = ROOT / "schemas/execution/v1/execution-envelope.schema.json"


def _data():
    return json.loads(EXAMPLES.read_text(encoding="utf-8"))


def _manifest(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _valid_payload_port(_manifest, _context, _direction, _payload, error_code=None):
    return {"valid": True, "diagnostics": []}


def _example(example_id):
    return next(item for item in _data()["examples"] if item["id"] == example_id)


def test_execution_envelope_schema_and_examples_conform():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    examples = _data()["examples"]
    assert len(examples) >= 10
    for item in examples:
        validator.validate(item["envelope"])
        report = validate_execution_envelope(
            item["envelope"], _manifest(item["manifestPath"])
        )
        assert report["valid"], (item["id"], report)


def test_envelope_binds_exact_manifest_and_contract_coordinates():
    item = _example("request-sync")
    envelope = item["envelope"]
    manifest = _manifest(item["manifestPath"])
    assert validate_execution_envelope(
        envelope, manifest, payload_validator=_valid_payload_port
    )["valid"]

    altered = json.loads(json.dumps(envelope))
    altered["context"]["releaseDigest"]["value"] = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
    report = validate_execution_envelope(
        altered, manifest, payload_validator=_valid_payload_port
    )
    assert not report["valid"]
    assert "EFS_EXECUTION_CONTEXT_MISMATCH" in {
        item["code"] for item in report["diagnostics"]
    }

    altered = json.loads(json.dumps(envelope))
    altered["context"]["contract"]["version"] = "2.0"
    report = validate_execution_envelope(
        altered, manifest, payload_validator=_valid_payload_port
    )
    assert "EFS_EXECUTION_CONTRACT_MISMATCH" in {
        item["code"] for item in report["diagnostics"]
    }


def test_payload_bearing_messages_use_the_canonical_psi43_validator_by_default():
    item = _example("request-sync")
    manifest = _manifest(item["manifestPath"])
    default_report = validate_execution_envelope(item["envelope"], manifest)
    assert default_report["valid"], default_report

    invalid = json.loads(json.dumps(item["envelope"]))
    invalid["payload"]["requestId"] = 123
    rejected = validate_execution_envelope(invalid, manifest)
    assert not rejected["valid"]
    assert "EFS_CONTRACT_PAYLOAD_INVALID" in {
        item["code"] for item in rejected["diagnostics"]
    }

    calls = []
    def port(manifest_arg, context, direction, payload, error_code=None):
        calls.append((context, direction, payload, error_code))
        return {"valid": True, "diagnostics": []}

    for example_id, expected_direction in (
        ("request-sync", "inputs"),
        ("result-sync", "outputs"),
        ("error-sync", "errors"),
        ("progress-data-streaming", "outputs"),
        ("event", "inputs"),
    ):
        example = _example(example_id)
        report = validate_execution_envelope(
            example["envelope"], _manifest(example["manifestPath"]),
            payload_validator=port,
        )
        assert report["valid"], (example_id, report)
        assert calls[-1][1] == expected_direction
    assert calls[2][3] == "INVALID_REQUEST"


def test_error_messages_require_declared_contract_error_codes():
    item = _example("error-sync")
    manifest = _manifest(item["manifestPath"])
    altered = json.loads(json.dumps(item["envelope"]))
    altered["error"]["code"] = "NOT_DECLARED"
    report = validate_execution_envelope(
        altered, manifest, payload_validator=_valid_payload_port
    )
    assert not report["valid"]
    assert "EFS_EXECUTION_ERROR_UNDECLARED" in {
        item["code"] for item in report["diagnostics"]
    }


def test_causal_transition_propagates_correlation_and_causation():
    request = _example("request-async")["envelope"]
    accepted = _example("accepted-async")["envelope"]
    result = _example("result-async")["envelope"]
    assert validate_execution_transition(request, accepted)["valid"]
    assert validate_execution_transition(accepted, result)["valid"]

    altered = json.loads(json.dumps(result))
    altered["correlationId"] = "different-correlation"
    report = validate_execution_transition(accepted, altered)
    codes = {item["code"] for item in report["diagnostics"]}
    assert not report["valid"]
    assert "EFS_EXECUTION_CORRELATION_MISMATCH" in codes

    altered = json.loads(json.dumps(result))
    altered["causationId"] = "not-the-accepted-message"
    report = validate_execution_transition(accepted, altered)
    assert "EFS_EXECUTION_CAUSATION_MISMATCH" in {
        item["code"] for item in report["diagnostics"]
    }


def test_mode_specific_envelopes_and_transition_rules():
    request = _example("request-sync")["envelope"]
    result = _example("result-sync")["envelope"]
    assert validate_execution_transition(request, result)["valid"]

    accepted = _example("accepted-async")["envelope"]
    assert not validate_execution_transition(request, accepted)["valid"]

    streaming_request = _example("request-streaming")["envelope"]
    streaming_progress = _example("progress-streaming")["envelope"]
    assert not validate_execution_transition(streaming_request, streaming_progress)["valid"]

    event = _example("event")["envelope"]
    event_result = _example("result-event")["envelope"]
    assert validate_execution_transition(event, event_result)["valid"]
    assert not validate_execution_transition(event, accepted)["valid"]

    invalid = json.loads(json.dumps(request))
    invalid["context"]["executionMode"] = "event"
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(invalid))
    assert errors


def test_vectors_make_transport_and_guarantee_non_inference_explicit():
    vectors = json.loads(
        (ROOT / "conformance/execution/v1/vectors.json").read_text(encoding="utf-8")
    )
    assert vectors["envelopeVersion"] == "1.0"
    assert vectors["transportIndependence"]["mandatoryProtocol"] is None
    for key in (
        "queuedMeansDurable", "sequenceMeansDeliveryOrder", "sequenceMeansReplay",
        "implicitIdempotency", "implicitRetryability", "implicitCancellation",
        "implicitApproval", "implicitCompensation",
    ):
        assert vectors["nonInferences"][key] is False
    assert vectors["cancellation"]["supported"] is False
    assert set(vectors["modeRules"]) == {"sync", "async", "streaming", "event"}


def test_execution_acceptance_registry_maps_to_executable_tests():
    registry = json.loads(
        (ROOT / "conformance/execution/v1/acceptance.json").read_text(encoding="utf-8")
    )
    tests = {
        "test_execution_envelope_schema_and_examples_conform",
        "test_envelope_binds_exact_manifest_and_contract_coordinates",
        "test_payload_bearing_messages_use_the_canonical_psi43_validator_by_default",
        "test_error_messages_require_declared_contract_error_codes",
        "test_causal_transition_propagates_correlation_and_causation",
        "test_mode_specific_envelopes_and_transition_rules",
        "test_vectors_make_transport_and_guarantee_non_inference_explicit",
        "test_execution_acceptance_registry_maps_to_executable_tests",
        "test_context_mismatch_stops_before_payload_validator_invocation",
    }
    criteria = registry["acceptanceCriteria"]
    assert [item["id"] for item in criteria] == [
        f"PSI44-AC-{number:02d}" for number in range(1, 9)
    ]
    for criterion in criteria:
        assert criterion["tests"]
        assert set(criterion["tests"]) <= tests


def test_context_mismatch_stops_before_payload_validator_invocation():
    item = _example("request-sync")
    envelope = json.loads(json.dumps(item["envelope"]))
    envelope["context"]["contract"]["version"] = "9.9"
    calls = []
    def port(*args, **kwargs):
        calls.append((args, kwargs))
        return {"valid": True, "diagnostics": []}
    report = validate_execution_envelope(
        envelope, _manifest(item["manifestPath"]), payload_validator=port
    )
    assert not report["valid"]
    assert not calls
