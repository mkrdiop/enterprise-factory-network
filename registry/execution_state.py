"""PSI-45 deterministic EFS execution lifecycle state model."""
from __future__ import annotations
import json
from collections.abc import Mapping
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
EVENT_SCHEMA = ROOT / "schemas/execution/v1/execution-state-event.schema.json"
STATE_SCHEMA = ROOT / "schemas/execution/v1/execution-state.schema.json"
ENVELOPE_SCHEMA = ROOT / "schemas/execution/v1/execution-envelope.schema.json"
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})
STATES = frozenset({"created", "requested", "accepted", "queued", "running", "waiting", "succeeded", "failed", "cancelled"})
TRANSITIONS = {
    "request": ({"created"}, "requested"),
    "accepted": ({"requested"}, "accepted"),
    "queued": ({"requested"}, "queued"),
    "started": ({"requested", "accepted", "queued", "waiting"}, "running"),
    "progress": ({"accepted", "queued", "running"}, "running"),
    "waiting": ({"running"}, "waiting"),
    "resumed": ({"waiting"}, "running"),
    "succeeded": ({"requested", "accepted", "queued", "running", "waiting"}, "succeeded"),
    "failed": ({"requested", "accepted", "queued", "running", "waiting"}, "failed"),
    "cancelled": ({"created", "requested", "accepted", "queued", "running", "waiting"}, "cancelled"),
}


def _schema_registry() -> Registry:
    envelope = json.loads(ENVELOPE_SCHEMA.read_text(encoding="utf-8"))
    return Registry().with_resource(envelope["$id"], Resource.from_contents(envelope))


def _diagnostic(code: str, path: str, message: str, details=None) -> dict:
    item = {"code": code, "stage": "execution_state", "path": path, "message": message}
    if details is not None:
        item["details"] = details
    return item


def _sort(diagnostics: list[dict]) -> list[dict]:
    return sorted(diagnostics, key=lambda item: (
        item["stage"], item["path"], item["code"], item["message"],
        json.dumps(item.get("details", {}), sort_keys=True, separators=(",", ":")),
    ))


def initial_execution_state(envelope: dict) -> dict:
    """Create revision-zero state from a PSI-44 request/event validated by its caller."""
    if envelope.get("messageType") not in {"request", "event"}:
        raise ValueError("initial state requires a PSI-44 request or event envelope")
    return {
        "stateVersion": "1.0", "invocationId": envelope["invocationId"],
        "correlationId": envelope["correlationId"], "context": envelope["context"],
        "state": "created", "revision": 0, "lastEventId": None,
    }


def transition_event_from_envelope(state: dict, envelope: dict) -> dict:
    """Project one validated PSI-44 envelope into a correlation-aware lifecycle event."""
    message_type = envelope.get("messageType")
    if message_type in {"request", "event"}:
        event_type, target = "request", "requested"
    elif message_type == "accepted":
        event_type = envelope.get("disposition")
        target = "accepted" if event_type == "accepted" else "queued"
    elif message_type == "progress":
        event_type, target = "progress", "running"
    elif message_type == "result":
        event_type, target = "succeeded", "succeeded"
    elif message_type == "error":
        event_type, target = "failed", "failed"
    else:
        raise ValueError("unsupported PSI-44 message type for lifecycle projection")
    return {
        "eventVersion": "1.0", "eventId": envelope["messageId"],
        "invocationId": envelope["invocationId"], "correlationId": envelope["correlationId"],
        "causationId": envelope.get("causationId"), "source": "envelope",
        "sourceMessageId": envelope["messageId"], "eventType": event_type,
        "fromState": state["state"], "toState": target,
        "expectedRevision": state["revision"], "reasonCode": f"efs.execution.{event_type}",
        "occurredAt": envelope["occurredAt"], "context": envelope["context"],
    }


def apply_execution_state_transition(
    current_state: dict, event: dict, *, seen_events: Mapping[str, dict] | None = None,
) -> dict:
    """Validate/apply one event without mutation; caller supplies its durable event-ID index.

    Identical event ID and content is an idempotent replay. Reuse with different
    content conflicts. expectedRevision is a compare-and-swap precondition, not a lock.
    """
    try:
        schema = json.loads(EVENT_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema, registry=_schema_registry(),
                                 format_checker=FormatChecker()).iter_errors(event),
            key=lambda error: ("/" + "/".join(map(str, error.absolute_path)), str(error.validator)),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {"valid": False, "replayed": False, "state": current_state, "diagnostics": [
            _diagnostic("EFS_EXECUTION_STATE_SCHEMA_UNAVAILABLE", "",
                        "The versioned execution state event schema could not be loaded.",
                        {"errorType": type(exc).__name__})
        ]}
    if errors:
        diagnostics = [_diagnostic(
            "EFS_EXECUTION_STATE_EVENT_INVALID",
            "/" + "/".join(str(part) for part in error.absolute_path),
            "Lifecycle event does not conform to the EFS execution state event schema.",
            {"keyword": str(error.validator)},
        ) for error in errors]
        return {"valid": False, "replayed": False, "state": current_state,
                "diagnostics": _sort(diagnostics)}

    event_id = event["eventId"]
    if seen_events is not None and event_id in seen_events:
        if seen_events[event_id] == event:
            return {"valid": True, "replayed": True, "state": current_state, "diagnostics": []}
        return {"valid": False, "replayed": False, "state": current_state, "diagnostics": [
            _diagnostic("EFS_EXECUTION_STATE_EVENT_ID_CONFLICT", "/eventId",
                        "An event ID already exists with different event content.")
        ]}

    diagnostics = []
    for key, code, message in (
        ("invocationId", "EFS_EXECUTION_STATE_INVOCATION_MISMATCH",
         "Lifecycle event invocation ID differs from the current execution."),
        ("correlationId", "EFS_EXECUTION_STATE_CORRELATION_MISMATCH",
         "Lifecycle event correlation ID differs from the current execution."),
        ("context", "EFS_EXECUTION_STATE_CONTEXT_MISMATCH",
         "Lifecycle event must preserve the exact immutable PSI-44 invocation context."),
    ):
        if event[key] != current_state.get(key):
            diagnostics.append(_diagnostic(code, f"/{key}", message))
    if event["fromState"] != current_state.get("state"):
        diagnostics.append(_diagnostic(
            "EFS_EXECUTION_STATE_SOURCE_MISMATCH", "/fromState",
            "Lifecycle event prior state does not match the current state.",
        ))
    if event["expectedRevision"] != current_state.get("revision"):
        diagnostics.append(_diagnostic(
            "EFS_EXECUTION_STATE_REVISION_CONFLICT", "/expectedRevision",
            "Lifecycle event was based on a stale state revision; reload and reconcile.",
            {"expected": current_state.get("revision"), "received": event["expectedRevision"]},
        ))

    event_type = event["eventType"]
    transition = TRANSITIONS.get(event_type)
    if transition is None or current_state.get("state") not in transition[0]:
        diagnostics.append(_diagnostic(
            "EFS_EXECUTION_STATE_TRANSITION_INVALID", "/eventType",
            "Lifecycle event is not legal from the current state.",
            {"eventType": event_type, "currentState": current_state.get("state")},
        ))
    elif event["toState"] != transition[1]:
        diagnostics.append(_diagnostic(
            "EFS_EXECUTION_STATE_TARGET_MISMATCH", "/toState",
            "Lifecycle event target differs from the normative transition table.",
            {"expected": transition[1], "received": event["toState"]},
        ))

    if event_type == "cancelled":
        if event["source"] != "governed_control" or not event.get("governanceRef"):
            diagnostics.append(_diagnostic(
                "EFS_EXECUTION_STATE_CANCELLATION_UNGOVERNED", "/governanceRef",
                "Cancellation requires an explicit governed control reference; PSI-44 v1.0 defines no cancellation message.",
            ))
    elif event_type in {"waiting", "resumed"}:
        if event["source"] != "runtime":
            diagnostics.append(_diagnostic(
                "EFS_EXECUTION_STATE_SOURCE_INVALID", "/source",
                "Waiting and resumed signals must originate from the runtime adapter.",
            ))
    elif event["source"] != "envelope":
        diagnostics.append(_diagnostic(
            "EFS_EXECUTION_STATE_SOURCE_INVALID", "/source",
            "This lifecycle event must be derived from a validated PSI-44 envelope.",
        ))

    if diagnostics:
        return {"valid": False, "replayed": False, "state": current_state,
                "diagnostics": _sort(diagnostics)}
    next_state = {
        **current_state, "state": transition[1],
        "revision": current_state["revision"] + 1, "lastEventId": event_id,
    }
    return {"valid": True, "replayed": False, "state": next_state, "diagnostics": []}


def validate_execution_state(state: dict) -> dict:
    """Validate a serialized lifecycle snapshot against the versioned state schema."""
    schema = json.loads(STATE_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, registry=_schema_registry(),
                             format_checker=FormatChecker()).iter_errors(state),
        key=lambda error: ("/" + "/".join(map(str, error.absolute_path)), str(error.validator)),
    )
    diagnostics = [_diagnostic(
        "EFS_EXECUTION_STATE_SNAPSHOT_INVALID",
        "/" + "/".join(str(part) for part in error.absolute_path),
        "Execution state snapshot does not conform to the EFS state schema.",
        {"keyword": str(error.validator)},
    ) for error in errors]
    return {"valid": not diagnostics, "diagnostics": _sort(diagnostics)}


def initial_execution_state(envelope: dict) -> dict:
    """Create revision-zero state from a PSI-44 request/event validated by its caller."""
    if envelope.get("messageType") not in {"request", "event"}:
        raise ValueError("initial state requires a PSI-44 request or event envelope")
    return {"stateVersion": "1.0", "invocationId": envelope["invocationId"],
            "correlationId": envelope["correlationId"], "context": envelope["context"],
            "state": "created", "revision": 0, "lastEventId": None}


def transition_event_from_envelope(state: dict, envelope: dict) -> dict:
    """Project a validated PSI-44 envelope into a correlation-aware lifecycle event."""
    kind = envelope.get("messageType")
    if kind in {"request", "event"}:
        event_type, target = "request", "requested"
    elif kind == "accepted":
        event_type = envelope.get("disposition")
        target = "accepted" if event_type == "accepted" else "queued"
    elif kind == "progress":
        event_type, target = "progress", "running"
    elif kind == "result":
        event_type, target = "succeeded", "succeeded"
    elif kind == "error":
        event_type, target = "failed", "failed"
    else:
        raise ValueError("unsupported PSI-44 message type for lifecycle projection")
    return {"eventVersion": "1.0", "eventId": envelope["messageId"],
            "invocationId": envelope["invocationId"], "correlationId": envelope["correlationId"],
            "causationId": envelope.get("causationId"), "source": "envelope",
            "sourceMessageId": envelope["messageId"], "eventType": event_type,
            "fromState": state["state"], "toState": target,
            "expectedRevision": state["revision"], "reasonCode": f"efs.execution.{event_type}",
            "occurredAt": envelope["occurredAt"], "context": envelope["context"]}


def apply_execution_state_transition(current_state: dict, event: dict, *, seen_events=None) -> dict:
    """Pure transition validator; persistence must atomically compare-and-swap revision."""
    schema = json.loads(EVENT_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, registry=_schema_registry(),
                                     format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(event),
                    key=lambda error: (str(list(error.absolute_path)), str(error.validator)))
    if errors:
        diagnostics = [_diagnostic("EFS_EXECUTION_STATE_EVENT_INVALID",
            "/" + "/".join(str(part) for part in error.absolute_path),
            "Lifecycle event does not conform to the EFS state event schema.",
            {"keyword": str(error.validator)}) for error in errors]
        return {"valid": False, "replayed": False, "state": current_state,
                "diagnostics": sorted(diagnostics, key=lambda item: (item["path"], item["code"]))}
    event_id = event["eventId"]
    if seen_events is not None and event_id in seen_events:
        if seen_events[event_id] == event:
            return {"valid": True, "replayed": True, "state": current_state, "diagnostics": []}
        return {"valid": False, "replayed": False, "state": current_state,
                "diagnostics": [_diagnostic("EFS_EXECUTION_STATE_EVENT_ID_CONFLICT", "/eventId",
                    "An event ID was reused with different event content.")]}
    diagnostics = []
    for key, code in (("invocationId", "INVOCATION"), ("correlationId", "CORRELATION"),
                      ("context", "CONTEXT")):
        if event[key] != current_state.get(key):
            diagnostics.append(_diagnostic(f"EFS_EXECUTION_STATE_{code}_MISMATCH", f"/{key}",
                f"Lifecycle event {key} differs from current execution."))
    if event["fromState"] != current_state.get("state"):
        diagnostics.append(_diagnostic("EFS_EXECUTION_STATE_SOURCE_MISMATCH", "/fromState",
            "Lifecycle event prior state differs from current state."))
    if event["expectedRevision"] != current_state.get("revision"):
        diagnostics.append(_diagnostic("EFS_EXECUTION_STATE_REVISION_CONFLICT", "/expectedRevision",
            "Lifecycle event is based on a stale state revision.",
            {"expected": current_state.get("revision"), "received": event["expectedRevision"]}))
    allowed = {
        "request": ({"created"}, "requested"), "accepted": ({"requested"}, "accepted"),
        "queued": ({"requested"}, "queued"),
        "started": ({"requested", "accepted", "queued", "waiting"}, "running"),
        "progress": ({"accepted", "queued", "running"}, "running"),
        "waiting": ({"running"}, "waiting"), "resumed": ({"waiting"}, "running"),
        "succeeded": ({"requested", "accepted", "queued", "running", "waiting"}, "succeeded"),
        "failed": ({"requested", "accepted", "queued", "running", "waiting"}, "failed"),
        "cancelled": ({"created", "requested", "accepted", "queued", "running", "waiting"}, "cancelled")}
    rule = allowed.get(event["eventType"])
    if rule is None or current_state.get("state") not in rule[0]:
        diagnostics.append(_diagnostic("EFS_EXECUTION_STATE_TRANSITION_INVALID", "/eventType",
            "Lifecycle event is not legal from the current state."))
    elif event["toState"] != rule[1]:
        diagnostics.append(_diagnostic("EFS_EXECUTION_STATE_TARGET_MISMATCH", "/toState",
            "Lifecycle event target differs from the normative transition table."))
    if event["eventType"] == "cancelled":
        if event["source"] != "governed_control" or not event.get("governanceRef"):
            diagnostics.append(_diagnostic("EFS_EXECUTION_STATE_CANCELLATION_UNGOVERNED",
                "/governanceRef", "Cancellation requires an explicit governed control reference."))
    elif event["eventType"] in {"waiting", "resumed"}:
        if event["source"] != "runtime":
            diagnostics.append(_diagnostic("EFS_EXECUTION_STATE_SOURCE_INVALID", "/source",
                "Waiting/resumed signals must originate from runtime."))
    elif event["source"] != "envelope":
        diagnostics.append(_diagnostic("EFS_EXECUTION_STATE_SOURCE_INVALID", "/source",
            "This event must be derived from a validated PSI-44 envelope."))
    if diagnostics:
        diagnostics.sort(key=lambda item: (item["path"], item["code"]))
        return {"valid": False, "replayed": False, "state": current_state, "diagnostics": diagnostics}
    return {"valid": True, "replayed": False, "state": {**current_state,
        "state": rule[1], "revision": current_state["revision"] + 1, "lastEventId": event_id},
        "diagnostics": []}


def validate_execution_state(state: dict) -> dict:
    schema = json.loads(STATE_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema, registry=_schema_registry(),
        format_checker=FormatChecker()).iter_errors(state))
    diagnostics = [_diagnostic("EFS_EXECUTION_STATE_SNAPSHOT_INVALID",
        "/" + "/".join(str(part) for part in error.absolute_path),
        "State snapshot does not conform to the EFS state schema.",
        {"keyword": str(error.validator)}) for error in errors]
    return {"valid": not diagnostics, "diagnostics": sorted(diagnostics,
        key=lambda item: (item["path"], item["code"]))}
