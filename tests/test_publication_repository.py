"""PSI-39 durable publication-operation repository integration tests."""
import base64
import copy
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
import rfc8785
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from registry.artifact_store import LocalFilesystemArtifactStore
from registry.digests import EFSReleaseDigestService, canonicalize_and_verify
from registry.models import ArtifactLocation, FactoryRelease
from registry.publication_contracts import (
    DigestIdentity,
    PublicationRequest,
    StoredArtifact,
)
from registry.publication_repository import SQLPublicationOperationRepository
from registry.publication_service import RegistryPublicationService
from registry.query_repository import RegistryQueryRepository
from registry.repositories import FactoryRepository, RegistryConflict, RegistryNotFound

URL = os.getenv("EFS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="EFS_TEST_DATABASE_URL not configured")


def _request(key, version="1.0.0", digest_value="A" * 43, fingerprint=None, namespace=None):
    digest = DigestIdentity("efs-jcs-sha256-v1", "SHA-256", digest_value)
    return PublicationRequest(
        idempotency_key=key,
        request_fingerprint=fingerprint or f"fingerprint-{key}",
        publisher_uri=f"urn:example:publishers:psi39:{namespace or key}",
        factory_id=f"publication-tests-{namespace or key}",
        version=version,
        digest=digest,
        payload_length=128,
    )


def _repo():
    engine = create_engine(URL)
    factory = sessionmaker(engine, expire_on_commit=False)
    return engine, factory, SQLPublicationOperationRepository(factory)


def _stored(request, object_key=None):
    return StoredArtifact(
        digest=request.digest,
        byte_length=request.payload_length,
        provider="filesystem",
        object_key=object_key or f"{request.digest.value}.json",
        generation="test-generation",
    )


def test_prepare_is_durable_idempotent_and_rejects_key_reuse():
    engine, _factory, repo = _repo()
    try:
        request = _request("psi39-idempotency")
        first = repo.prepare_or_get(request)
        replay = repo.prepare_or_get(request)
        assert first.state == "pending"
        assert replay.operation_id == first.operation_id
        assert len(repo.list_recoverable(20)) >= 1
        with pytest.raises(RegistryConflict, match="idempotency"):
            repo.prepare_or_get(replace(request, request_fingerprint="different"))
    finally:
        engine.dispose()


def test_finalize_commits_blob_location_release_and_operation_together():
    engine, _factory, repo = _repo()
    try:
        request = _request("psi39-finalize", version="finalize-v1")
        operation = repo.prepare_or_get(request)
        release_id = repo.finalize_release(operation.operation_id, _stored(request))
        committed = repo.get(operation.operation_id)
        assert committed.state == "committed"
        assert committed.release_record_id == release_id
        with Session(engine) as session:
            rows = session.scalars(
                select(FactoryRelease).where(FactoryRelease.release_record_id == release_id)
            ).all()
            assert len(rows) == 1
            location = session.scalar(
                select(ArtifactLocation).where(
                    ArtifactLocation.artifact_blob_id == rows[0].artifact_blob_id
                )
            )
            assert location.generation == "test-generation"
    finally:
        engine.dispose()


def test_digest_mismatch_marks_operation_conflict_without_release():
    engine, _factory, repo = _repo()
    try:
        request = _request("psi39-digest-conflict", version="digest-mismatch-v1")
        operation = repo.prepare_or_get(request)
        wrong = replace(
            _stored(request),
            digest=DigestIdentity(request.digest.profile, request.digest.algorithm, "B" * 43),
        )
        with pytest.raises(RegistryConflict, match="INTEGRITY"):
            repo.finalize_release(operation.operation_id, wrong)
        current = repo.get(operation.operation_id)
        assert current.state == "conflict"
        assert current.failure_code == "EFS_ARTIFACT_INTEGRITY_FAILURE"
        with Session(engine) as session:
            assert session.scalar(
                select(FactoryRelease).where(FactoryRelease.version == request.version)
            ) is None
    finally:
        engine.dispose()


def test_different_digests_for_same_factory_version_have_one_immutable_winner():
    engine, _factory, repo = _repo()
    try:
        first_request = _request("psi39-version-winner", version="same-version", digest_value="C" * 43, namespace="version-race")
        second_request = _request("psi39-version-loser", version="same-version", digest_value="D" * 43, namespace="version-race")
        first = repo.prepare_or_get(first_request)
        second = repo.prepare_or_get(second_request)
        first_release = repo.finalize_release(first.operation_id, _stored(first_request))
        with pytest.raises(RegistryConflict, match="VERSION_CONFLICT"):
            repo.finalize_release(second.operation_id, _stored(second_request))
        assert repo.get(first.operation_id).release_record_id == first_release
        assert repo.get(second.operation_id).state == "conflict"
    finally:
        engine.dispose()


def test_same_factory_version_and_digest_reuses_existing_release():
    engine, _factory, repo = _repo()
    try:
        first_request = _request("psi39-same-release-one", version="same-content", digest_value="E" * 43, namespace="same-release")
        second_request = _request("psi39-same-release-two", version="same-content", digest_value="E" * 43, namespace="same-release")
        first = repo.prepare_or_get(first_request)
        release_id = repo.finalize_release(first.operation_id, _stored(first_request))
        second = repo.prepare_or_get(second_request)
        assert second.state == "committed"
        assert second.release_record_id == release_id
    finally:
        engine.dispose()


def test_retired_factory_cannot_finalize_pending_publication():
    engine, factory, repo = _repo()
    try:
        request = _request("psi39-retired-parent", version="retired-v1")
        operation = repo.prepare_or_get(request)
        with factory.begin() as session:
            FactoryRepository(session).retire(request.publisher_uri, request.factory_id)
        with pytest.raises(RegistryConflict, match="FACTORY_RETIRED"):
            repo.finalize_release(operation.operation_id, _stored(request))
        assert repo.get(operation.operation_id).state == "conflict"
    finally:
        engine.dispose()


def test_pending_factory_is_not_discoverable():
    engine, _factory, repo = _repo()
    try:
        request = _request("psi39-pending-invisible", version="pending-v1")
        repo.prepare_or_get(request)
        query = RegistryQueryRepository(repo.session_factory)
        with pytest.raises(RegistryNotFound):
            query.get_factory(request.publisher_uri, request.factory_id)
    finally:
        engine.dispose()


def test_release_listing_uses_stable_keyset_cursor_and_exact_versions():
    engine, _factory, repo = _repo()
    try:
        for index, letter in enumerate(("F", "G", "H")):
            request = _request(
                f"psi39-page-{index}",
                version=f"opaque-version-{index}",
                digest_value=letter * 43,
                namespace="pagination",
            )
            operation = repo.prepare_or_get(request)
            repo.finalize_release(operation.operation_id, _stored(request, f"{letter}.json"))
        query = RegistryQueryRepository(repo.session_factory)
        first = query.list_releases(
            "urn:example:publishers:psi39:pagination", "publication-tests-pagination", limit=2
        )
        second = query.list_releases(
            "urn:example:publishers:psi39:pagination",
            "publication-tests-pagination",
            limit=2,
            cursor=first["nextCursor"],
        )
        assert len(first["items"]) == 2
        assert first["nextCursor"]
        assert len(second["items"]) == 1
        assert second["nextCursor"] is None
        versions = {item["version"] for item in first["items"] + second["items"]}
        assert versions == {"opaque-version-0", "opaque-version-1", "opaque-version-2"}
    finally:
        engine.dispose()



def _fixture_payload(namespace):
    root = Path(__file__).resolve().parents[1]
    vectors = json.loads(
        (root / "conformance/efs/v1/release-digest-vectors.json").read_text(encoding="utf-8")
    )
    vector = vectors["vectors"][0]
    manifest = json.loads((root / vector["fixture"]).read_text(encoding="utf-8"))
    manifest["publisher"]["id"] = f"urn:example:publishers:psi39-recovery:{namespace}"
    manifest["factory"]["id"] = f"recovery-{namespace}"
    manifest["release"]["version"] = f"recovery-{namespace}"
    projection = copy.deepcopy(manifest)
    projection["release"].pop("digest", None)
    projection["release"].pop("signature", None)
    envelope = {"domain": "efs.factory-release.v1", "manifest": projection}
    canonical = rfc8785.dumps(envelope)
    digest = base64.urlsafe_b64encode(hashlib.sha256(canonical).digest()).rstrip(b"=").decode("ascii")
    manifest["release"]["digest"]["value"] = digest
    return root, canonicalize_and_verify(json.dumps(manifest).encode()), manifest


def _fixture_request(key, payload, manifest):
    identity = [
        manifest["publisher"]["id"],
        manifest["factory"]["id"],
        manifest["release"]["version"],
        payload.digest.profile,
        payload.digest.algorithm,
        payload.digest.value,
    ]
    fingerprint = hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return PublicationRequest(
        idempotency_key=key,
        request_fingerprint="fixture-" + fingerprint,
        publisher_uri=manifest["publisher"]["id"],
        factory_id=manifest["factory"]["id"],
        version=manifest["release"]["version"],
        digest=payload.digest,
        payload_length=payload.byte_length,
    )


def test_recovery_commits_object_written_before_process_crash(tmp_path):
    engine, _factory, repo = _repo()
    try:
        root, payload, manifest = _fixture_payload("present")
        request = _fixture_request("psi39-recovery-present", payload, manifest)
        operation = repo.prepare_or_get(request)
        store = LocalFilesystemArtifactStore(tmp_path)
        store.put_if_absent(payload)  # Simulate crash after Phase C and before Phase D.
        service = RegistryPublicationService(
            repo, EFSReleaseDigestService(), store, root / "schemas/efs/v1/factory-manifest.schema.json"
        )
        result = service.recover_pending(limit=500)
        assert result["committed"] >= 1
        assert repo.get(operation.operation_id).state == "committed"
    finally:
        engine.dispose()


def test_recovery_leaves_pending_operation_when_object_is_absent(tmp_path):
    engine, _factory, repo = _repo()
    try:
        root, payload, manifest = _fixture_payload("absent")
        request = _fixture_request("psi39-recovery-absent", payload, manifest)
        operation = repo.prepare_or_get(request)
        store = LocalFilesystemArtifactStore(tmp_path)
        service = RegistryPublicationService(
            repo, EFSReleaseDigestService(), store, root / "schemas/efs/v1/factory-manifest.schema.json"
        )
        result = service.recover_pending(limit=500)
        assert result["absent"] >= 1
        assert repo.get(operation.operation_id).state == "pending"
    finally:
        engine.dispose()


def test_recovery_quarantines_corrupt_existing_object(tmp_path):
    engine, _factory, repo = _repo()
    try:
        root, payload, manifest = _fixture_payload("corrupt")
        request = _fixture_request("psi39-recovery-corrupt", payload, manifest)
        operation = repo.prepare_or_get(request)
        store = LocalFilesystemArtifactStore(tmp_path)
        store.put_if_absent(payload)
        store._path(payload.digest).write_bytes(b"tampered")
        service = RegistryPublicationService(
            repo, EFSReleaseDigestService(), store, root / "schemas/efs/v1/factory-manifest.schema.json"
        )
        result = service.recover_pending(limit=500)
        assert result["conflict"] >= 1
        assert repo.get(operation.operation_id).state == "conflict"
        assert repo.get(operation.operation_id).failure_code == "EFS_ARTIFACT_INTEGRITY_FAILURE"
    finally:
        engine.dispose()
