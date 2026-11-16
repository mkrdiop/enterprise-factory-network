"""Publication orchestration shared by the versioned registry API (PSI-39)."""
from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from scripts.validate_manifest import validate_report

from .artifact_store import ArtifactIntegrityError
from .digests import ReleaseDigestError, verify_canonical_payload
from .publication_contracts import (
    ArtifactStore,
    PublicationOperationRepository,
    PublicationRequest,
    PublicationResult,
    ReleaseDigestService,
)
from .repositories import RegistryConflict

logger = logging.getLogger(__name__)


class ManifestValidationError(ValueError):
    """Manifest failed the normative EFS schema or semantic conformance stages."""

    def __init__(self, report: dict):
        self.report = report
        super().__init__("Factory Manifest is not EFS v1 conformant")


class RegistryPublicationService:
    """Coordinates validation, durable intent, immutable storage and DB commit."""

    def __init__(
        self,
        operation_repository: PublicationOperationRepository,
        digest_service: ReleaseDigestService,
        artifact_store: ArtifactStore,
        schema_path: str | Path,
    ):
        self.operation_repository = operation_repository
        self.digest_service = digest_service
        self.artifact_store = artifact_store
        self.schema_path = Path(schema_path)

    def _validate(self, manifest_bytes: bytes) -> dict:
        # Reuse the canonical repository validator; temporary input avoids a
        # second schema/profile implementation or a divergent API validator.
        with tempfile.TemporaryDirectory(prefix="efs-manifest-") as directory:
            path = Path(directory) / "manifest.json"
            path.write_bytes(manifest_bytes)
            report = validate_report(path, self.schema_path)
        if not report["valid"]:
            raise ManifestValidationError(report)
        return report

    @staticmethod
    def _request_fingerprint(
        publisher_uri: str, factory_id: str, version: str, digest
    ) -> str:
        identity = [
            publisher_uri,
            factory_id,
            version,
            digest.profile,
            digest.algorithm,
            digest.value,
        ]
        encoded = json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def publish(self, manifest_bytes: bytes, idempotency_key: str) -> PublicationResult:
        self._validate(manifest_bytes)
        payload = self.digest_service.canonicalize_and_verify(manifest_bytes)
        # canonicalize_and_verify has already strictly parsed the same bytes,
        # rejecting duplicate members, invalid UTF-8 and non-JSON constants.
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        publisher_uri = manifest["publisher"]["id"]
        factory_id = manifest["factory"]["id"]
        version = manifest["release"]["version"]
        request = PublicationRequest(
            idempotency_key=idempotency_key,
            request_fingerprint=self._request_fingerprint(
                publisher_uri, factory_id, version, payload.digest
            ),
            publisher_uri=publisher_uri,
            factory_id=factory_id,
            version=version,
            digest=payload.digest,
            payload_length=payload.byte_length,
        )

        try:
            operation = self.operation_repository.prepare_or_get(request)
        except RegistryConflict as exc:
            return PublicationResult(state="conflict", error_code=exc.code)

        if operation.state == "committed":
            return PublicationResult(
                state="committed",
                operation_id=operation.operation_id,
                release_record_id=operation.release_record_id,
            )
        if operation.state == "conflict":
            return PublicationResult(
                state="conflict",
                operation_id=operation.operation_id,
                error_code=operation.failure_code or "EFS_RELEASE_VERSION_CONFLICT",
            )
        if operation.state != "pending":
            return PublicationResult(
                state="conflict",
                operation_id=operation.operation_id,
                error_code="EFS_PUBLICATION_NOT_RECOVERABLE",
            )

        try:
            stored = self.artifact_store.put_if_absent(payload)
            stored_bytes = self.artifact_store.read(payload.digest)
            verify_canonical_payload(stored_bytes, payload.digest)
            if stored_bytes != payload.canonical_bytes or len(stored_bytes) != payload.byte_length:
                raise ReleaseDigestError("stored bytes differ from canonical payload")
            release_id = self.operation_repository.finalize_release(
                operation.operation_id, stored
            )
            return PublicationResult(
                state="committed",
                operation_id=operation.operation_id,
                release_record_id=release_id,
            )
        except RegistryConflict:
            current = self.operation_repository.get(operation.operation_id)
            return PublicationResult(
                state="conflict",
                operation_id=operation.operation_id,
                error_code=(
                    current.failure_code
                    if current is not None and current.failure_code
                    else "EFS_RELEASE_VERSION_CONFLICT"
                ),
            )
        except (ReleaseDigestError, ArtifactIntegrityError):
            self.operation_repository.record_terminal_conflict(
                operation.operation_id, "EFS_ARTIFACT_INTEGRITY_FAILURE"
            )
            return PublicationResult(
                state="conflict",
                operation_id=operation.operation_id,
                error_code="EFS_ARTIFACT_INTEGRITY_FAILURE",
            )
        except (OSError, TimeoutError, ConnectionError, SQLAlchemyError):
            # The outcome of a failed/timeout put may be unknown. Keep the
            # operation pending; a retry repeats put-if-absent and verifies.
            try:
                self.operation_repository.record_retryable_failure(
                    operation.operation_id, "EFS_ARTIFACT_UNAVAILABLE"
                )
            except SQLAlchemyError:
                # The already-committed pending intent is the recovery anchor;
                # if the DB is unavailable, do not hide the original pending state.
                logger.exception("Could not persist retryable publication failure")
            return PublicationResult(
                state="pending",
                operation_id=operation.operation_id,
                error_code="EFS_ARTIFACT_UNAVAILABLE",
            )


    def recover_pending(self, limit: int = 50) -> dict[str, int]:
        """Resume pending operations whose digest-addressed object is already present.

        Missing objects remain pending for client resubmission. This method is
        bounded and safe to run repeatedly from an external scheduler.
        """
        operations = self.operation_repository.list_recoverable(limit)
        counts = {"scanned": len(operations), "committed": 0, "absent": 0, "conflict": 0, "pending": 0}
        for operation in operations:
            try:
                stored = self.artifact_store.describe(operation.request.digest)
                if stored is None:
                    counts["absent"] += 1
                    continue
                raw = self.artifact_store.read(operation.request.digest)
                projection = verify_canonical_payload(raw, operation.request.digest)
                if (
                    projection.get("publisher", {}).get("id") != operation.request.publisher_uri
                    or projection.get("factory", {}).get("id") != operation.request.factory_id
                    or projection.get("release", {}).get("version") != operation.request.version
                ):
                    raise ReleaseDigestError("recovered artifact identity differs from publication intent")
                if len(raw) != operation.request.payload_length or stored.byte_length != len(raw):
                    raise ReleaseDigestError("recovered artifact length differs from publication intent")
                self.operation_repository.finalize_release(operation.operation_id, stored)
                counts["committed"] += 1
            except RegistryConflict:
                counts["conflict"] += 1
            except (ReleaseDigestError, ArtifactIntegrityError):
                self.operation_repository.record_terminal_conflict(
                    operation.operation_id, "EFS_ARTIFACT_INTEGRITY_FAILURE"
                )
                counts["conflict"] += 1
            except (OSError, TimeoutError, ConnectionError, SQLAlchemyError):
                try:
                    self.operation_repository.record_retryable_failure(
                        operation.operation_id, "EFS_ARTIFACT_UNAVAILABLE"
                    )
                except SQLAlchemyError:
                    logger.exception("Could not persist recovery retry diagnostic")
                counts["pending"] += 1
        return counts
