"""PSI-51 signing/verifier security and interoperability tests."""
import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from registry.digests import canonicalize_and_verify
from registry.signatures import (
    Ed25519Signer,
    EFSReleaseSignatureVerifier,
    KeyResolution,
    KeyTrustStatus,
    SignatureCode,
    SignatureEnvelopeError,
    add_signature,
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
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_until=None,
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
    assert verifier.verify(raw, encoded).code is SignatureCode.EVALUATED


def test_known_seed_ed25519_signing_and_verification_round_trip():
    raw, _manifest, _envelope, encoded = _signed()
    resolver = FixtureResolver()
    result = verify_release_signature(raw, encoded, resolver)
    assert result.code is SignatureCode.EVALUATED
    assert result.digest_valid is True
    assert result.signers[0].cryptographic_valid is True
    assert result.signers[0].trust_status is KeyTrustStatus.TRUSTED
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
    assert result.signers[0].code is SignatureCode.INVALID
    assert result.signers[0].cryptographic_valid is False


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
    assert result.signers[0].code is expected
    assert result.signers[0].cryptographic_valid is True
    assert result.signers[0].trust_status is trust

def test_unknown_key_is_typed_and_fails_closed():
    raw, _manifest, _envelope, encoded = _signed()
    result = verify_release_signature(
        raw, encoded, FixtureResolver(status=KeyTrustStatus.NOT_FOUND, public_key=None)
    )
    assert result.signers[0].code is SignatureCode.KEY_NOT_FOUND
    assert result.signers[0].cryptographic_valid is None

def test_resolver_exception_is_unavailable_and_fails_closed():
    raw, _manifest, _envelope, encoded = _signed()

    class BrokenResolver:
        def resolve(self, *_args):
            raise TimeoutError("trust provider offline")

    result = verify_release_signature(raw, encoded, BrokenResolver())
    assert result.signers[0].code is SignatureCode.RESOLVER_UNAVAILABLE
    assert result.signers[0].trust_status is KeyTrustStatus.UNAVAILABLE

def test_cross_publisher_key_substitution_is_binding_failure():
    raw, _manifest, _envelope, encoded = _signed()
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
    assert result.signers[0].code is SignatureCode.KEY_BINDING_MISMATCH
    assert result.signers[0].trust_status is KeyTrustStatus.BINDING_MISMATCH
    assert result.signers[0].cryptographic_valid is None


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
    assert result.code is SignatureCode.ENVELOPE_ENCODING_INVALID


def test_unknown_signature_profile_fails_without_resolver_lookup():
    raw, _manifest, envelope, _encoded = _signed()
    envelope["profile_id"] = "efs-rsa-jcs-v1"
    resolver = FixtureResolver()
    result = verify_release_signature(raw, json.dumps(envelope).encode(), resolver)
    assert result.code is SignatureCode.UNSUPPORTED_PROFILE
    assert resolver.calls == []


def test_unsupported_signing_algorithm_is_not_downgraded():
    _raw, _manifest = _manifest_bytes()
    statement = {
        "purpose": "efs.release.signature.v1",
        "publisher_id": "urn:example:publishers:acme",
        "factory_id": "customer-support",
        "release_version": "1.2.0",
        "efs_version": "1.0.0",
        "digest": {
            "profile_id": "efs-jcs-sha256-v1",
            "algorithm": "SHA-256",
            "value": DIGEST_VECTOR["expectedDigest"],
        },
    }
    with pytest.raises(SignatureEnvelopeError) as error:
        signing_input(statement, "test-release-key", "RSA-PSS")
    assert error.value.code is SignatureCode.UNSUPPORTED_PROFILE


def test_resolver_unknown_status_fails_closed():
    raw, _manifest, _envelope, encoded = _signed()

    class InvalidResolver:
        def resolve(self, *_args):
            return {"status": "trusted", "public_key": PUBLIC}

    result = verify_release_signature(raw, encoded, InvalidResolver())
    assert result.code is SignatureCode.EVALUATED
    assert result.signers[0].code is SignatureCode.RESOLVER_UNAVAILABLE

def test_multiple_signatures_are_independently_signed_and_sorted():
    raw, _manifest = _manifest_bytes()
    first = create_signature_envelope(raw, "z-key", SIGNER)
    second_signer = Ed25519Signer.from_private_bytes(bytes(reversed(range(32))))
    combined = add_signature(first, "a-key", second_signer)
    assert [item["key_id"] for item in combined["signatures"]] == ["a-key", "z-key"]

    class MultiKeyResolver:
        def resolve(self, publisher_id, key_id, algorithm, usage):
            key = (
                PRIVATE.public_key().public_bytes_raw()
                if key_id == "z-key"
                else Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32)))).public_key().public_bytes_raw()
            )
            return KeyResolution(
                status=KeyTrustStatus.TRUSTED,
                publisher_id=publisher_id,
                key_id=key_id,
                algorithm=algorithm,
                public_key=key,
                usage=usage,
                valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                evidence_version="test-multi-key-v1",
            )

    result = verify_release_signature(raw, serialize_signature_envelope(combined), MultiKeyResolver())
    assert result.code is SignatureCode.EVALUATED
    assert len(result.signers) == 2
    assert result.signers[0].cryptographic_valid is True


def test_resolver_missing_validity_or_evidence_fails_closed():
    raw, _manifest, _envelope, encoded = _signed()

    class IncompleteResolver:
        def resolve(self, publisher_id, key_id, algorithm, usage):
            return KeyResolution(
                status=KeyTrustStatus.TRUSTED,
                publisher_id=publisher_id,
                key_id=key_id,
                algorithm=algorithm,
                public_key=PUBLIC,
                usage=usage,
            )

    result = verify_release_signature(raw, encoded, IncompleteResolver())
    assert result.signers[0].code is SignatureCode.KEY_BINDING_MISMATCH
    assert result.signers[0].cryptographic_valid is None

def test_signature_array_order_does_not_change_verification_result():
    raw, _manifest = _manifest_bytes()
    first = create_signature_envelope(raw, "z-key", SIGNER)
    second_signer = Ed25519Signer.from_private_bytes(bytes(reversed(range(32))))
    combined = add_signature(first, "a-key", second_signer)
    signature = bytearray(base64.urlsafe_b64decode(combined["signatures"][0]["signature"] + "=="))
    signature[0] ^= 1
    combined["signatures"][0]["signature"] = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

    class MultiKeyResolver:
        def resolve(self, publisher_id, key_id, algorithm, usage):
            private = PRIVATE if key_id == "z-key" else Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32))))
            return KeyResolution(
                status=KeyTrustStatus.TRUSTED,
                publisher_id=publisher_id,
                key_id=key_id,
                algorithm=algorithm,
                public_key=private.public_key().public_bytes_raw(),
                usage=usage,
                valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                evidence_version="test-multi-key-v1",
            )

    reordered = json.loads(json.dumps(combined))
    reordered["signatures"].reverse()
    first_report = verify_release_signature(raw, serialize_signature_envelope(combined), MultiKeyResolver())
    second_report = verify_release_signature(raw, serialize_signature_envelope(reordered), MultiKeyResolver())
    assert first_report == second_report
    assert first_report.code is SignatureCode.EVALUATED
    assert first_report.signers[0].code is SignatureCode.INVALID


@pytest.mark.parametrize(
    ("coordinate", "value"),
    [
        ("publisher_id", "urn:example:publishers:other"),
        ("factory_id", "other-factory"),
        ("release_version", "9.9.9"),
        ("efs_version", "2.0.0"),
    ],
)
def test_each_release_coordinate_is_cryptographically_bound(coordinate, value):
    raw, _manifest, envelope, _encoded = _signed()
    envelope["statement"][coordinate] = value
    result = verify_release_signature(raw, json.dumps(envelope).encode(), FixtureResolver())
    assert result.code is SignatureCode.BINDING_MISMATCH
    assert result.signers == ()


def test_digest_tuple_is_bound_to_the_immutable_release():
    raw, _manifest, envelope, _encoded = _signed()
    envelope["statement"]["digest"]["value"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    result = verify_release_signature(raw, json.dumps(envelope).encode(), FixtureResolver())
    assert result.code is SignatureCode.BINDING_MISMATCH


def test_envelope_digest_profile_mismatch_has_its_own_typed_outcome():
    raw, _manifest, envelope, _encoded = _signed()
    envelope["statement"]["digest"]["profile_id"] = "efs-jcs-sha512-v1"
    result = verify_release_signature(raw, json.dumps(envelope).encode(), FixtureResolver())
    assert result.code is SignatureCode.DIGEST_PROFILE_MISMATCH


def test_manifest_digest_profile_mismatch_fails_before_key_resolution():
    _raw, manifest = _manifest_bytes()
    manifest["release"]["digest"]["profile"] = "efs-jcs-sha512-v1"
    changed = json.dumps(manifest).encode()
    resolver = FixtureResolver()
    result = verify_release_signature(changed, b"{}", resolver)
    assert result.code is SignatureCode.DIGEST_PROFILE_MISMATCH
    assert resolver.calls == []


def test_wrong_publisher_scoped_public_key_is_an_invalid_signature():
    raw, _manifest, _envelope, encoded = _signed()
    wrong_key = Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32)))).public_key().public_bytes_raw()
    result = verify_release_signature(raw, encoded, FixtureResolver(public_key=wrong_key))
    assert result.signers[0].code is SignatureCode.INVALID
    assert result.signers[0].cryptographic_valid is False


def test_trust_denial_without_public_key_still_requires_exact_resolver_binding():
    raw, _manifest, _envelope, encoded = _signed()

    class RevokedResolver:
        def __init__(self, publisher_id):
            self.publisher_id = publisher_id

        def resolve(self, _publisher_id, key_id, algorithm, usage):
            return KeyResolution(
                status=KeyTrustStatus.REVOKED,
                publisher_id=self.publisher_id,
                key_id=key_id,
                algorithm=algorithm,
                public_key=None,
                usage=usage,
                valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                evidence_version="revocation-evidence-v1",
            )

    revoked = verify_release_signature(
        raw, encoded, RevokedResolver("urn:example:publishers:acme")
    )
    assert revoked.signers[0].code is SignatureCode.KEY_REVOKED
    assert revoked.signers[0].cryptographic_valid is None

    mismatched = verify_release_signature(
        raw, encoded, RevokedResolver("urn:example:publishers:attacker")
    )
    assert mismatched.signers[0].code is SignatureCode.KEY_BINDING_MISMATCH


@pytest.mark.parametrize("interval", ["not_yet_valid", "expired_but_reported_trusted"])
def test_trusted_resolver_status_must_match_current_validity_interval(interval):
    raw, _manifest, _envelope, encoded = _signed()

    class ContradictoryResolver:
        def resolve(self, publisher_id, key_id, algorithm, usage):
            now = datetime.now(UTC)
            valid_from = now.replace(year=now.year + 1) if interval == "not_yet_valid" else datetime(2025, 1, 1, tzinfo=UTC)
            valid_until = None if interval == "not_yet_valid" else now - timedelta(days=1)
            return KeyResolution(
                status=KeyTrustStatus.TRUSTED,
                publisher_id=publisher_id,
                key_id=key_id,
                algorithm=algorithm,
                public_key=PUBLIC,
                usage=usage,
                valid_from=valid_from,
                valid_until=valid_until,
                evidence_version="contradictory-trust-evidence-v1",
            )

    report = verify_release_signature(raw, encoded, ContradictoryResolver())
    assert report.code is SignatureCode.EVALUATED
    assert report.signers[0].code is SignatureCode.KEY_BINDING_MISMATCH
    assert report.signers[0].trust_status is KeyTrustStatus.BINDING_MISMATCH
    assert report.signers[0].cryptographic_valid is None


def _multi_signature_fixture():
    raw, _manifest = _manifest_bytes()
    first = create_signature_envelope(raw, "z-valid", SIGNER)
    second_signer = Ed25519Signer.from_private_bytes(bytes(reversed(range(32))))
    envelope = add_signature(first, "a-secondary", second_signer)
    return raw, envelope, second_signer


def test_valid_and_invalid_signatures_are_reported_independently():
    raw, envelope, _second_signer = _multi_signature_fixture()
    signature = bytearray(base64.urlsafe_b64decode(envelope["signatures"][0]["signature"] + "=="))
    signature[0] ^= 1
    envelope["signatures"][0]["signature"] = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

    class Resolver:
        def resolve(self, publisher_id, key_id, algorithm, usage):
            key = (
                PRIVATE.public_key().public_bytes_raw()
                if key_id == "z-valid"
                else Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32)))).public_key().public_bytes_raw()
            )
            return KeyResolution(KeyTrustStatus.TRUSTED, publisher_id, key_id, algorithm, key, usage,
                                 datetime(2026, 1, 1, tzinfo=UTC), None, "multi-v1")

    report = verify_release_signature(raw, serialize_signature_envelope(envelope), Resolver())
    by_key = {item.key_id: item for item in report.signers}
    assert report.code is SignatureCode.EVALUATED
    assert by_key["a-secondary"].code is SignatureCode.INVALID
    assert by_key["a-secondary"].cryptographic_valid is False
    assert by_key["z-valid"].code is SignatureCode.VERIFIED
    assert by_key["z-valid"].cryptographic_valid is True


def test_valid_and_unknown_signatures_are_reported_independently():
    raw, envelope, _second_signer = _multi_signature_fixture()

    class Resolver:
        def resolve(self, publisher_id, key_id, algorithm, usage):
            if key_id == "a-secondary":
                return KeyResolution(KeyTrustStatus.NOT_FOUND)
            return KeyResolution(KeyTrustStatus.TRUSTED, publisher_id, key_id, algorithm,
                                 PUBLIC, usage, datetime(2026, 1, 1, tzinfo=UTC), None, "known-v1")

    report = verify_release_signature(raw, serialize_signature_envelope(envelope), Resolver())
    by_key = {item.key_id: item for item in report.signers}
    assert report.code is SignatureCode.EVALUATED
    assert by_key["a-secondary"].code is SignatureCode.KEY_NOT_FOUND
    assert by_key["a-secondary"].cryptographic_valid is None
    assert by_key["z-valid"].code is SignatureCode.VERIFIED
    assert by_key["z-valid"].cryptographic_valid is True


def test_valid_and_revoked_signatures_are_reported_independently():
    raw, envelope, _second_signer = _multi_signature_fixture()

    class Resolver:
        def resolve(self, publisher_id, key_id, algorithm, usage):
            if key_id == "a-secondary":
                return KeyResolution(KeyTrustStatus.REVOKED, publisher_id, key_id, algorithm,
                                     None, usage, datetime(2026, 1, 1, tzinfo=UTC), None, "revoked-v1")
            return KeyResolution(KeyTrustStatus.TRUSTED, publisher_id, key_id, algorithm,
                                 PUBLIC, usage, datetime(2026, 1, 1, tzinfo=UTC), None, "known-v1")

    report = verify_release_signature(raw, serialize_signature_envelope(envelope), Resolver())
    by_key = {item.key_id: item for item in report.signers}
    assert report.code is SignatureCode.EVALUATED
    assert by_key["a-secondary"].code is SignatureCode.KEY_REVOKED
    assert by_key["a-secondary"].cryptographic_valid is None
    assert by_key["z-valid"].code is SignatureCode.VERIFIED
    assert by_key["z-valid"].cryptographic_valid is True
