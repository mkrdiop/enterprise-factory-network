"""HTTP contract tests for the versioned registry API."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from registry.api import create_app
from registry.digests import canonicalize_and_verify
from registry.publication_contracts import PublicationResult

ROOT = Path(__file__).resolve().parents[1]
VECTOR = json.loads(
    (ROOT / "conformance/efs/v1/release-digest-vectors.json").read_text(encoding="utf-8")
)["vectors"][0]
EXPECTED_DIGEST = VECTOR["expectedDigest"]


class FakeOperationRepository:
    def __init__(self):
        self.operation = None

    def get(self, operation_id):
        if self.operation and self.operation.operation_id == operation_id:
            return self.operation
        return None


class FakePublicationService:
    def __init__(self):
        self.operation_repository = FakeOperationRepository()
        self.result = PublicationResult(state="committed", operation_id="op-1", release_record_id="release-1")

    def publish(self, _body, _key):
        return self.result


class FakeQueryRepository:
    def __init__(self, payload):
        self.payload = payload

    def get_factory(self, publisher_id, factory_id):
        return {
            "publisherId": publisher_id,
            "factoryId": factory_id,
            "releaseCount": 1,
            "lifecycleState": "active",
        }

    def list_releases(self, _publisher_id, _factory_id, _limit, _cursor):
        return {"items": [{"version": "1.2.0"}], "nextCursor": None}

    def get_release(self, publisher_id, factory_id, version):
        return {
            "publisherId": publisher_id,
            "factoryId": factory_id,
            "version": version,
            "digest": {
                "profile": self.payload.digest.profile,
                "algorithm": self.payload.digest.algorithm,
                "value": self.payload.digest.value,
            },
            "byteLength": self.payload.byte_length,
            "provider": "test-memory",
            "objectKey": "opaque-test-key",
            "publishedAt": "2026-11-16T00:00:00+00:00",
        }


class FakeArtifactStore:
    provider = "test-memory"

    def __init__(self, payload):
        self.payload = payload

    def read(self, _digest):
        return self.payload.canonical_bytes


def _payload():
    manifest = json.loads((ROOT / VECTOR["fixture"]).read_text(encoding="utf-8"))
    manifest["release"]["digest"]["value"] = EXPECTED_DIGEST
    return canonicalize_and_verify(json.dumps(manifest).encode())


def _client():
    payload = _payload()
    publication = FakePublicationService()
    query = FakeQueryRepository(payload)
    store = FakeArtifactStore(payload)
    return TestClient(create_app(publication, query, store)), publication, payload


def test_publish_returns_created_for_committed_operation():
    client, _publication, _payload_value = _client()
    response = client.post(
        "/v1/releases",
        headers={"Idempotency-Key": "api-test-1"},
        content=b'{"manifest":"accepted by fake service"}',
    )
    assert response.status_code == 201
    assert response.json()["state"] == "committed"


def test_publish_returns_accepted_for_pending_operation():
    client, publication, _payload_value = _client()
    publication.result = PublicationResult(state="pending", operation_id="op-pending")
    response = client.post(
        "/v1/releases",
        headers={"Idempotency-Key": "api-test-2"},
        content=b"{}",
    )
    assert response.status_code == 202
    assert response.json()["state"] == "pending"


def test_publish_returns_conflict_for_immutable_version_collision():
    client, publication, _payload_value = _client()
    publication.result = PublicationResult(
        state="conflict",
        operation_id="op-conflict",
        error_code="EFS_RELEASE_VERSION_CONFLICT",
    )
    response = client.post(
        "/v1/releases",
        headers={"Idempotency-Key": "api-test-3"},
        content=b"{}",
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "EFS_RELEASE_VERSION_CONFLICT"


def test_missing_idempotency_header_uses_stable_error_envelope():
    client, _publication, _payload_value = _client()
    response = client.post("/v1/releases", content=b"{}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EFS_REQUEST_INVALID"


def test_exact_release_retrieval_reconstructs_verified_manifest():
    client, _publication, _payload_value = _client()
    response = client.get(
        "/v1/releases",
        params={
            "publisher_id": "urn:example:publishers:acme",
            "factory_id": "customer-support",
            "version": "1.2.0",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["release"]["digest"]["value"] == EXPECTED_DIGEST
    assert "signature" not in body["release"]


def test_factory_lookup_and_release_pagination_are_versioned():
    client, _publication, _payload_value = _client()
    factory = client.get(
        "/v1/factories",
        params={"publisher_id": "urn:example:publishers:acme", "factory_id": "customer-support"},
    )
    releases = client.get(
        "/v1/factories/releases",
        params={"publisher_id": "urn:example:publishers:acme", "factory_id": "customer-support"},
    )
    assert factory.status_code == 200
    assert factory.json()["releaseCount"] == 1
    assert releases.status_code == 200
    assert releases.json()["items"][0]["version"] == "1.2.0"


def test_publication_status_returns_not_found_for_unknown_operation():
    client, _publication, _payload_value = _client()
    response = client.get("/v1/publications/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EFS_REGISTRY_NOT_FOUND"
