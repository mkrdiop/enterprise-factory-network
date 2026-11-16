"""EFS v1 release digest implementation (PSI-40)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from copy import deepcopy
from typing import Any

import rfc8785

from scripts.validate_manifest import (
    InvalidJSONConstant,
    reject_duplicate_members,
    reject_non_json_constant,
)

from .publication_contracts import CanonicalReleasePayload, DigestIdentity

DIGEST_PROFILE = "efs-jcs-sha256-v1"
DIGEST_ALGORITHM = "SHA-256"
DIGEST_DOMAIN = "efs.factory-release.v1"


class ReleaseDigestError(ValueError):
    """The manifest or payload does not conform to the approved digest profile."""


def _strict_json(raw: bytes) -> Any:
    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=reject_duplicate_members,
            parse_constant=reject_non_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReleaseDigestError("release payload is not strict UTF-8 JSON") from exc


def _digest_identity(raw: bytes) -> DigestIdentity:
    value = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode("ascii")
    return DigestIdentity(DIGEST_PROFILE, DIGEST_ALGORITHM, value)


def canonicalize_and_verify(manifest_bytes: bytes) -> CanonicalReleasePayload:
    """Build the exact canonical digest envelope and verify release.digest.

    Schema and EFS semantic validation are intentionally performed by PSI-39
    before this function is called. This function owns strict parsing and the
    normative digest profile only.
    """
    manifest = _strict_json(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ReleaseDigestError("Factory Manifest root must be a JSON object")

    release = manifest.get("release")
    if not isinstance(release, dict):
        raise ReleaseDigestError("release must be a JSON object")
    supplied = release.get("digest")
    if not isinstance(supplied, dict):
        raise ReleaseDigestError("release.digest is required")
    if supplied.get("profile") != DIGEST_PROFILE:
        raise ReleaseDigestError("unsupported release digest profile")
    if supplied.get("algorithm") != DIGEST_ALGORITHM:
        raise ReleaseDigestError("unsupported release digest algorithm")
    supplied_value = supplied.get("value")
    if not isinstance(supplied_value, str) or len(supplied_value) != 43:
        raise ReleaseDigestError("release digest value must be unpadded Base64URL SHA-256")

    projection = deepcopy(manifest)
    projection_release = projection.get("release")
    projection_release.pop("digest", None)
    projection_release.pop("signature", None)
    envelope = {"domain": DIGEST_DOMAIN, "manifest": projection}
    try:
        canonical_bytes = rfc8785.dumps(envelope)
    except Exception as exc:  # library raises typed canonicalization errors by value shape
        raise ReleaseDigestError("manifest contains values outside the JCS/I-JSON profile") from exc

    actual = _digest_identity(canonical_bytes)
    if not hmac.compare_digest(actual.value, supplied_value):
        raise ReleaseDigestError("supplied release digest does not match canonical manifest projection")
    return CanonicalReleasePayload(actual, canonical_bytes)


def verify_canonical_payload(raw: bytes, expected: DigestIdentity) -> dict[str, Any]:
    """Verify stored bytes and return the digest-covered manifest projection."""
    if expected.profile != DIGEST_PROFILE or expected.algorithm != DIGEST_ALGORITHM:
        raise ReleaseDigestError("unsupported expected digest identity")
    actual = _digest_identity(raw)
    if not hmac.compare_digest(actual.value, expected.value):
        raise ReleaseDigestError("stored artifact bytes do not match expected digest")

    envelope = _strict_json(raw)
    if not isinstance(envelope, dict) or set(envelope) != {"domain", "manifest"}:
        raise ReleaseDigestError("stored payload is not the EFS release digest envelope")
    if envelope.get("domain") != DIGEST_DOMAIN:
        raise ReleaseDigestError("stored payload has an invalid digest domain")
    projection = envelope.get("manifest")
    if not isinstance(projection, dict):
        raise ReleaseDigestError("stored manifest projection must be a JSON object")
    release = projection.get("release")
    if not isinstance(release, dict) or "digest" in release or "signature" in release:
        raise ReleaseDigestError("stored projection must exclude release.digest and release.signature")
    try:
        canonical = rfc8785.dumps(envelope)
    except Exception as exc:
        raise ReleaseDigestError("stored payload is outside the JCS/I-JSON profile") from exc
    if canonical != raw:
        raise ReleaseDigestError("stored payload is not in canonical JCS serialization")
    return projection


def reconstruct_manifest(raw: bytes, expected: DigestIdentity) -> dict[str, Any]:
    """Reconstruct the unsigned manifest projection with its verified digest."""
    projection = deepcopy(verify_canonical_payload(raw, expected))
    projection["release"]["digest"] = {
        "profile": expected.profile,
        "algorithm": expected.algorithm,
        "value": expected.value,
    }
    return projection
