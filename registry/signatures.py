"""PSI-51 reference signing and verification for EFS v1 detached envelopes.

Cryptographic verification and authoritative key trust are separate dimensions.
This module performs no network access and contains no trust store or policy engine.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from jsonschema import Draft202012Validator

from registry.digests import (
    DIGEST_ALGORITHM,
    DIGEST_PROFILE,
    ReleaseDigestError,
    canonicalize_and_verify,
)
from scripts.validate_manifest import (
    DuplicateMemberError,
    InvalidJSONConstant,
    canonical_publisher_uri,
    reject_duplicate_members,
    reject_non_json_constant,
)

PROFILE_ID = "efs-ed25519-jcs-v1"
SIGNATURE_PURPOSE = "efs.release.signature.v1"
SIGNATURE_DOMAIN = "efs.release.signature.v1"
SIGNATURE_PREFIX = b"EFS-SIGNATURE-V1\n"
KEY_USAGE = "efs-release-signing"
KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "efs-signature-envelope-v1.schema.json"
)


class SignatureCode(str, Enum):
    VERIFIED = "EFS_SIGNATURE_VERIFIED"
    ENVELOPE_INVALID = "EFS_SIGNATURE_ENVELOPE_INVALID"
    ENVELOPE_ENCODING_INVALID = "EFS_SIGNATURE_ENCODING_INVALID"
    UNSUPPORTED_PROFILE = "EFS_SIGNATURE_UNSUPPORTED_PROFILE"
    DIGEST_MISMATCH = "EFS_SIGNATURE_DIGEST_MISMATCH"
    DIGEST_PROFILE_MISMATCH = "EFS_SIGNATURE_DIGEST_PROFILE_MISMATCH"
    BINDING_MISMATCH = "EFS_SIGNATURE_BINDING_MISMATCH"
    DUPLICATE_SIGNER = "EFS_SIGNATURE_DUPLICATE_SIGNER"
    INVALID = "EFS_SIGNATURE_INVALID"
    KEY_NOT_FOUND = "EFS_SIGNATURE_KEY_NOT_FOUND"
    KEY_BINDING_MISMATCH = "EFS_SIGNATURE_KEY_BINDING_MISMATCH"
    KEY_NOT_TRUSTED = "EFS_SIGNATURE_KEY_NOT_TRUSTED"
    KEY_EXPIRED = "EFS_SIGNATURE_KEY_EXPIRED"
    KEY_REVOKED = "EFS_SIGNATURE_KEY_REVOKED"
    RESOLVER_UNAVAILABLE = "EFS_SIGNATURE_RESOLVER_UNAVAILABLE"


class KeyTrustStatus(str, Enum):
    TRUSTED = "trusted"
    NOT_TRUSTED = "not_trusted"
    EXPIRED = "expired"
    REVOKED = "revoked"
    NOT_FOUND = "not_found"
    BINDING_MISMATCH = "binding_mismatch"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class KeyResolution:
    """Authoritative resolver result; never construct from envelope fields."""

    status: KeyTrustStatus
    publisher_id: str | None = None
    key_id: str | None = None
    algorithm: str | None = None
    public_key: bytes | None = None
    usage: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    evidence_version: str | None = None


@runtime_checkable
class PublisherKeyResolver(Protocol):
    """Injected trust authority. Implementations may wrap PSI-53 later."""

    def resolve(
        self,
        publisher_id: str,
        key_id: str,
        required_algorithm: str,
        required_usage: str,
    ) -> KeyResolution:
        """Resolve exactly (publisher_id, key_id); do not infer or discover keys."""
        ...


@runtime_checkable
class ReleaseSigner(Protocol):
    """Transport-neutral signing adapter."""

    def sign(self, message: bytes) -> bytes:
        ...


@runtime_checkable
class ReleaseSignatureVerifier(Protocol):
    """Transport-neutral verifier contract for Registry, Connect and Runtime."""

    def verify(
        self, manifest_bytes: bytes, envelope_bytes: bytes
    ) -> SignatureVerificationReport:
        ...


class Ed25519Signer:
    """Ed25519 adapter around an already-provisioned private key."""

    def __init__(self, private_key: Ed25519PrivateKey):
        if not isinstance(private_key, Ed25519PrivateKey):
            raise TypeError("private_key must be an Ed25519PrivateKey")
        self._private_key = private_key

    @classmethod
    def from_private_bytes(cls, private_key: bytes) -> Ed25519Signer:
        if not isinstance(private_key, bytes) or len(private_key) != 32:
            raise ValueError("Ed25519 private seed must be exactly 32 bytes")
        return cls(Ed25519PrivateKey.from_private_bytes(private_key))

    def sign(self, message: bytes) -> bytes:
        return self._private_key.sign(message)


@dataclass(frozen=True, slots=True)
class SignerVerification:
    key_id: str
    cryptographic_valid: bool | None
    trust_status: KeyTrustStatus
    code: SignatureCode
    resolver_evidence_version: str | None = None


@dataclass(frozen=True, slots=True)
class SignatureVerificationReport:
    """Evidence only; this report is not an authorization decision."""

    code: SignatureCode
    digest_valid: bool
    signers: tuple[SignerVerification, ...] = ()

    @property
    def cryptographic_valid(self) -> bool:
        return bool(self.signers) and all(
            item.cryptographic_valid is True for item in self.signers
        )

    @property
    def all_keys_trusted(self) -> bool:
        return bool(self.signers) and all(
            item.trust_status is KeyTrustStatus.TRUSTED for item in self.signers
        )

    @property
    def trusted_signature_evidence(self) -> bool:
        """Cryptographic + resolver trust evidence; never an authorization grant."""
        return (
            self.digest_valid
            and self.cryptographic_valid
            and self.all_keys_trusted
            and self.code is SignatureCode.VERIFIED
        )


class SignatureEnvelopeError(ValueError):
    """Raised by producers when input cannot produce a normative envelope."""

    def __init__(self, code: SignatureCode, message: str):
        self.code = code
        super().__init__(message)


def _strict_load(raw: bytes, *, label: str):
    if not isinstance(raw, bytes):
        raise SignatureEnvelopeError(
            SignatureCode.ENVELOPE_ENCODING_INVALID, f"{label} must be UTF-8 bytes"
        )
    try:
        return json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicate_members,
            parse_constant=reject_non_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateMemberError,
            InvalidJSONConstant, ValueError) as exc:
        raise SignatureEnvelopeError(
            SignatureCode.ENVELOPE_ENCODING_INVALID,
            f"{label} is not strict UTF-8 JSON without duplicate members",
        ) from exc


def _release_statement(manifest: dict, digest_value: str) -> dict:
    try:
        publisher_id = manifest["publisher"]["id"]
        factory_id = manifest["factory"]["id"]
        release = manifest["release"]
        release_version = release["version"]
        efs_version = manifest["efsVersion"]
    except (KeyError, TypeError) as exc:
        raise SignatureEnvelopeError(
            SignatureCode.BINDING_MISMATCH, "manifest is missing signed release coordinates"
        ) from exc

    if not all(isinstance(value, str) and value for value in (
        publisher_id, factory_id, release_version, efs_version
    )):
        raise SignatureEnvelopeError(
            SignatureCode.BINDING_MISMATCH, "signed release coordinates must be non-empty strings"
        )
    if canonical_publisher_uri(publisher_id) != publisher_id:
        raise SignatureEnvelopeError(
            SignatureCode.BINDING_MISMATCH,
            "publisher_id is not canonical under efs-uri-c14n-1",
        )
    if "signature" in release:
        raise SignatureEnvelopeError(
            SignatureCode.BINDING_MISMATCH,
            "EFS v1 manifests MUST NOT contain release.signature",
        )
    return {
        "purpose": SIGNATURE_PURPOSE,
        "publisher_id": publisher_id,
        "factory_id": factory_id,
        "release_version": release_version,
        "efs_version": efs_version,
        "digest": {
            "profile_id": DIGEST_PROFILE,
            "algorithm": DIGEST_ALGORITHM,
            "value": digest_value,
        },
    }


def _signed_object(statement: dict, key_id: str, algorithm: str = "Ed25519") -> dict:
    return {
        "domain": SIGNATURE_DOMAIN,
        "signer": {"algorithm": algorithm, "key_id": key_id},
        "statement": statement,
    }


def signing_input(statement: dict, key_id: str, algorithm: str = "Ed25519") -> bytes:
    """Return the exact PSI-50 domain-separated RFC 8785 signing preimage."""
    if not isinstance(key_id, str) or not KEY_ID_PATTERN.fullmatch(key_id):
        raise SignatureEnvelopeError(
            SignatureCode.ENVELOPE_INVALID, "key_id does not match the publisher-scoped identifier profile"
        )
    if algorithm != "Ed25519":
        raise SignatureEnvelopeError(
            SignatureCode.UNSUPPORTED_PROFILE, "only Ed25519 is enabled by efs-ed25519-jcs-v1"
        )
    try:
        canonical = rfc8785.dumps(_signed_object(statement, key_id, algorithm))
    except Exception as exc:
        raise SignatureEnvelopeError(
            SignatureCode.ENVELOPE_INVALID, "signed statement is outside the RFC 8785/I-JSON profile"
        ) from exc
    return SIGNATURE_PREFIX + canonical


def _load_schema(schema_path: str | Path | None):
    path = Path(schema_path) if schema_path is not None else SCHEMA_PATH
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        return schema
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SignatureEnvelopeError(
            SignatureCode.ENVELOPE_INVALID, "normative signature-envelope schema is unavailable or invalid"
        ) from exc


def _validate_envelope(envelope: dict, schema_path: str | Path | None = None):
    if not isinstance(envelope, dict):
        raise SignatureEnvelopeError(
            SignatureCode.ENVELOPE_INVALID, "signature envelope root must be an object"
        )
    schema = _load_schema(schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(envelope),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        first = errors[0]
        if first.path and (
            first.path[0] == "profile_id"
            or "algorithm" in first.path
        ):
            raise SignatureEnvelopeError(
                SignatureCode.UNSUPPORTED_PROFILE, "unsupported signature profile or algorithm"
            )
        if "signature" in first.path and "signatures" in first.path:
            raise SignatureEnvelopeError(
                SignatureCode.ENVELOPE_ENCODING_INVALID, "signature encoding violates the canonical Base64URL profile"
            )
        raise SignatureEnvelopeError(
            SignatureCode.ENVELOPE_INVALID, f"signature envelope schema violation: {first.message}"
        )
    seen = set()
    for signer in envelope["signatures"]:
        identity = (signer["key_id"], signer["algorithm"])
        if identity in seen or signer["key_id"] in {item[0] for item in seen}:
            raise SignatureEnvelopeError(
                SignatureCode.DUPLICATE_SIGNER, "duplicate key_id entries are prohibited in one envelope"
            )
        seen.add(identity)


def create_signature_envelope(
    manifest_bytes: bytes,
    key_id: str,
    signer: ReleaseSigner,
    *,
    schema_path: str | Path | None = None,
) -> dict:
    """Sign one immutable release. The private key never enters the envelope."""
    manifest = _strict_load(manifest_bytes, label="manifest")
    if not isinstance(manifest, dict):
        raise SignatureEnvelopeError(
            SignatureCode.BINDING_MISMATCH, "manifest root must be an object"
        )
    try:
        payload = canonicalize_and_verify(manifest_bytes)
    except ReleaseDigestError as exc:
        message = str(exc).lower()
        code = (
            SignatureCode.DIGEST_PROFILE_MISMATCH
            if "unsupported" in message or "profile" in message or "algorithm" in message
            else SignatureCode.DIGEST_MISMATCH
        )
        raise SignatureEnvelopeError(
            code, "manifest release digest failed verification"
        ) from exc
    statement = _release_statement(manifest, payload.digest.value)
    message = signing_input(statement, key_id)
    signature = signer.sign(message)
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise SignatureEnvelopeError(
            SignatureCode.INVALID, "Ed25519 signer must return exactly 64 signature octets"
        )
    envelope = {
        "envelope_version": "1",
        "profile_id": PROFILE_ID,
        "statement": statement,
        "signatures": [{
            "key_id": key_id,
            "algorithm": "Ed25519",
            "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii"),
        }],
    }
    _validate_envelope(envelope, schema_path)
    return envelope


def add_signature(
    envelope: dict,
    key_id: str,
    signer: ReleaseSigner,
    *,
    schema_path: str | Path | None = None,
) -> dict:
    """Return a new envelope with one additional independent signer entry."""
    _validate_envelope(envelope, schema_path)
    if any(item["key_id"] == key_id for item in envelope["signatures"]):
        raise SignatureEnvelopeError(
            SignatureCode.DUPLICATE_SIGNER, "key_id is already present in this envelope"
        )
    message = signing_input(envelope["statement"], key_id)
    signature = signer.sign(message)
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise SignatureEnvelopeError(
            SignatureCode.INVALID, "Ed25519 signer must return exactly 64 signature octets"
        )
    result = deepcopy(envelope)
    result["signatures"].append({
        "key_id": key_id,
        "algorithm": "Ed25519",
        "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii"),
    })
    result["signatures"].sort(key=lambda item: item["key_id"].encode("ascii"))
    _validate_envelope(result, schema_path)
    return result


def serialize_signature_envelope(envelope: dict, *, schema_path: str | Path | None = None) -> bytes:
    """Validate and serialize an envelope using RFC 8785."""
    _validate_envelope(envelope, schema_path)
    try:
        return rfc8785.dumps(envelope)
    except Exception as exc:
        raise SignatureEnvelopeError(
            SignatureCode.ENVELOPE_INVALID, "signature envelope is outside the RFC 8785/I-JSON profile"
        ) from exc


def _decode_signature(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{86}", value):
        raise SignatureEnvelopeError(
            SignatureCode.ENVELOPE_ENCODING_INVALID, "signature must be canonical unpadded Base64URL"
        )
    try:
        decoded = base64.urlsafe_b64decode(value + "==")
    except (ValueError, binascii.Error) as exc:
        raise SignatureEnvelopeError(
            SignatureCode.ENVELOPE_ENCODING_INVALID, "signature Base64URL decoding failed"
        ) from exc
    if len(decoded) != 64 or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        raise SignatureEnvelopeError(
            SignatureCode.ENVELOPE_ENCODING_INVALID, "signature encoding is non-canonical or wrong length"
        )
    return decoded


def _key_result(resolver: PublisherKeyResolver, publisher_id: str, key_id: str) -> KeyResolution:
    try:
        result = resolver.resolve(publisher_id, key_id, "Ed25519", KEY_USAGE)
    except Exception:  # noqa: BLE001 - any resolver failure must fail closed
        return KeyResolution(KeyTrustStatus.UNAVAILABLE)
    if not isinstance(result, KeyResolution) or not isinstance(result.status, KeyTrustStatus):
        return KeyResolution(KeyTrustStatus.UNAVAILABLE)
    return result


def verify_release_signature(
    manifest_bytes: bytes,
    envelope_bytes: bytes,
    resolver: PublisherKeyResolver,
    *,
    schema_path: str | Path | None = None,
) -> SignatureVerificationReport:
    """Verify digest, exact statement binding and each signer independently.

    This API deliberately returns cryptographic and trust evidence separately.
    It never makes a PSI-52/53 authorization decision.
    """
    try:
        manifest = _strict_load(manifest_bytes, label="manifest")
        if not isinstance(manifest, dict):
            raise SignatureEnvelopeError(SignatureCode.BINDING_MISMATCH, "manifest root must be an object")
    except SignatureEnvelopeError as exc:
        return SignatureVerificationReport(exc.code, False)

    try:
        payload = canonicalize_and_verify(manifest_bytes)
    except ReleaseDigestError as exc:
        message = str(exc).lower()
        code = (
            SignatureCode.DIGEST_PROFILE_MISMATCH
            if "unsupported" in message or "profile" in message or "algorithm" in message
            else SignatureCode.DIGEST_MISMATCH
        )
        return SignatureVerificationReport(code, False)

    try:
        expected_statement = _release_statement(manifest, payload.digest.value)
        envelope = _strict_load(envelope_bytes, label="signature envelope")
        _validate_envelope(envelope, schema_path)
    except SignatureEnvelopeError as exc:
        return SignatureVerificationReport(exc.code, True)

    if envelope["profile_id"] != PROFILE_ID:
        return SignatureVerificationReport(SignatureCode.UNSUPPORTED_PROFILE, True)
    if envelope["statement"] != expected_statement:
        return SignatureVerificationReport(SignatureCode.BINDING_MISMATCH, True)

    results: list[SignerVerification] = []
    publisher_id = expected_statement["publisher_id"]
    for entry in envelope["signatures"]:
        key_id = entry["key_id"]
        try:
            signature = _decode_signature(entry["signature"])
        except SignatureEnvelopeError as exc:
            results.append(SignerVerification(
                key_id, False, KeyTrustStatus.UNAVAILABLE, exc.code
            ))
            continue

        resolution = _key_result(resolver, publisher_id, key_id)
        trust = resolution.status
        if trust is KeyTrustStatus.NOT_FOUND:
            results.append(SignerVerification(key_id, None, trust, SignatureCode.KEY_NOT_FOUND))
            continue
        if trust is KeyTrustStatus.UNAVAILABLE:
            results.append(SignerVerification(key_id, None, trust, SignatureCode.RESOLVER_UNAVAILABLE))
            continue
        if trust is KeyTrustStatus.BINDING_MISMATCH:
            results.append(SignerVerification(key_id, None, trust, SignatureCode.KEY_BINDING_MISMATCH))
            continue
        if trust in {
            KeyTrustStatus.NOT_TRUSTED,
            KeyTrustStatus.EXPIRED,
            KeyTrustStatus.REVOKED,
        } and resolution.public_key is None:
            trust_code = {
                KeyTrustStatus.NOT_TRUSTED: SignatureCode.KEY_NOT_TRUSTED,
                KeyTrustStatus.EXPIRED: SignatureCode.KEY_EXPIRED,
                KeyTrustStatus.REVOKED: SignatureCode.KEY_REVOKED,
            }[trust]
            results.append(SignerVerification(
                key_id, None, trust, trust_code, resolution.evidence_version
            ))
            continue

        if (
            resolution.publisher_id != publisher_id
            or resolution.key_id != key_id
            or resolution.algorithm != "Ed25519"
            or resolution.usage != KEY_USAGE
            or not isinstance(resolution.public_key, bytes)
            or len(resolution.public_key) != 32
            or not isinstance(resolution.valid_from, datetime)
            or resolution.valid_from.tzinfo is None
            or (
                resolution.valid_until is not None
                and (
                    not isinstance(resolution.valid_until, datetime)
                    or resolution.valid_until.tzinfo is None
                )
            )
            or not isinstance(resolution.evidence_version, str)
            or not resolution.evidence_version
        ):
            results.append(SignerVerification(
                key_id, None, KeyTrustStatus.BINDING_MISMATCH,
                SignatureCode.KEY_BINDING_MISMATCH, resolution.evidence_version
            ))
            continue

        try:
            public_key = Ed25519PublicKey.from_public_bytes(resolution.public_key)
            public_key.verify(signature, signing_input(expected_statement, key_id, entry["algorithm"]))
            crypto_valid = True
        except InvalidSignature:
            crypto_valid = False
        except (ValueError, TypeError):
            results.append(SignerVerification(
                key_id, None, KeyTrustStatus.BINDING_MISMATCH,
                SignatureCode.KEY_BINDING_MISMATCH, resolution.evidence_version
            ))
            continue

        if not crypto_valid:
            code = SignatureCode.INVALID
        elif trust is KeyTrustStatus.REVOKED:
            code = SignatureCode.KEY_REVOKED
        elif trust is KeyTrustStatus.EXPIRED:
            code = SignatureCode.KEY_EXPIRED
        elif trust is KeyTrustStatus.NOT_TRUSTED:
            code = SignatureCode.KEY_NOT_TRUSTED
        elif trust is KeyTrustStatus.TRUSTED:
            code = SignatureCode.VERIFIED
        else:
            code = SignatureCode.KEY_NOT_TRUSTED
        results.append(SignerVerification(
            key_id, crypto_valid, trust, code, resolution.evidence_version
        ))

    if results and all(item.code is SignatureCode.VERIFIED for item in results):
        overall = SignatureCode.VERIFIED
    else:
        # Preserve per-signer typed outcomes; overall is the first failure in
        # envelope order, not a quorum or "any signer" authorization rule.
        overall = next(
            (item.code for item in results if item.code is not SignatureCode.VERIFIED),
            SignatureCode.ENVELOPE_INVALID,
        )
    return SignatureVerificationReport(overall, True, tuple(results))


class EFSReleaseSignatureVerifier:
    """Default transport-neutral adapter around the PSI-51 reference verifier."""

    def __init__(
        self,
        resolver: PublisherKeyResolver,
        *,
        schema_path: str | Path | None = None,
    ):
        self._resolver = resolver
        self._schema_path = schema_path

    def verify(
        self, manifest_bytes: bytes, envelope_bytes: bytes
    ) -> SignatureVerificationReport:
        return verify_release_signature(
            manifest_bytes,
            envelope_bytes,
            self._resolver,
            schema_path=self._schema_path,
        )
