"""PSI-44 transport-neutral EFS execution envelope validation.

This module validates envelope structure, exact manifest binding and causal
message relationships. Concrete inputs, outputs and error details are delegated
to the PSI-43 payload validator through an explicit adapter callback; no second
payload-schema implementation is introduced here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas/execution/v1/execution-envelope.schema.json"


def _pointer(parts) -> str:
    if not parts:
        return ""
    return "/" + "/".join(
        str(part).replace("~", "~0").replace("/", "~1") for part in parts
    )


def _diagnostic(code, path, message, details=None):
    item = {
        "code": code,
        "stage": "execution",
        "path": path,
        "message": message,
    }
    if details is not None:
        item["details"] = details
    return item


def _schema_diagnostics(envelope, schema):
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(envelope),
        key=lambda error: (_pointer(error.absolute_path), str(error.validator)),
    )
    return [
        _diagnostic(
            "EFS_EXECUTION_ENVELOPE_INVALID",
            _pointer(error.absolute_path),
            "Execution envelope does not satisfy the EFS v1 envelope schema.",
            {"keyword": str(error.validator)},
        )
        for error in errors
    ]


def validate_execution_envelope(
    envelope: dict,
    manifest: dict,
    *,
    payload_validator: Callable | None = None,
    schema_path: str | Path = DEFAULT_SCHEMA,
) -> dict:
    """Validate one envelope against the exact manifest and optional PSI-43 port.

    payload_validator signature:
      callback(manifest, context, direction, payload, error_code=None) -> report
    The callback is expected to adapt to registry.capability_contracts.
    """
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    diagnostics = _schema_diagnostics(envelope, schema)
    if diagnostics:
        return {"valid": False, "diagnostics": diagnostics}

    context = envelope["context"]
    publisher = manifest.get("publisher", {})
    factory = manifest.get("factory", {})
    release = manifest.get("release", {})
    digest = release.get("digest", {}) if isinstance(release, dict) else {}
    expected = {
        "publisherId": publisher.get("id"),
        "factoryId": factory.get("id"),
        "releaseVersion": release.get("version"),
        "releaseDigest": digest,
    }
    for key, value in expected.items():
        if context.get(key) != value:
            diagnostics.append(_diagnostic(
                "EFS_EXECUTION_CONTEXT_MISMATCH", f"/context/{key}",
                "Envelope context does not match the selected immutable release.",
            ))

    capabilities = manifest.get("capabilities", [])
    selected = [
        (index, capability) for index, capability in enumerate(capabilities)
        if isinstance(capability, dict)
        and capability.get("id") == context["capabilityId"]
    ]
    if len(selected) != 1:
        diagnostics.append(_diagnostic(
            "EFS_EXECUTION_CAPABILITY_NOT_UNIQUE", "/context/capabilityId",
            "Capability identifier must resolve to exactly one capability in the selected release.",
        ))
        return {"valid": False, "diagnostics": diagnostics}

    capability_index, capability = selected[0]
    contract = capability.get("contract", {})
    contract_context = context["contract"]
    if (
        not isinstance(contract, dict)
        or contract.get("id") != contract_context["id"]
        or contract.get("version") != contract_context["version"]
    ):
        diagnostics.append(_diagnostic(
            "EFS_EXECUTION_CONTRACT_MISMATCH", "/context/contract",
            "Envelope contract does not match the exact declared contract ID and version.",
        ))

    capability_profiles = capability.get("executionProfiles")
    profile_id = context["executionProfileId"]
    if not isinstance(capability_profiles, list) or profile_id not in capability_profiles:
        diagnostics.append(_diagnostic(
            "EFS_EXECUTION_PROFILE_UNRESOLVED", "/context/executionProfileId",
            "Execution profile is not explicitly selected by this capability in the exact release.",
        ))
    else:
        execution = manifest.get("execution", {})
        if execution.get("source") == "manifest":
            profiles = [
                profile for profile in execution.get("profiles", [])
                if isinstance(profile, dict) and profile.get("id") == profile_id
            ]
            if len(profiles) != 1 or context["executionMode"] not in profiles[0].get("modes", []):
                diagnostics.append(_diagnostic(
                    "EFS_EXECUTION_MODE_UNDECLARED", "/context/executionMode",
                    "Execution mode is not declared by the exactly selected embedded execution profile.",
                ))
        elif execution.get("source") == "external":
            references = [
                reference for reference in execution.get("profileReferences", [])
                if isinstance(reference, dict) and reference.get("id") == profile_id
            ]
            if len(references) != 1:
                diagnostics.append(_diagnostic(
                    "EFS_EXECUTION_PROFILE_UNRESOLVED", "/context/executionProfileId",
                    "External execution profile reference must resolve exactly once.",
                ))
            # The external profile's mode declaration is not inferred or fetched
            # here. The adapter must resolve and verify that immutable artifact.

    message_type = envelope["messageType"]
    direction = None
    payload = None
    error_code = None
    if message_type in {"request", "event"}:
        direction, payload = "inputs", envelope["payload"]
    elif message_type == "result":
        direction, payload = "outputs", envelope["payload"]
    elif message_type == "progress" and envelope["eventKind"] == "data":
        direction, payload = "outputs", envelope["payload"]
    elif message_type == "error":
        error_code = envelope["error"]["code"]
        declared = [
            item for item in contract.get("errors", [])
            if isinstance(item, dict) and item.get("code") == error_code
        ]
        if len(declared) != 1:
            diagnostics.append(_diagnostic(
                "EFS_EXECUTION_ERROR_UNDECLARED", "/error/code",
                "Error code is not declared exactly once by the selected contract.",
            ))
        elif "details" in envelope["error"]:
            direction, payload = "errors", envelope["error"]["details"]

    if direction is not None:
        if payload_validator is None:
            diagnostics.append(_diagnostic(
                "EFS_EXECUTION_PAYLOAD_VALIDATOR_REQUIRED", "/payload",
                "Payload-bearing envelope requires the shared PSI-43 contract payload validator.",
            ))
        else:
            report = payload_validator(
                manifest, context, direction, payload, error_code=error_code
            )
            if not report.get("valid", False):
                for item in report.get("diagnostics", []):
                    diagnostics.append(_diagnostic(
                        item.get("code", "EFS_EXECUTION_PAYLOAD_INVALID"),
                        item.get("path", ""),
                        item.get("message", "Payload failed contract validation."),
                        item.get("details"),
                    ))

    diagnostics.sort(key=lambda item: (
        item["stage"], item["path"], item["code"], item["message"],
        json.dumps(item.get("details", {}), sort_keys=True),
    ))
    return {"valid": not diagnostics, "diagnostics": diagnostics}


def validate_execution_transition(previous: dict, current: dict) -> dict:
    """Check one observed causal edge; PSI-45 owns lifecycle state transitions."""
    diagnostics = []
    previous_type = previous.get("messageType")
    current_type = current.get("messageType")
    mode = previous.get("context", {}).get("executionMode")
    allowed = {
        ("request", "sync"): {"result", "error"},
        ("request", "async"): {"accepted", "result", "error"},
        ("request", "streaming"): {"accepted", "progress", "result", "error"},
        ("event", "event"): {"result", "error"},
        ("accepted", "async"): {"result", "error"},
        ("accepted", "streaming"): {"progress", "result", "error"},
        ("progress", "streaming"): {"progress", "result", "error"},
    }
    if current_type not in allowed.get((previous_type, mode), set()):
        diagnostics.append(_diagnostic(
            "EFS_EXECUTION_TRANSITION_INVALID", "/messageType",
            "Message type is not permitted as the next observed interaction message for this mode.",
        ))
    if previous.get("invocationId") != current.get("invocationId"):
        diagnostics.append(_diagnostic(
            "EFS_EXECUTION_INVOCATION_MISMATCH", "/invocationId",
            "Invocation identifier must remain unchanged throughout one interaction.",
        ))
    if previous.get("correlationId") != current.get("correlationId"):
        diagnostics.append(_diagnostic(
            "EFS_EXECUTION_CORRELATION_MISMATCH", "/correlationId",
            "Correlation identifier must propagate unchanged throughout one interaction.",
        ))
    if previous.get("context") != current.get("context"):
        diagnostics.append(_diagnostic(
            "EFS_EXECUTION_CONTEXT_MISMATCH", "/context",
            "Exact release, capability, contract, profile and mode context must remain unchanged.",
        ))
    if current.get("causationId") != previous.get("messageId"):
        diagnostics.append(_diagnostic(
            "EFS_EXECUTION_CAUSATION_MISMATCH", "/causationId",
            "Causation identifier must reference the immediately preceding message in this observed chain.",
        ))
    diagnostics.sort(key=lambda item: (item["path"], item["code"]))
    return {"valid": not diagnostics, "diagnostics": diagnostics}
