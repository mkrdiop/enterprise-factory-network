"""PSI-45 executable conformance tests for the shared execution state model."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from registry.execution_state import (
    apply_execution_state_transition,
    initial_execution_state,
    transition_event_from_envelope,
    validate_execution_state,
)

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "conformance/execution/v1/state-vectors.json"
ACCEPTANCE = ROOT / "conformance/execution/v1/state-acceptance.json"
STATE_SCHEMA = ROOT / "schemas/execution/v1/execution-state.schema.json"
EVENT_SCHEMA = ROOT / "schemas/execution/v1/execution-state-event.schema.json"
ENVELOPE_SCHEMA = ROOT / "schemas/execution/v1/execution-envelope.schema.json"
CONTEXT = {
    "publisherId": "urn:example:publishers:acme", "factoryId": "factory-a",
    "releaseVersion": "1.0.0",
    "releaseDigest": {"profile": "efs-jcs-sha256-v1", "algorithm": "SHA-256",
                      "value": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
    "capabilityId": "capability-a",
    "contract": {"id": "https://example.org/contracts/a", "version": "1.0"},
    "executionProfileId": "profile-a", "executionMode": "async",
}


def _state(state="requested", revision=1):
    return {"stateVersion": "1.0", "invocationId": "inv-1", "correlationId": "corr-1",
            "context": CONTEXT, "state": state, "revision": revision, "lastEventId": "evt-0"}


def _event(event_type, from_state, to_state, *, revision=1, source=None, **extra):
    source = source or ("governed_control" if event_type == "cancelled" else
                        "runtime" if event_type in {"waiting", "resumed"} else "envelope")
    event = {
        "eventVersion": "1.0", "eventId": f"evt-{revision + 1}-{event_type}",
        "invocationId": "inv-1", "correlationId": "corr-1", "causationId": "msg-1",
        "source": source, "sourceMessageId": "msg-1", "eventType": event_type,
        "fromState": from_state, "toState": to_state, "expectedRevision": revision,
        "reasonCode": f"efs.execution.{event_type}", "occurredAt": "2026-11-16T10:00:00Z",
        "context": CONTEXT,
    }
    event.update(extra)
    if event_type == "cancelled":
        event.setdefault("governanceRef", "urn:example:governance:cancel-v1")
    return event


def _apply(state, event, seen_events=None):
    return apply_execution_state_transition(state, event, seen_events=seen_events)


def _registry():
    envelope = json.loads(ENVELOPE_SCHEMA.read_text(encoding="utf-8"))
    return Registry().with_resource(envelope["$id"], Resource.from_contents(envelope))


def test_state_and_event_schemas_conform_to_vectors():
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
    state_schema = json.loads(STATE_SCHEMA.read_text(encoding="utf-8"))
    event_schema = json.loads(EVENT_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(state_schema)
    Draft202012Validator.check_schema(event_schema)
    assert vectors["states"] == state_schema["properties"]["state"]["enum"]
    assert vectors["states"] == event_schema["properties"]["fromState"]["enum"]
    assert set(vectors["terminalStates"]) == {"succeeded", "failed", "cancelled"}
    assert validate_execution_state(_state())["valid"]
    assert Draft202012Validator(event_schema, registry=_registry(),
                                format_checker=FormatChecker()).is_valid(
        _event("accepted", "requested", "accepted")
    )


def test_every_normative_transition_is_accepted():
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
    for event_type, rule in vectors["transitions"].items():
        for from_state in rule["from"]:
            current = _state(from_state, revision=4)
            event = _event(
                event_type, from_state, rule["to"], revision=4, source=rule["source"],
                **({"governanceRef": "urn:example:governance:cancel-v1"}
                   if rule.get("requiresGovernanceRef") else {}),
            )
            report = _apply(current, event)
            assert report["valid"], (event_type, from_state, report)
            assert report["state"]["state"] == rule["to"]
            assert report["state"]["revision"] == 5


def test_invalid_out_of_order_and_terminal_transitions_are_rejected():
    cases = [
        (_state("created", 0), _event("succeeded", "created", "succeeded", revision=0)),
        (_state("running", 2), _event("accepted", "running", "accepted", revision=2)),
        (_state("succeeded", 3), _event("started", "succeeded", "running", revision=3)),
        (_state("failed", 3), _event("cancelled", "failed", "cancelled", revision=3)),
        (_state("cancelled", 3), _event("started", "cancelled", "running", revision=3)),
    ]
    for current, event in cases:
        report = _apply(current, event)
        assert not report["valid"]
        assert "EFS_EXECUTION_STATE_TRANSITION_INVALID" in {
            item["code"] for item in report["diagnostics"]
        }


def test_replay_is_idempotent_and_event_id_reuse_conflicts():
    current = _state()
    event = _event("accepted", "requested", "accepted")
    replay = _apply(current, event, {event["eventId"]: event})
    assert replay["valid"] and replay["replayed"] and replay["state"] == current
    altered = dict(event, reasonCode="efs.execution.other")
    conflict = _apply(current, altered, {event["eventId"]: event})
    assert not conflict["valid"]
    assert "EFS_EXECUTION_STATE_EVENT_ID_CONFLICT" in {
        item["code"] for item in conflict["diagnostics"]
    }


def test_stale_revision_is_rejected():
    report = _apply(_state(revision=3), _event("accepted", "requested", "accepted", revision=2))
    assert not report["valid"]
    assert "EFS_EXECUTION_STATE_REVISION_CONFLICT" in {
        item["code"] for item in report["diagnostics"]
    }


def test_identity_and_context_are_preserved_and_mismatch_fails():
    current, event = _state(), _event("accepted", "requested", "accepted")
    report = _apply(current, event)
    assert report["valid"]
    assert report["state"]["invocationId"] == current["invocationId"]
    assert report["state"]["correlationId"] == current["correlationId"]
    assert report["state"]["context"] == CONTEXT
    rejected = _apply(current, dict(event, correlationId="other"))
    assert "EFS_EXECUTION_STATE_CORRELATION_MISMATCH" in {
        item["code"] for item in rejected["diagnostics"]
    }


def test_envelope_projection_is_correlation_aware_and_auditable():
    envelope = {
        "messageType": "request", "messageId": "message-1", "invocationId": "inv-1",
        "correlationId": "corr-1", "causationId": "upstream-1",
        "occurredAt": "2026-11-16T10:00:00Z", "context": CONTEXT,
    }
    current = initial_execution_state(envelope)
    assert current["state"] == "created" and current["revision"] == 0
    event = transition_event_from_envelope(current, envelope)
    assert event["fromState"] == "created" and event["toState"] == "requested"
    assert event["reasonCode"] and event["sourceMessageId"] == "message-1"
    assert event["causationId"] == "upstream-1"
    applied = _apply(current, event)
    assert applied["valid"] and applied["state"]["lastEventId"] == "message-1"


def test_cancellation_requires_governed_control_and_is_terminal():
    current = _state("running", 2)
    event = _event("cancelled", "running", "cancelled", revision=2,
                   source="envelope", governanceRef="urn:example:governance:cancel-v1")
    rejected = _apply(current, event)
    assert "EFS_EXECUTION_STATE_CANCELLATION_UNGOVERNED" in {
        item["code"] for item in rejected["diagnostics"]
    }
    event["source"] = "governed_control"
    accepted = _apply(current, event)
    assert accepted["valid"] and accepted["state"]["state"] == "cancelled"
    terminal = _apply(accepted["state"], _event("started", "cancelled", "running", revision=3))
    assert not terminal["valid"]


def test_state_model_is_pure_and_non_inferences_are_explicit():
    current = _state()
    original, event = json.loads(json.dumps(current)), _event("accepted", "requested", "accepted")
    original_event = json.loads(json.dumps(event))
    _apply(current, event)
    assert current == original and event == original_event
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert all(value is False for value in vectors["nonInferences"].values())


def test_state_acceptance_registry_maps_to_executable_tests():
    registry = json.loads(ACCEPTANCE.read_text(encoding="utf-8"))
    names = {
        "test_state_and_event_schemas_conform_to_vectors",
        "test_every_normative_transition_is_accepted",
        "test_invalid_out_of_order_and_terminal_transitions_are_rejected",
        "test_replay_is_idempotent_and_event_id_reuse_conflicts",
        "test_stale_revision_is_rejected",
        "test_identity_and_context_are_preserved_and_mismatch_fails",
        "test_envelope_projection_is_correlation_aware_and_auditable",
        "test_cancellation_requires_governed_control_and_is_terminal",
        "test_state_model_is_pure_and_non_inferences_are_explicit",
        "test_state_acceptance_registry_maps_to_executable_tests",
    }
    assert [item["id"] for item in registry["acceptanceCriteria"]] == [
        f"PSI45-AC-{number:02d}" for number in range(1, 9)
    ]
    for criterion in registry["acceptanceCriteria"]:
        assert criterion["tests"] and set(criterion["tests"]) <= names
