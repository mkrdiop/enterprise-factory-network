"""Layered, deterministic EFS v1 manifest conformance validator.

Conformance is structural/profile validation only. It does not verify release
digests or signatures, retrieve external artifacts, evaluate policies, resolve
dependencies, or authorize runtime execution.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit, urlparse

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

DIALECT = "https://json-schema.org/draft/2020-12/schema"
PROFILE = "efs-v1"
STAGES = ("parsing", "structural", "embedded_schemas", "profile")
FORMAT_CHECKER = FormatChecker()


class DuplicateMemberError(ValueError):
    """Raised when a JSON object contains a duplicate member name."""


class InvalidJSONConstant(ValueError):
    """Raised for JavaScript-only constants such as NaN and Infinity."""


def reject_non_json_constant(value):
    raise InvalidJSONConstant(f"non-JSON numeric constant: {value}")


def reject_duplicate_members(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateMemberError(f"duplicate JSON object member: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    # read_bytes + strict decode distinguishes invalid UTF-8 from invalid JSON.
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="strict")
    return json.loads(text, object_pairs_hook=reject_duplicate_members, parse_constant=reject_non_json_constant)


def pointer(parts) -> str:
    if not parts:
        return ""
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def diagnostic(code: str, stage: str, path: str, message: str, details=None):
    item = {"code": code, "stage": stage, "path": path, "message": message}
    if details is not None:
        item["details"] = details
    return item


def _walk_schema(value, path, diagnostics):
    """Enforce the EFS v1 local-only reference subset without network access."""
    if isinstance(value, dict):
        for keyword in ("$dynamicRef", "$dynamicAnchor"):
            if keyword in value:
                diagnostics.append(diagnostic(
                    "EFS_SCHEMA_REF_UNSUPPORTED", "embedded_schemas",
                    pointer(path + [keyword]),
                    f"{keyword} is outside the profiled EFS v1 reference subset.",
                ))
        ref = value.get("$ref")
        if isinstance(ref, str):
            parsed = urlparse(ref)
            if parsed.scheme or parsed.netloc or ref.startswith("//"):
                diagnostics.append(diagnostic(
                    "EFS_SCHEMA_REF_REMOTE", "embedded_schemas",
                    pointer(path + ["$ref"]),
                    "Absolute and network schema references are prohibited; bundle schema resources with the immutable release.",
                ))
        for key, child in value.items():
            _walk_schema(child, path + [key], diagnostics)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_schema(child, path + [index], diagnostics)


def _embedded_schema_checks(manifest):
    diagnostics = []
    capabilities = manifest.get("capabilities", [])
    if not isinstance(capabilities, list):
        return diagnostics
    for i, capability in enumerate(capabilities):
        if not isinstance(capability, dict):
            continue
        contract = capability.get("contract")
        if not isinstance(contract, dict):
            continue
        for direction in ("inputs", "outputs"):
            schema = contract.get(direction)
            if not isinstance(schema, dict):
                continue
            base = ["capabilities", i, "contract", direction]
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as exc:
                diagnostics.append(diagnostic(
                    "EFS_EMBEDDED_SCHEMA_INVALID", "embedded_schemas",
                    pointer(base), "Embedded contract schema is not valid Draft 2020-12.",
                    {"validator": str(exc.validator), "message": exc.message},
                ))
                continue
            _walk_schema(schema, base, diagnostics)
        errors = contract.get("errors", [])
        if isinstance(errors, list):
            for j, error in enumerate(errors):
                if not isinstance(error, dict) or "schema" not in error:
                    continue
                schema = error["schema"]
                base = ["capabilities", i, "contract", "errors", j, "schema"]
                if not isinstance(schema, dict):
                    diagnostics.append(diagnostic(
                        "EFS_EMBEDDED_SCHEMA_INVALID", "embedded_schemas", pointer(base),
                        "Contract error schema must be a JSON object.",
                    ))
                    continue
                try:
                    Draft202012Validator.check_schema(schema)
                except SchemaError as exc:
                    diagnostics.append(diagnostic(
                        "EFS_EMBEDDED_SCHEMA_INVALID", "embedded_schemas",
                        pointer(base), "Embedded error schema is not valid Draft 2020-12.",
                        {"validator": str(exc.validator), "message": exc.message},
                    ))
                    continue
                _walk_schema(schema, base, diagnostics)
    return diagnostics


_PCT = re.compile(r"%([0-9A-Fa-f]{2})")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*$")
_PATH_CHARS = re.compile(r"(?:[A-Za-z0-9._~!def _profile_checks(manifest):
    diagnostics = []
    publisher = manifest.get("publisher")
    if isinstance(publisher, dict) and isinstance(publisher.get("id"), str):
        publisher_id = publisher["id"]
        canonical = canonical_publisher_uri(publisher_id)
        if canonical is None:
            diagnostics.append(diagnostic(
                "EFS_PUBLISHER_URI_INVALID", "profile", "/publisher/id",
                "Publisher identifier must be a valid absolute RFC 3986 URI under efs-uri-c14n-1.",
            ))
        elif canonical != publisher_id:
            diagnostics.append(diagnostic(
                "EFS_PUBLISHER_URI_NON_CANONICAL", "profile", "/publisher/id",
                "Publisher identifier is not in canonical efs-uri-c14n-1 serialization.",
                {"canonical": canonical},
            ))
'()*+,;=:@/-]|%[0-9A-Fa-f]{2})*\\Z")
_REG_NAME_CHARS = re.compile(r"(?:[A-Za-z0-9._~!def _profile_checks(manifest):
    diagnostics = []
'()*+,;=-]|%[0-9A-Fa-f]{2})*\\Z")
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def _normalize_percent_encoding(component: str) -> str:
    """Decode only RFC 3986 unreserved octets and uppercase other triplets."""
    def replace(match):
        value = int(match.group(1), 16)
        char = chr(value)
        return char if char in _UNRESERVED else f"%{value:02X}"
    return _PCT.sub(replace, component)


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 section 5.2.4 dot-segment removal algorithm."""
    source = path
    output = ""
    while source:
        if source.startswith("../"):
            source = source[3:]
        elif source.startswith("./"):
            source = source[2:]
        elif source.startswith("/./"):
            source = source[2:]
        elif source == "/.":
            source = "/"
        elif source.startswith("/../"):
            source = source[3:]
            output = output[:output.rfind("/")] if "/" in output else ""
        elif source == "/..":
            source = "/"
            output = output[:output.rfind("/")] if "/" in output else ""
        elif source in (".", ".."):
            source = ""
        else:
            start = 1 if source.startswith("/") else 0
            next_slash = source.find("/", start)
            if next_slash == -1:
                output += source
                source = ""
            else:
                output += source[:next_slash]
                source = source[next_slash:]
    return output


def canonical_publisher_uri(value: str) -> str | None:
    """Return efs-uri-c14n-1 serialization, or None for an invalid URI.

    This is a local syntax operation only: it performs no dereferencing,
    DNS resolution, redirects, scheme handlers or key discovery.
    """
    if not value or not value.isascii() or any(ord(ch) <= 0x20 or ord(ch) == 0x7f for ch in value):
        return None
    if "?" in value or "#" in value or any(ch.isspace() for ch in value):
        return None
    match = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):(.*)\\Z", value, re.DOTALL)
    if not match:
        return None
    scheme, remainder = match.groups()
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme.lower() != scheme.lower() or parsed.query or parsed.fragment:
        return None
    if not _PATH_CHARS.fullmatch(parsed.path):
        return None
    if _PCT.search(re.sub(r"%[0-9A-Fa-f]{2}", "", value)):
        return None

    authority = ""
    has_authority = remainder.startswith("//")
    if has_authority:
        raw_authority = remainder[2:].split("/", 1)[0]
        if "@" in raw_authority:
            return None
        try:
            # Accessing .port validates numeric syntax and the 0..65535 range.
            _ = parsed.port
        except ValueError:
            return None
        if raw_authority.startswith("["):
            close = raw_authority.find("]")
            if close < 0:
                return None
            literal = raw_authority[1:close]
            suffix = raw_authority[close + 1:]
            if suffix and not re.fullmatch(r":[0-9]*", suffix):
                return None
            if literal.lower().startswith("v"):
                if not re.fullmatch(r"v[0-9A-Fa-f]+\\.[A-Za-z0-9._~!def _profile_checks(manifest):
    diagnostics = []
'()*+,;=:-]+", literal):
                    return None
            else:
                try:
                    ipaddress.IPv6Address(literal)
                except ValueError:
                    return None
            authority = "[" + literal.lower() + "]" + suffix
        else:
            if raw_authority.count(":") > 1:
                return None
            if ":" in raw_authority:
                host, port_suffix = raw_authority.rsplit(":", 1)
                if not port_suffix.isdigit() and port_suffix != "":
                    return None
                suffix = ":" + port_suffix
            else:
                host, suffix = raw_authority, ""
            if not _REG_NAME_CHARS.fullmatch(host):
                return None
            authority = _normalize_percent_encoding(host.lower()) + suffix

    path = _normalize_percent_encoding(parsed.path)
    path = _remove_dot_segments(path) if path else path
    return scheme.lower() + ":" + ("//" + authority if has_authority else "") + path


def _profile_checks(manifest):
    diagnostics = []
    execution = manifest.get("execution")
    if isinstance(execution, dict):
        source = execution.get("source")
        if source == "manifest" and not execution.get("profiles"):
            diagnostics.append(diagnostic(
                "EFS_PROFILE_INVARIANT_FAILED", "profile", "/execution/profiles",
                "Manifest-sourced execution requires at least one embedded profile.",
            ))
        elif source == "external" and not execution.get("profileReferences"):
            diagnostics.append(diagnostic(
                "EFS_PROFILE_INVARIANT_FAILED", "profile", "/execution/profileReferences",
                "Externally sourced execution requires at least one profile reference.",
            ))
    return diagnostics


def _sort_diagnostics(items):
    return sorted(items, key=lambda d: (
        d["stage"], d["path"], d["code"], d["message"],
        json.dumps(d.get("details", {}), sort_keys=True, ensure_ascii=False),
    ))


def _finalize(report: dict) -> dict:
    """Apply the canonical diagnostic ordering on every success and failure path."""
    report["diagnostics"] = _sort_diagnostics(report["diagnostics"])
    report["valid"] = all(value == "passed" for value in report["stages"].values())
    return report


def _structural_code(error) -> str:
    """Map JSON Schema keywords to stable public diagnostic identifiers."""
    if error.validator == "required":
        return "EFS_SCHEMA_REQUIRED"
    if error.validator == "type":
        return "EFS_SCHEMA_TYPE"
    if error.validator in {"enum", "const"}:
        return "EFS_SCHEMA_ENUM"
    if error.validator == "format":
        return "EFS_SCHEMA_FORMAT"
    return "EFS_SCHEMA_CONSTRAINT"


def _structural_path(error) -> str:
    """Point to the missing/invalid property where jsonschema exposes its name."""
    parts = list(error.absolute_path)
    if error.validator == "required" and isinstance(error.validator_value, list):
        missing = [name for name in error.validator_value
                   if isinstance(error.instance, dict) and name not in error.instance]
        if len(missing) == 1:
            parts.append(missing[0])
    return pointer(parts)


def validate_report(manifest_path: Path, schema_path: Path) -> dict:
    stages = {name: "not_run" for name in STAGES}
    diagnostics = []
    report = {
        "reportVersion": "1.0",
        "conformanceProfile": PROFILE,
        "schemaDialect": DIALECT,
        "valid": False,
        "stages": stages,
        "diagnostics": diagnostics,
    }

    try:
        manifest = load_json(manifest_path)
    except DuplicateMemberError as exc:
        stages["parsing"] = "failed"
        diagnostics.append(diagnostic(
            "EFS_JSON_DUPLICATE_MEMBER", "parsing", "",
            "JSON object contains a duplicate member name.", {"message": str(exc)},
        ))
        return _finalize(report)
    except UnicodeDecodeError as exc:
        stages["parsing"] = "failed"
        diagnostics.append(diagnostic(
            "EFS_JSON_INVALID_ENCODING", "parsing", "",
            "Input is not valid UTF-8.", {"message": str(exc)},
        ))
        return _finalize(report)
    except (json.JSONDecodeError, InvalidJSONConstant, OSError) as exc:
        stages["parsing"] = "failed"
        diagnostics.append(diagnostic(
            "EFS_JSON_INVALID", "parsing", "",
            "Input could not be read as valid JSON.", {"message": str(exc)},
        ))
        return _finalize(report)
    stages["parsing"] = "passed"

    try:
        schema = load_json(schema_path)
        Draft202012Validator.check_schema(schema)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, SchemaError) as exc:
        stages["structural"] = "failed"
        diagnostics.append(diagnostic(
            "EFS_SCHEMA_INVALID", "structural", "",
            "The normative manifest schema could not be loaded or is not valid Draft 2020-12.",
            {"message": str(exc)},
        ))
        return _finalize(report)

    errors = sorted(
        Draft202012Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(manifest),
        key=lambda e: (pointer(list(e.absolute_path)), e.validator or "", e.message),
    )
    if errors:
        stages["structural"] = "failed"
        for error in errors:
            diagnostics.append(diagnostic(
                _structural_code(error), "structural", _structural_path(error),
                error.message, {"keyword": error.validator},
            ))
        return _finalize(report)
    stages["structural"] = "passed"

    embedded = _embedded_schema_checks(manifest)
    if embedded:
        stages["embedded_schemas"] = "failed"
        diagnostics.extend(embedded)
        return _finalize(report)
    stages["embedded_schemas"] = "passed"

    profile = _profile_checks(manifest)
    if profile:
        stages["profile"] = "failed"
        diagnostics.extend(profile)
        return _finalize(report)
    stages["profile"] = "passed"

    report["valid"] = True
    return _finalize(report)


def validate(manifest_path, schema_path):
    """Compatibility helper retained for callers expecting a list of messages."""
    report = validate_report(Path(manifest_path), Path(schema_path))
    return [f'{d["code"]} {d["path"]}: {d["message"]}' for d in report["diagnostics"]]


def main():
    parser = argparse.ArgumentParser(description="Validate an EFS v1 Factory Manifest.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--schema", type=Path, default=Path(__file__).resolve().parents[1] / "schemas/efs/v1/factory-manifest.schema.json")
    parser.add_argument("--json", action="store_true", help="Emit the deterministic machine-readable conformance report.")
    args = parser.parse_args()
    report = validate_report(args.manifest, args.schema)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    elif report["valid"]:
        print("EFS v1 CONFORMANT (parsing, Draft 2020-12 structure, embedded schemas, profile checks)")
        print("Digest/signature verification, external retrieval, policy evaluation, compatibility and runtime admission are separate.")
    else:
        print("EFS v1 NOT CONFORMANT")
        for item in report["diagnostics"]:
            print(f'- {item["code"]} {item["path"]}: {item["message"]}')
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
