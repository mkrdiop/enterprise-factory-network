"""Shared EFS v1 capability-contract payload validation (PSI-43).

Definition semantics remain in scripts.validate_manifest so publication, CLI,
and conformance tests share one report contract. This module provides the
runtime-facing payload boundary against an exact immutable release coordinate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urljoin, urlsplit

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012


@dataclass(frozen=True, slots=True)
class ContractCoordinate:
    """Complete exact selection; no latest lookup or version inference exists."""

    publisher_id: str
    factory_id: str
    release_version: str
    release_digest_profile: str
    release_digest_algorithm: str
    release_digest_value: str
    capability_id: str
    contract_id: str
    contract_version: str


@dataclass(frozen=True, slots=True)
class PayloadDiagnostic:
    code: str
    stage: str
    path: str
    message: str
    details: dict | None = None

    def as_dict(self) -> dict:
        item = {
            "code": self.code,
            "stage": self.stage,
            "path": self.path,
            "message": self.message,
        }
        if self.details is not None:
            item["details"] = self.details
        return item


def _pointer(parts) -> str:
    if not parts:
        return ""
    return "/" + "/".join(
        str(part).replace("~", "~0").replace("/", "~1") for part in parts
    )


def _resource_registry(
    root_schema: dict,
    schema_resources: Mapping[str, dict] | None,
):
    registry = Registry()
    resources = dict(schema_resources or {})
    root_id = root_schema.get("$id")
    root_uri = root_id if isinstance(root_id, str) else "urn:efs:contract:root"
    resources.setdefault(root_uri, root_schema)
    for uri, schema in sorted(resources.items()):
        if not isinstance(uri, str) or not isinstance(schema, dict):
            raise ValueError("Schema resource graph entries must map URI strings to schema objects")
        resource = Resource.from_contents(
            schema, default_specification=DRAFT202012
        )
        registry = registry.with_resource(uri, resource)
        declared_id = schema.get("$id")
        if isinstance(declared_id, str) and declared_id != uri:
            registry = registry.with_resource(declared_id, resource)
    return registry, root_uri, resources


def _reference_diagnostics(
    schema: dict,
    registry: Registry,
    root_uri: str,
    resources: Mapping[str, dict],
) -> list[PayloadDiagnostic]:
    diagnostics: list[PayloadDiagnostic] = []

    def walk(node, path, base_uri):
        if isinstance(node, dict):
            declared_id = node.get("$id")
            if isinstance(declared_id, str):
                base_uri = urljoin(base_uri, declared_id)
            ref = node.get("$ref")
            if isinstance(ref, str):
                parsed = urlsplit(ref)
                ref_path = parsed.path
                if parsed.scheme or parsed.netloc or ref.startswith("//"):
                    diagnostics.append(PayloadDiagnostic(
                        "EFS_SCHEMA_REF_REMOTE", "embedded_schemas",
                        _pointer(path + ["$ref"]),
                        "Absolute and network schema references are prohibited.",
                    ))
                elif ref_path and not base_uri.startswith(("http://", "https://")):
                    diagnostics.append(PayloadDiagnostic(
                        "EFS_SCHEMA_REF_UNRESOLVED", "embedded_schemas",
                        _pointer(path + ["$ref"]),
                        "Relative schema reference has no declared local resource base.",
                    ))
                else:
                    try:
                        registry.resolver(base_uri).lookup(ref)
                    except (Unresolvable, ValueError):
                        diagnostics.append(PayloadDiagnostic(
                            "EFS_SCHEMA_REF_UNRESOLVED", "embedded_schemas",
                            _pointer(path + ["$ref"]),
                            "Schema reference does not resolve in the supplied immutable resource graph.",
                        ))
            if "$dynamicRef" in node or "$dynamicAnchor" in node:
                keyword = "$dynamicRef" if "$dynamicRef" in node else "$dynamicAnchor"
                diagnostics.append(PayloadDiagnostic(
                    "EFS_SCHEMA_REF_UNSUPPORTED", "embedded_schemas",
                    _pointer(path + [keyword]),
                    "Dynamic schema references are outside the EFS v1 reference profile.",
                ))
            for key, value in node.items():
                if isinstance(value, (dict, list)):
                    walk(value, path + [key], base_uri)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, path + [index], base_uri)

    walk(schema, [], root_uri)
    return diagnostics


def validate_contract_payload(
    manifest: dict,
    coordinate: ContractCoordinate,
    direction: str,
    payload,
    *,
    schema_resources: Mapping[str, dict] | None = None,
) -> dict:
    """Validate one input/output payload against one exact manifest contract.

    The caller must obtain the manifest from a verified immutable registry
    release. This function compares every coordinate exactly and never queries
    a registry, selects a release, retrieves a URI, or falls back to latest.
    """
    diagnostics: list[PayloadDiagnostic] = []
    if direction not in {"inputs", "outputs"}:
        return {
            "valid": False,
            "diagnostics": [PayloadDiagnostic(
                "EFS_CONTRACT_DIRECTION_INVALID", "payload", "",
                "Direction must be exactly 'inputs' or 'outputs'.",
            ).as_dict()],
        }

    publisher = manifest.get("publisher", {})
    factory = manifest.get("factory", {})
    release = manifest.get("release", {})
    digest = release.get("digest", {}) if isinstance(release, dict) else {}
    expected = (
        coordinate.publisher_id,
        coordinate.factory_id,
        coordinate.release_version,
        coordinate.release_digest_profile,
        coordinate.release_digest_algorithm,
        coordinate.release_digest_value,
    )
    actual = (
        publisher.get("id") if isinstance(publisher, dict) else None,
        factory.get("id") if isinstance(factory, dict) else None,
        release.get("version") if isinstance(release, dict) else None,
        digest.get("profile") if isinstance(digest, dict) else None,
        digest.get("algorithm") if isinstance(digest, dict) else None,
        digest.get("value") if isinstance(digest, dict) else None,
    )
    if actual != expected:
        diagnostics.append(PayloadDiagnostic(
            "EFS_CONTRACT_RELEASE_COORDINATE_MISMATCH", "payload", "",
            "Supplied manifest does not match the exact publisher, Factory, release and digest coordinate.",
        ))
        return {"valid": False, "diagnostics": [item.as_dict() for item in diagnostics]}

    capabilities = manifest.get("capabilities", [])
    matches = [
        (index, item) for index, item in enumerate(capabilities)
        if isinstance(item, dict) and item.get("id") == coordinate.capability_id
    ]
    if len(matches) != 1:
        diagnostics.append(PayloadDiagnostic(
            "EFS_CONTRACT_CAPABILITY_NOT_UNIQUE", "payload", "/capabilities",
            "Exact capability identifier must resolve to one capability in the selected release.",
        ))
        return {"valid": False, "diagnostics": [item.as_dict() for item in diagnostics]}

    index, capability = matches[0]
    contract = capability.get("contract", {})
    if (
        not isinstance(contract, dict)
        or contract.get("id") != coordinate.contract_id
        or contract.get("version") != coordinate.contract_version
    ):
        diagnostics.append(PayloadDiagnostic(
            "EFS_CONTRACT_VERSION_MISMATCH", "payload",
            f"/capabilities/{index}/contract",
            "Capability contract does not match the exact contract ID and version coordinate.",
        ))
        return {"valid": False, "diagnostics": [item.as_dict() for item in diagnostics]}

    schema = contract.get(direction)
    if not isinstance(schema, dict):
        diagnostics.append(PayloadDiagnostic(
            "EFS_CONTRACT_SCHEMA_MISSING", "payload",
            f"/capabilities/{index}/contract/{direction}",
            "Selected capability contract has no object schema for this direction.",
        ))
        return {"valid": False, "diagnostics": [item.as_dict() for item in diagnostics]}

    try:
        Draft202012Validator.check_schema(schema)
        registry, root_uri, resources = _resource_registry(schema, schema_resources)
        diagnostics.extend(_reference_diagnostics(schema, registry, root_uri, resources))
        if diagnostics:
            return {"valid": False, "diagnostics": [item.as_dict() for item in diagnostics]}
        validator = Draft202012Validator(schema, registry=registry)
        errors = sorted(
            validator.iter_errors(payload),
            key=lambda error: (_pointer(error.absolute_path), str(error.validator)),
        )
        for error in errors:
            diagnostics.append(PayloadDiagnostic(
                "EFS_CONTRACT_PAYLOAD_INVALID", "payload",
                _pointer(error.absolute_path),
                "Payload does not satisfy the selected capability contract schema.",
                {"keyword": str(error.validator)},
            ))
    except (SchemaError, ValueError, Unresolvable) as exc:
        diagnostics.append(PayloadDiagnostic(
            "EFS_CONTRACT_SCHEMA_INVALID", "payload",
            f"/capabilities/{index}/contract/{direction}",
            "Selected capability contract schema or local resource graph is invalid.",
            {"reason": type(exc).__name__},
        ))

    diagnostics.sort(key=lambda item: (
        item.stage, item.path, item.code, item.message,
    ))
    return {"valid": not diagnostics, "diagnostics": [item.as_dict() for item in diagnostics]}


def validate_schema_references(
    schema: dict,
    schema_resources: Mapping[str, dict] | None = None,
) -> list[dict]:
    """Return deterministic diagnostics for references in one local schema graph."""
    try:
        registry, root_uri, resources = _resource_registry(schema, schema_resources)
        diagnostics = _reference_diagnostics(schema, registry, root_uri, resources)
    except (SchemaError, ValueError, Unresolvable) as exc:
        diagnostics = [PayloadDiagnostic(
            "EFS_CONTRACT_SCHEMA_INVALID", "embedded_schemas", "",
            "Schema resource graph is invalid.",
            {"reason": type(exc).__name__},
        )]
    diagnostics.sort(key=lambda item: (item.stage, item.path, item.code, item.message))
    return [item.as_dict() for item in diagnostics]
