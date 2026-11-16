"""PostgreSQL publication-operation repository (PSI-39).

Each public method owns a short database transaction. External artifact-store
I/O is deliberately performed by the publication service between transactions.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from scripts.validate_manifest import canonical_publisher_uri

from .models import (
    ArtifactBlob,
    ArtifactLocation,
    Factory,
    FactoryRelease,
    Publisher,
)
from .models import PublicationOperation as PublicationOperationRow
from .publication_contracts import (
    DigestIdentity,
    PublicationOperation,
    PublicationRequest,
    StoredArtifact,
)
from .repositories import RegistryConflict, RegistryNotFound


class SQLPublicationOperationRepository:
    """Durable operation ledger and atomic release finalization."""

    def __init__(self, session_factory: sessionmaker):
        self.session_factory = session_factory

    @staticmethod
    def _to_domain(session, row: PublicationOperationRow) -> PublicationOperation:
        factory = session.get(Factory, row.factory_record_id)
        if factory is None:
            raise RegistryNotFound("publication operation Factory no longer exists")
        publisher = session.get(Publisher, factory.publisher_record_id)
        if publisher is None:
            raise RegistryNotFound("publication operation publisher no longer exists")
        request = PublicationRequest(
            idempotency_key=row.idempotency_key,
            request_fingerprint=row.request_fingerprint,
            publisher_uri=publisher.publisher_uri,
            factory_id=factory.factory_id,
            version=row.version,
            digest=DigestIdentity(row.digest_profile, row.digest_algorithm, row.digest_value),
            payload_length=row.payload_length,
        )
        return PublicationOperation(
            operation_id=str(row.publication_operation_id),
            request=request,
            state=row.state,
            failure_code=row.failure_code,
            release_record_id=(None if row.release_record_id is None else str(row.release_record_id)),
        )

    @staticmethod
    def _ensure_factory(session, request: PublicationRequest) -> Factory:
        if canonical_publisher_uri(request.publisher_uri) != request.publisher_uri:
            raise RegistryConflict("publisher URI is not canonical under efs-uri-c14n-1", code="EFS_PUBLISHER_URI_NON_CANONICAL")

        publisher = session.scalar(
            select(Publisher)
            .where(Publisher.publisher_uri == request.publisher_uri)
            .with_for_update()
        )
        if publisher is None:
            session.execute(
                insert(Publisher)
                .values(
                    publisher_record_id=uuid.uuid4(),
                    publisher_uri=request.publisher_uri,
                    lifecycle_state="active",
                )
                .on_conflict_do_nothing(index_elements=[Publisher.publisher_uri])
            )
            publisher = session.scalar(
                select(Publisher)
                .where(Publisher.publisher_uri == request.publisher_uri)
                .with_for_update()
            )
        if publisher is None:
            raise RegistryConflict("publisher namespace could not be reserved")
        if publisher.lifecycle_state != "active":
            raise RegistryConflict("publisher is retired", code="EFS_PUBLISHER_RETIRED")

        factory = session.scalar(
            select(Factory)
            .where(
                Factory.publisher_record_id == publisher.publisher_record_id,
                Factory.factory_id == request.factory_id,
            )
            .with_for_update()
        )
        if factory is None:
            session.execute(
                insert(Factory)
                .values(
                    factory_record_id=uuid.uuid4(),
                    publisher_record_id=publisher.publisher_record_id,
                    factory_id=request.factory_id,
                    lifecycle_state="active",
                )
                .on_conflict_do_nothing(
                    index_elements=[Factory.publisher_record_id, Factory.factory_id]
                )
            )
            factory = session.scalar(
                select(Factory)
                .where(
                    Factory.publisher_record_id == publisher.publisher_record_id,
                    Factory.factory_id == request.factory_id,
                )
                .with_for_update()
            )
        if factory is None:
            raise RegistryConflict("Factory identity could not be reserved")
        if factory.lifecycle_state != "active":
            raise RegistryConflict("Factory is retired", code="EFS_FACTORY_RETIRED")
        return factory

    def prepare_or_get(self, request: PublicationRequest) -> PublicationOperation:
        if not request.idempotency_key or len(request.idempotency_key) > 255:
            raise ValueError("Idempotency-Key must contain 1 to 255 characters")
        if request.payload_length < 0:
            raise ValueError("payload length cannot be negative")

        with self.session_factory.begin() as session:
            # Serialize requests sharing one key before creating any identity rows.
            session.execute(
                select(func.pg_advisory_xact_lock(func.hashtext(request.idempotency_key)))
            )
            existing = session.scalar(
                select(PublicationOperationRow)
                .where(PublicationOperationRow.idempotency_key == request.idempotency_key)
                .with_for_update()
            )
            if existing is not None:
                if existing.request_fingerprint != request.request_fingerprint:
                    raise RegistryConflict("idempotency key was reused for a different request", code="EFS_IDEMPOTENCY_KEY_REUSED")
                return self._to_domain(session, existing)

            factory = self._ensure_factory(session, request)
            release = session.scalar(
                select(FactoryRelease)
                .where(
                    FactoryRelease.factory_record_id == factory.factory_record_id,
                    FactoryRelease.version == request.version,
                )
                .with_for_update()
            )
            state = "pending"
            failure_code = None
            release_record_id = None
            if release is not None:
                if (
                    release.digest_profile == request.digest.profile
                    and release.digest_algorithm == request.digest.algorithm
                    and release.digest_value == request.digest.value
                ):
                    state = "committed"
                    release_record_id = release.release_record_id
                else:
                    state = "conflict"
                    failure_code = "EFS_RELEASE_VERSION_CONFLICT"

            row = PublicationOperationRow(
                publication_operation_id=uuid.uuid4(),
                idempotency_key=request.idempotency_key,
                request_fingerprint=request.request_fingerprint,
                factory_record_id=factory.factory_record_id,
                version=request.version,
                digest_profile=request.digest.profile,
                digest_algorithm=request.digest.algorithm,
                digest_value=request.digest.value,
                payload_length=request.payload_length,
                state=state,
                release_record_id=release_record_id,
                failure_code=failure_code,
            )
            session.add(row)
            session.flush()
            return self._to_domain(session, row)

    def get(self, operation_id: str) -> PublicationOperation | None:
        try:
            key = uuid.UUID(operation_id)
        except ValueError as exc:
            raise ValueError("operation ID must be a UUID") from exc
        with self.session_factory() as session:
            row = session.get(PublicationOperationRow, key)
            return None if row is None else self._to_domain(session, row)

    def list_recoverable(self, limit: int) -> list[PublicationOperation]:
        if not 1 <= limit <= 500:
            raise ValueError("recovery batch limit must be between 1 and 500")
        with self.session_factory() as session:
            rows = session.scalars(
                select(PublicationOperationRow)
                .where(PublicationOperationRow.state == "pending")
                .order_by(
                    PublicationOperationRow.created_at,
                    PublicationOperationRow.publication_operation_id,
                )
                .limit(limit)
            ).all()
            return [self._to_domain(session, row) for row in rows]

    def finalize_release(self, operation_id: str, artifact: StoredArtifact) -> str:
        try:
            operation_uuid = uuid.UUID(operation_id)
        except ValueError as exc:
            raise ValueError("operation ID must be a UUID") from exc

        conflict_code = None
        release_id = None
        with self.session_factory.begin() as session:
            operation = session.scalar(
                select(PublicationOperationRow)
                .where(PublicationOperationRow.publication_operation_id == operation_uuid)
                .with_for_update()
            )
            if operation is None:
                raise RegistryNotFound(operation_id)
            if operation.state == "committed":
                return str(operation.release_record_id)
            if operation.state == "conflict":
                raise RegistryConflict(operation.failure_code or "publication conflict", code=operation.failure_code or "EFS_REGISTRY_CONFLICT")
            if operation.state != "pending":
                raise RegistryConflict("publication operation is not recoverable", code="EFS_PUBLICATION_NOT_RECOVERABLE")

            expected = (
                operation.digest_profile,
                operation.digest_algorithm,
                operation.digest_value,
            )
            actual = (
                artifact.digest.profile,
                artifact.digest.algorithm,
                artifact.digest.value,
            )
            if expected != actual or operation.payload_length != artifact.byte_length:
                operation.state = "conflict"
                operation.failure_code = "EFS_ARTIFACT_INTEGRITY_FAILURE"
                conflict_code = operation.failure_code
            else:
                factory = session.scalar(
                    select(Factory)
                    .where(Factory.factory_record_id == operation.factory_record_id)
                    .with_for_update()
                )
                publisher = (
                    None
                    if factory is None
                    else session.scalar(
                        select(Publisher)
                        .where(Publisher.publisher_record_id == factory.publisher_record_id)
                        .with_for_update()
                    )
                )
                if factory is None or publisher is None:
                    operation.state = "conflict"
                    operation.failure_code = "EFS_REGISTRY_IDENTITY_NOT_FOUND"
                    conflict_code = operation.failure_code
                elif publisher.lifecycle_state != "active":
                    operation.state = "conflict"
                    operation.failure_code = "EFS_PUBLISHER_RETIRED"
                    conflict_code = operation.failure_code
                elif factory.lifecycle_state != "active":
                    operation.state = "conflict"
                    operation.failure_code = "EFS_FACTORY_RETIRED"
                    conflict_code = operation.failure_code
                else:
                    blob = session.scalar(
                        select(ArtifactBlob)
                        .where(
                            ArtifactBlob.digest_profile == operation.digest_profile,
                            ArtifactBlob.digest_algorithm == operation.digest_algorithm,
                            ArtifactBlob.digest_value == operation.digest_value,
                        )
                        .with_for_update()
                    )
                    if blob is None:
                        session.execute(
                            insert(ArtifactBlob)
                            .values(
                                artifact_blob_id=uuid.uuid4(),
                                digest_profile=operation.digest_profile,
                                digest_algorithm=operation.digest_algorithm,
                                digest_value=operation.digest_value,
                                byte_length=operation.payload_length,
                            )
                            .on_conflict_do_nothing(
                                index_elements=[
                                    ArtifactBlob.digest_profile,
                                    ArtifactBlob.digest_algorithm,
                                    ArtifactBlob.digest_value,
                                ]
                            )
                        )
                        blob = session.scalar(
                            select(ArtifactBlob)
                            .where(
                                ArtifactBlob.digest_profile == operation.digest_profile,
                                ArtifactBlob.digest_algorithm == operation.digest_algorithm,
                                ArtifactBlob.digest_value == operation.digest_value,
                            )
                            .with_for_update()
                        )
                    if blob is None or blob.byte_length != operation.payload_length:
                        operation.state = "conflict"
                        operation.failure_code = "EFS_ARTIFACT_INTEGRITY_FAILURE"
                        conflict_code = operation.failure_code
                    else:
                        location = session.scalar(
                            select(ArtifactLocation)
                            .where(
                                ArtifactLocation.provider == artifact.provider,
                                ArtifactLocation.object_key == artifact.object_key,
                            )
                            .with_for_update()
                        )
                        if location is None:
                            session.execute(
                                insert(ArtifactLocation)
                                .values(
                                    artifact_location_id=uuid.uuid4(),
                                    artifact_blob_id=blob.artifact_blob_id,
                                    provider=artifact.provider,
                                    object_key=artifact.object_key,
                                    generation=artifact.generation,
                                    location_state="active",
                                )
                                .on_conflict_do_nothing(
                                    index_elements=[
                                        ArtifactLocation.provider,
                                        ArtifactLocation.object_key,
                                    ]
                                )
                            )
                            location = session.scalar(
                                select(ArtifactLocation)
                                .where(
                                    ArtifactLocation.provider == artifact.provider,
                                    ArtifactLocation.object_key == artifact.object_key,
                                )
                                .with_for_update()
                            )
                        generation_mismatch = (
                            location is not None
                            and location.generation is not None
                            and artifact.generation is not None
                            and location.generation != artifact.generation
                        )
                        if location is None or location.artifact_blob_id != blob.artifact_blob_id or generation_mismatch:
                            operation.state = "conflict"
                            operation.failure_code = "EFS_ARTIFACT_LOCATION_CONFLICT"
                            conflict_code = operation.failure_code
                        else:
                            if location.generation is None and artifact.generation is not None:
                                location.generation = artifact.generation
                            # The bytes were just read and verified by the caller;
                            # an inactive location may safely be reactivated.
                            location.location_state = "active"
                            release = session.scalar(
                                select(FactoryRelease)
                                .where(
                                    FactoryRelease.factory_record_id == factory.factory_record_id,
                                    FactoryRelease.version == operation.version,
                                )
                                .with_for_update()
                            )
                            if release is not None:
                                same_digest = (
                                    release.digest_profile == operation.digest_profile
                                    and release.digest_algorithm == operation.digest_algorithm
                                    and release.digest_value == operation.digest_value
                                )
                                if same_digest:
                                    release_id = release.release_record_id
                                else:
                                    operation.state = "conflict"
                                    operation.failure_code = "EFS_RELEASE_VERSION_CONFLICT"
                                    conflict_code = operation.failure_code
                            else:
                                release = FactoryRelease(
                                    factory_record_id=factory.factory_record_id,
                                    version=operation.version,
                                    digest_profile=operation.digest_profile,
                                    digest_algorithm=operation.digest_algorithm,
                                    digest_value=operation.digest_value,
                                    artifact_blob_id=blob.artifact_blob_id,
                                    published_at=datetime.now(UTC),
                                )
                                session.add(release)
                                session.flush()
                                release_id = release.release_record_id

                            if conflict_code is None:
                                operation.state = "committed"
                                operation.release_record_id = release_id
                                operation.failure_code = None

            operation.updated_at = datetime.now(UTC)

        if conflict_code is not None:
            raise RegistryConflict(conflict_code, code=conflict_code)
        if release_id is None:
            raise RegistryConflict("publication finalization did not produce a release", code="EFS_PUBLICATION_FINALIZATION_FAILED")
        return str(release_id)

    def record_retryable_failure(self, operation_id: str, code: str) -> None:
        self._update_operation(operation_id, state="pending", code=code)

    def record_terminal_conflict(self, operation_id: str, code: str) -> None:
        self._update_operation(operation_id, state="conflict", code=code)

    def _update_operation(self, operation_id: str, state: str, code: str) -> None:
        try:
            operation_uuid = uuid.UUID(operation_id)
        except ValueError as exc:
            raise ValueError("operation ID must be a UUID") from exc
        with self.session_factory.begin() as session:
            row = session.scalar(
                select(PublicationOperationRow)
                .where(PublicationOperationRow.publication_operation_id == operation_uuid)
                .with_for_update()
            )
            if row is None:
                raise RegistryNotFound(operation_id)
            if row.state == "committed":
                return
            if row.state == "conflict" and state == "pending":
                raise RegistryConflict("terminal conflict cannot return to pending", code="EFS_PUBLICATION_NOT_RECOVERABLE")
            row.state = state
            row.failure_code = code
            row.updated_at = datetime.now(UTC)
