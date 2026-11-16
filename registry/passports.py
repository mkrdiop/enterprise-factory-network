"""Deterministic Factory Passport projections for registered EFS v1 releases.

A Passport is a read-only derived representation. Registry records and the
verified EFS release artifact remain authoritative for identity and content.
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import rfc8785


PASSPORT_VERSION = "1.0"


class PassportSourceMismatch(RuntimeError):
    """Registry release coordinates disagree with the verified manifest."""


def _pointer(parent: str, token: str | int) -> str:
    escaped = str(token).replace("~", "~0").replace("/", "~1")
    return f"{parent}/{escaped}"


def _copy_with_provenance(
    value: Any,
    target_path: str,
    source_path: str,
    provenance: list[dict[str, str]],
    *,
    source: str = "manifest",
) -> Any:
    """Deep-copy a source value and record provenance for every leaf/container."""
    if isinstance(value, dict):
        result = {}
        if not value:
            provenance.append(
                {
                    "target": target_path,
                    "source": source,
                    "sourcePointer": source_path,
                    "rule": "copy",
                }
            )
        for key, child in value.items():
            result[key] = _copy_with_provenance(
                child,
                _pointer(target_path, key),
                _pointer(source_path, key),
                provenance,
                source=source,
            )
        return result
    if isinstance(value, list):
        result = []
        if not value:
            provenance.append(
                {
                    "target": target_path,
                    "source": source,
                    "sourcePointer": source_path,
                    "rule": "copy",
                }
            )
        for index, child in enumerate(value):
            result.append(
                _copy_with_provenance(
                    child,
                    _pointer(target_path, index),
                    _pointer(source_path, index),
                    provenance,
                    source=source,
                )
            )
        return result
    provenance.append(
        {
            "target": target_path,
            "source": source,
            "sourcePointer": source_path,
            "rule": "copy",
        }
    )
    return deepcopy(value)


def build_factory_passport(
    manifest: dict[str, Any],
    registry_record: dict[str, Any],
) -> dict[str, Any]:
    """Build a Passport only when registry coordinates match the verified manifest."""
    publisher_id = manifest["publisher"]["id"]
    factory_id = manifest["factory"]["id"]
    version = manifest["release"]["version"]
    digest = manifest["release"]["digest"]

    expected_digest = {
        "profile": digest["profile"],
        "algorithm": digest["algorithm"],
        "value": digest["value"],
    }
    if (
        registry_record["publisherId"] != publisher_id
        or registry_record["factoryId"] != factory_id
        or registry_record["version"] != version
        or registry_record["digest"] != expected_digest
    ):
        raise PassportSourceMismatch("registry release coordinates do not match verified manifest")

    provenance: list[dict[str, str]] = [
        {
            "target": "/passportVersion",
            "source": "derivation",
            "sourcePointer": "/passportVersion",
            "rule": "passport-contract-version",
        }
    ]
    passport: dict[str, Any] = {
        "passportVersion": PASSPORT_VERSION,
        "source": {
            "efsVersion": _copy_with_provenance(
                manifest["efsVersion"], "/source/efsVersion", "/efsVersion", provenance
            ),
            "publisherId": _copy_with_provenance(
                publisher_id, "/source/publisherId", "/publisher/id", provenance
            ),
            "factoryId": _copy_with_provenance(
                factory_id, "/source/factoryId", "/factory/id", provenance
            ),
            "releaseVersion": _copy_with_provenance(
                version, "/source/releaseVersion", "/release/version", provenance
            ),
            "digest": _copy_with_provenance(
                expected_digest, "/source/digest", "/release/digest", provenance
            ),
            "registry": {
                "releaseRecordId": _copy_with_provenance(
                    registry_record["releaseRecordId"],
                    "/source/registry/releaseRecordId",
                    "/registry/releaseRecordId",
                    provenance,
                    source="registry",
                ),
                "publishedAt": _copy_with_provenance(
                    registry_record["publishedAt"],
                    "/source/registry/publishedAt",
                    "/registry/publishedAt",
                    provenance,
                    source="registry",
                ),
                "artifactByteLength": _copy_with_provenance(
                    registry_record["byteLength"],
                    "/source/registry/artifactByteLength",
                    "/registry/byteLength",
                    provenance,
                    source="registry",
                ),
            },
        },
        "publisher": {
            "id": _copy_with_provenance(
                publisher_id, "/publisher/id", "/publisher/id", provenance
            )
        },
        "factory": _copy_with_provenance(
            manifest["factory"], "/factory", "/factory", provenance
        ),
        "release": {},
        "capabilities": _copy_with_provenance(
            manifest["capabilities"], "/capabilities", "/capabilities", provenance
        ),
        "execution": _copy_with_provenance(
            manifest["execution"], "/execution", "/execution", provenance
        ),
        "dependencies": _copy_with_provenance(
            manifest["dependencies"], "/dependencies", "/dependencies", provenance
        ),
        "policies": _copy_with_provenance(
            manifest["policies"], "/policies", "/policies", provenance
        ),
        "assurance": {
            "artifactIntegrity": "verified",
            "publisherAuthentication": "not_evaluated",
            "publisherTrust": "not_evaluated",
            "signatureVerification": "not_evaluated",
            "authorization": "not_evaluated",
            "signatureMaterial": "not_part_of_digest_artifact",
        },
        "summary": {
            "capabilityCount": len(manifest["capabilities"]),
            "dependencyCount": len(manifest["dependencies"]),
            "policyDeclarationCount": len(manifest["policies"].get("declarations", [])),
            "policyReferenceCount": len(manifest["policies"].get("references", [])),
            "endpointCount": sum(len(item["endpoints"]) for item in manifest["capabilities"]),
        },
    }
    for field in ("artifactIntegrity",):
        provenance.append({
            "target": f"/assurance/{field}",
            "source": "derivation",
            "sourcePointer": "/registry/artifactReadback",
            "rule": "verified-artifact-readback",
        })
    for field in ("publisherAuthentication", "publisherTrust", "signatureVerification", "authorization"):
        provenance.append({
            "target": f"/assurance/{field}",
            "source": "derivation",
            "sourcePointer": "/registry/verification",
            "rule": "not-evaluated-by-registry",
        })
    provenance.append({
        "target": "/assurance/signatureMaterial",
        "source": "derivation",
        "sourcePointer": "/release/digest",
        "rule": "excluded-from-digest-artifact",
    })
    for field, source_path in (
        ("capabilityCount", "/capabilities"),
        ("dependencyCount", "/dependencies"),
        ("policyDeclarationCount", "/policies"),
        ("policyReferenceCount", "/policies"),
        ("endpointCount", "/capabilities"),
    ):
        provenance.append({
            "target": f"/summary/{field}",
            "source": "manifest",
            "sourcePointer": source_path,
            "rule": {\n                "endpointCount": "count-endpoint-items",\n                "policyDeclarationCount": "count-policy-declarations",\n                "policyReferenceCount": "count-policy-references",\n            }.get(field, "count-items"),
        })

    if "name" in manifest["publisher"]:
        passport["publisher"]["name"] = _copy_with_provenance(
            manifest["publisher"]["name"],
            "/publisher/name",
            "/publisher/name",
            provenance,
        )
    if "createdAt" in manifest["release"]:
        passport["release"]["createdAt"] = _copy_with_provenance(
            manifest["release"]["createdAt"],
            "/release/createdAt",
            "/release/createdAt",
            provenance,
        )
    if "extensions" in manifest:
        passport["extensions"] = _copy_with_provenance(
            manifest["extensions"], "/extensions", "/extensions", provenance
        )

    provenance.sort(key=lambda item: (item["target"], item["source"], item["sourcePointer"]))
    passport["provenance"] = provenance
    return passport


def canonical_passport_json(passport: dict[str, Any]) -> bytes:
    """RFC 8785 serialization for stable machine-readable output."""
    return rfc8785.dumps(passport)


def _json_block(value: Any) -> list[str]:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    return ["\x60\x60\x60json", rendered, "\x60\x60\x60"]


def render_factory_passport_markdown(passport: dict[str, Any]) -> str:
    """Render a deterministic human-readable view of the same Passport object."""
    source = passport["source"]
    factory = passport["factory"]
    publisher = passport["publisher"]
    release = passport["release"]
    lines = [
        f"# Factory Passport — {factory['name']}",
        "",
        f"- **Publisher:** {publisher.get('name', publisher['id'])}",
        f"- **Publisher ID:** `{publisher['id']}`",
        f"- **Factory ID:** `{factory['id']}`",
        f"- **Release:** `{source['releaseVersion']}`",
        f"- **EFS version:** `{source['efsVersion']}`",
        f"- **Digest:** `{source['digest']['profile']}:{source['digest']['value']}`",
        f"- **Registry release record:** `{source['registry']['releaseRecordId']}`",
        f"- **Published at:** `{source['registry']['publishedAt']}`",
        "",
        "## Capabilities",
        "",
    ]
    for capability in passport["capabilities"]:
        lines.extend(
            [
                f"### {capability['name']}",
                "",
                f"- **Capability ID:** `{capability['id']}`",
            ]
        )
        if capability.get("description"):
            lines.append(f"- **Description:** {capability['description']}")
        contract = capability["contract"]
        lines.extend(
            [
                f"- **Contract:** `{contract['id']}@{contract['version']}`",
                f"- **Endpoints:** {len(capability['endpoints'])}",
                f"- **Declared execution profiles:** {', '.join(capability.get('executionProfiles', [])) or 'None'}",
                "",
                "**Contract details**",
                "",
                *_json_block(contract),
                "",
                "**Endpoint declarations**",
                "",
                *_json_block(capability["endpoints"]),
                "",
            ]
        )
    if factory.get("description"):
        lines[lines.index("## Capabilities"):lines.index("## Capabilities")] = [
            "## Description", "", factory["description"], ""
        ]
    lines.extend(
        [
            "## Execution",
            "",
            f"- **Profile source:** `{passport['execution']['source']}`",
            "",
            *_json_block(passport["execution"]),
            "",
        ]
    )
    if passport["execution"]["source"] == "manifest":
        for profile in passport["execution"]["profiles"]:
            lines.append(
                f"- **Profile:** `{profile['id']}` — modes: {', '.join(profile['modes'])}"
            )
    else:
        for profile in passport["execution"]["profileReferences"]:
            lines.append(
                f"- **External profile:** `{profile['id']}@{profile['version']}` "
                f"({profile['digest']['algorithm']}:{profile['digest']['value']})"
            )
    lines.extend(
        [
            "",
            "## Dependencies",
            "",
            f"{passport['summary']['dependencyCount']} dependency declaration(s).",
            "",
            *_json_block(passport["dependencies"]),
            "",
            "## Policies",
            "",
            f"{passport['summary']['policyDeclarationCount']} embedded declaration(s); "
            f"{passport['summary']['policyReferenceCount']} external reference(s).",
            "",
            *_json_block(passport["policies"]),
            "",
            "## Assurance",
            "",
            "- **Artifact integrity:** Verified against the registered release digest.",
            "- **Publisher authentication:** Not evaluated.",
            "- **Publisher trust:** Not evaluated.",
            "- **Signature verification:** Not evaluated.",
            "- **Authorization:** Not evaluated.",
            "- **Signature material:** Not part of the digest-addressed artifact.",
            "",
            "## Provenance",
            "",
            "| Passport field | Source | Source pointer | Rule |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in passport["provenance"]:
        values = [
            item["target"],
            item["source"],
            item["sourcePointer"],
            item["rule"],
        ]
        lines.append("| " + " | ".join(value.replace("|", "\\|") for value in values) + " |")
    return "\n".join(lines) + "\n"
