"""PSI-51 signing/verifier security and interoperability tests."""
import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from registry.digests import canonicalize_and_verify
from registry.signatures import (
    EFSReleaseSignatureVerifier,
    Ed25519Signer,
    KeyResolution,
    KeyTrustStatus,
    SignatureCode,
    SignatureEnvelopeError,
    create_signature_envelope,
    serialize_signature_envelope,
    signing_input,
    verify_release_signature,
)

ROOT = Path(__file__).resolve().parents[1]
DIGEST_VECTOR = json.loads(
    (ROOT / "conformance/efs/v1/release-digest-vectors.json").read_text(encoding="utf-8")
)["vectors"][0]
MANIFEST_FIXTURE = ROOT / DIGEST_VECTOR["fixture"]
SEED = bytes(range(32))
PRIVATE = Ed25519PrivateKey.from_private_bytes(SEED)
PUBLIC = PRIVATE.public_key().public_bytes_raw()
SIGNER = Ed25519Signer(PRIVATE)


class FixtureResolver:
    def __init__(self, status=KeyTrustStatus.TRUSTED, public_key=PUBLIC):
        self.status = status
        self.public_key = public_key
        self.calls = []

    def resolve(self, publisher_id, key_id, required_algorithm, required_usage):
        self.calls.append((publisher_id, key_id, required_algorithm, required_usage))
        return KeyResolution(
            status=self.status,
            publisher_id=publisher_id,
            key_id=key_id,
            algorithm=required_algorithm,
            public_key=self.public_key,
            usage=required_usage,
            evidence_version="test-evidence-v1",
        )


def _manifest_bytes():
    manifest = json.loads(MANIFEST_FIXTURE.read_text(encoding="utf-8"))
    manifest["release"]["digest"]["value"] = DIGEST_VECTOR["expectedDigest"]
    raw = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    canonicalize_and_verify(raw)
    return raw, manifest


def _signed():
    raw, manifest = _manifest_bytes()
    envelope = create_signature_envelope(raw, "test-release-key", SIGNER)
    return raw, manifest, envelope, serialize_signature_envelope(envelope)


def test_transport_neutral_verifier_adapter_uses_injected_resolver():
    raw, _manifest, _envelope, encoded = _signed()
    verifier = EFSReleaseSignatureVerifier(FixtureResolver())
    assert verifier.verify(raw, encoded).code is SignatureCode.VERIFIED


def test_known_seed_ed25519_signing_and_verification_round_trip():
    raw, _manifest, _envelope, encoded = _signed()
    resolver = FixtureResolver()
    result = verify_release_signature(raw, encoded, resolver)
    assert result.code is SignatureCode.VERIFIED
    assert result.digest_valid is True
    assert result.cryptographic_valid is True
    assert result.all_keys_trusted is True
    assert result.trusted_signature_evidence is True
    assert resolver.calls == [(
        "urn:example:publishers:acme",
        "test-release-key",
        "Ed25519",
        "efs-release-signing",
    )]


def test_psi50_known_answer_vector_matches_exact_preimage_and_ed25519():
    vectors = json.loads(
        (ROOT / "tests/conformance/signatures-v1.json").read_text(encoding="utf-8")
    )
    vector = next(item for item in vectors["vectors"] if item["id"] == "sig-kat-001")
    statement = vector["input"]["statement"]
    signer = vector["input"]["signer"]
    preimage = signing_input(statement, signer["key_id"], signer["algorithm"])
    assert base64.urlsafe_b64encode(preimage).rstrip(b"=").decode() == vector["expected"]["preimage_base64url"]
    public_key = base64.urlsafe_b64decode(vector["expected"]["public_key_base64url"] + "==")
    signature = base64.urlsafe_b64decode(vector["expected"]["signature_base64url"] + "==")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    Ed25519PublicKey.from_public_bytes(public_key).verify(signature, preimage)


def test_exact_signing_prefix_and_domain_are_stable():
    _raw, _manifest = _manifest_bytes()
    envelope = create_signature_envelope(_raw, "test-release-key", SIGNER)
    message = signing_input(envelope["statement"], "test-release-key")
    assert message.startswith(b"EFS-SIGNATURE-V1\n")
    canonical = message.removeprefix(b"EFS-SIGNATURE-V1\n")
    parsed = json.loads(canonical)
    assert parsed["domain"] == "efs.release.signature.v1"
    assert parsed["signer"] == {"algorithm": "Ed25519", "key_id": "test-release-key"}
    assert parsed["statement"] == envelope["statement"]


def test_manifest_digest_tampering_fails_before_resolver():
    _raw, manifest = _manifest_bytes()
    manifest["factory"]["id"] = "substituted-factory"
    changed = json.dumps(manifest).encode()
    resolver = FixtureResolver()
    result = verify_release_signature(changed, b"{}", resolver)
    assert result.code is SignatureCode.DIGEST_MISMATCH
    assert result.digest_valid is False
    assert resolver.calls == []


def test_envelope_statement_substitution_is_binding_failure():
    raw, _manifest, envelope, _encoded = _signed()
    envelope["statement"]["factory_id"] = "other-factory"
    result = verify_release_signature(
        raw, serialize_signature_envelope(envelope), FixtureResolver()
    )
    assert result.code is SignatureCode.BINDING_MISMATCH
    assert result.signers == ()


def test_signature_byte_tampering_is_invalid():
    raw, _manifest, envelope, _encoded = _signed()
    signature = bytearray(base64.urlsafe_b64decode(envelope["signatures"][0]["signature"] + "=="))
    signature[0] ^= 1
    envelope["signatures"][0]["signature"] = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    result = verify_release_signature(
        raw, serialize_signature_envelope(envelope), FixtureResolver()
    )
    assert result.code is SignatureCode.INVALID
    assert result.cryptographic_valid is False


@pytest.mark.parametrize(
    ("trust", "expected"),
    [
        (KeyTrustStatus.NOT_TRUSTED, SignatureCode.KEY_NOT_TRUSTED),
        (KeyTrustStatus.EXPIRED, SignatureCode.KEY_EXPIRED),
        (KeyTrustStatus.REVOKED, SignatureCode.KEY_REVOKED),
    ],
)
def test_cryptographic_validity_is_separate_from_key_trust(trust, expected):
    raw, _manifest, _envelope, encoded = _signed()
    result = verify_release_signature(raw, encoded, FixtureResolver(status=trust))
    assert result.code is expected
    assert result.cryptographic_valid is True
    assert result.all_keys_trusted is False
    assert result.trusted_signature_evidence is False


def test_unknown_key_is_typed_and_fails_closed():
    raw, _manifest, _envelope, encoded = _signed()
    result = verify_release_signature(
        raw, encoded, FixtureResolver(status=KeyTrustStatus.NOT_FOUND, public_key=None)
    )
    assert result.code is SignatureCode.KEY_NOT_FOUND
    assert result.cryptographic_valid is False
    assert result.admission_eligible is False


def test_resolver_exception_is_unavailable_and_fails_closed():
    raw, _manifest, _envelope, encoded = _signed()

    class BrokenResolver:
        def resolve(self, *_args):
            raise TimeoutError("trust provider offline")

    result = verify_release_signature(raw, encoded, BrokenResolver())
    assert result.code is SignatureCode.RESOLVER_UNAVAILABLE
    assert result.admission_eligible is False


def test_cross_publisher_key_substitution_is_binding_failure():
    raw, _manifest, _envelope, encoded = _signed()
    resolver = FixtureResolver()

    class WrongPublisherResolver:
        def resolve(self, publisher_id, key_id, algorithm, usage):
            return KeyResolution(
                KeyTrustStatus.TRUSTED,
                publisher_id="urn:example:publishers:attacker",
                key_id=key_id,
                algorithm=algorithm,
                public_key=PUBLIC,
                usage=usage,
            )

    result = verify_release_signature(raw, encoded, WrongPublisherResolver())
    assert result.code is SignatureCode.KEY_BINDING_MISMATCH
    assert result.cryptographic_valid is False


def test_duplicate_signer_entries_are_rejected():
    _raw, _manifest, envelope, _encoded = _signed()
    envelope["signatures"].append(dict(envelope["signatures"][0]))
    with pytest.raises(SignatureEnvelopeError) as error:
        serialize_signature_envelope(envelope)
    assert error.value.code is SignatureCode.DUPLICATE_SIGNER


def test_duplicate_json_members_are_rejected():
    raw, _manifest, _envelope, _encoded = _signed()
    resolver = FixtureResolver()
    result = verify_release_signature(
        raw, b'{"envelope_version":"1","envelope_version":"1"}', resolver
    )
    assert result.code is SignatureCode.ENVELOPE_ENCODING_INVALID
    assert resolver.calls == []


def test_manifest_embedded_signature_is_rejected():
    _raw, manifest = _manifest_bytes()
    manifest["release"]["signature"] = {"signature": "attacker-controlled"}
    with pytest.raises(SignatureEnvelopeError) as error:
        create_signature_envelope(json.dumps(manifest).encode(), "test-release-key", SIGNER)
    assert error.value.code in {
        SignatureCode.BINDING_MISMATCH,
        SignatureCode.DIGEST_MISMATCH,
    }


def test_unknown_envelope_property_is_rejected():
    _raw, _manifest, envelope, _encoded = _signed()
    envelope["public_key"] = base64.urlsafe_b64encode(PUBLIC).rstrip(b"=").decode()
    with pytest.raises(SignatureEnvelopeError) as error:
        serialize_signature_envelope(envelope)
    assert error.value.code is SignatureCode.ENVELOPE_INVALID


def test_malformed_signature_encoding_is_rejected():
    raw, _manifest, envelope, _encoded = _signed()
    envelope["signatures"][0]["signature"] = "A" * 85 + "="
    # Schema rejects padded and non-canonical Base64URL before key lookup.
    result = verify_release_signature(raw, json.dumps(envelope).encode(), FixtureResolver())
    assert result.code is SignatureCode.ENVELOPE_INVALID
