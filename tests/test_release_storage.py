"""PSI-40 digest and immutable storage contract tests."""
import base64
import json
from pathlib import Path

import pytest

from registry.artifact_store import ArtifactIntegrityError, LocalFilesystemArtifactStore
from registry.digests import (
    DIGEST_ALGORITHM,
    DIGEST_PROFILE,
    ReleaseDigestError,
    canonicalize_and_verify,
    reconstruct_manifest,
    verify_canonical_payload,
)
from registry.publication_contracts import DigestIdentity

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/valid/manifest-minimal.json"
VECTORS = json.loads((ROOT / "conformance/efs/v1/release-digest-vectors.json").read_text(encoding="utf-8"))
MINIMAL_VECTOR = VECTORS["vectors"][0]
EXPECTED_MINIMAL_DIGEST = MINIMAL_VECTOR["expectedDigest"]


def _fixture_object():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_minimal_manifest_matches_language_neutral_digest_vector():
    manifest = _fixture_object()
    manifest["release"]["digest"]["value"] = EXPECTED_MINIMAL_DIGEST
    payload = canonicalize_and_verify(json.dumps(manifest).encode())
    expected_bytes = base64.b64decode(MINIMAL_VECTOR["canonicalEnvelopeBase64"])
    assert payload.digest.profile == DIGEST_PROFILE
    assert payload.digest.algorithm == DIGEST_ALGORITHM
    assert payload.digest.value == EXPECTED_MINIMAL_DIGEST
    assert payload.byte_length == MINIMAL_VECTOR["canonicalEnvelopeByteLength"]
    assert payload.canonical_bytes == expected_bytes


def test_whitespace_and_key_order_do_not_change_digest():
    manifest = _fixture_object()
    manifest["release"]["digest"]["value"] = EXPECTED_MINIMAL_DIGEST
    compact = json.dumps(manifest, separators=(",", ":")).encode()
    reordered = json.dumps(manifest, indent=4, sort_keys=True).encode()
    assert canonicalize_and_verify(compact).canonical_bytes == canonicalize_and_verify(reordered).canonical_bytes


def test_signature_is_excluded_and_never_synthesized_on_retrieval():
    manifest = _fixture_object()
    manifest["release"]["digest"]["value"] = EXPECTED_MINIMAL_DIGEST
    manifest["release"]["signature"] = {
        "algorithm": "example-signature",
        "keyId": "urn:example:key:one",
        "value": "signature-one",
    }
    first = canonicalize_and_verify(json.dumps(manifest).encode())
    manifest["release"]["signature"]["value"] = "signature-two"
    second = canonicalize_and_verify(json.dumps(manifest).encode())
    assert first.canonical_bytes == second.canonical_bytes
    reconstructed = reconstruct_manifest(first.canonical_bytes, first.digest)
    assert reconstructed["release"]["digest"]["value"] == EXPECTED_MINIMAL_DIGEST
    assert "signature" not in reconstructed["release"]


@pytest.mark.parametrize(
    "raw",
    [
        b'{"release":{"digest":{"profile":"x","profile":"y"}}}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":"\xff"}',
    ],
)
def test_strict_parser_rejects_duplicate_non_json_and_invalid_utf8(raw):
    with pytest.raises(ReleaseDigestError):
        canonicalize_and_verify(raw)


def test_digest_mismatch_is_rejected():
    manifest = _fixture_object()
    manifest["release"]["digest"]["value"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    with pytest.raises(ReleaseDigestError, match="does not match"):
        canonicalize_and_verify(json.dumps(manifest).encode())


def test_non_jcs_number_domain_is_rejected():
    manifest = _fixture_object()
    manifest["extensions"] = {"https://example.org/ext": {"unsafeInteger": 9007199254740992}}
    with pytest.raises(ReleaseDigestError, match="JCS/I-JSON"):
        canonicalize_and_verify(json.dumps(manifest).encode())


def test_stored_payload_must_be_canonical_and_digest_valid():
    manifest = _fixture_object()
    manifest["release"]["digest"]["value"] = EXPECTED_MINIMAL_DIGEST
    payload = canonicalize_and_verify(json.dumps(manifest).encode())
    projection = verify_canonical_payload(payload.canonical_bytes, payload.digest)
    assert projection["factory"]["id"] == "customer-support"
    tampered = payload.canonical_bytes + b" "
    with pytest.raises(ReleaseDigestError):
        verify_canonical_payload(tampered, payload.digest)


def test_filesystem_store_is_idempotent_and_digest_addressed(tmp_path):
    manifest = _fixture_object()
    manifest["release"]["digest"]["value"] = EXPECTED_MINIMAL_DIGEST
    payload = canonicalize_and_verify(json.dumps(manifest).encode())
    store = LocalFilesystemArtifactStore(tmp_path)
    first = store.put_if_absent(payload)
    second = store.put_if_absent(payload)
    assert first.digest == second.digest
    assert first.object_key == second.object_key
    assert store.read(payload.digest) == payload.canonical_bytes
    assert first.provider == "filesystem"
    assert first.byte_length == payload.byte_length
    assert store.delete_if_match(first) is False


def test_filesystem_store_never_overwrites_corrupt_existing_object(tmp_path):
    manifest = _fixture_object()
    manifest["release"]["digest"]["value"] = EXPECTED_MINIMAL_DIGEST
    payload = canonicalize_and_verify(json.dumps(manifest).encode())
    store = LocalFilesystemArtifactStore(tmp_path)
    destination = store._path(payload.digest)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"corrupt")
    with pytest.raises(ArtifactIntegrityError, match="corrupt"):
        store.put_if_absent(payload)
    assert destination.read_bytes() == b"corrupt"


def test_filesystem_store_rejects_path_traversal_digest(tmp_path):
    store = LocalFilesystemArtifactStore(tmp_path)
    with pytest.raises(ValueError):
        store.read(DigestIdentity(DIGEST_PROFILE, DIGEST_ALGORITHM, "../escape"))
