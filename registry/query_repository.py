"""Exact-identity registry read models and deterministic keyset pagination."""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import sessionmaker

from scripts.validate_manifest import canonical_publisher_uri

from .models import ArtifactBlob, ArtifactLocation, Factory, FactoryRelease, Publisher
from .repositories import RegistryNotFound


class ArtifactLocationUnavailable(RuntimeError):
    """A published release has no active artifact location."""


class RegistryQueryRepository:
    def __init__(self, session_factory: sessionmaker):
        self.session_factory = session_factory

    @staticmethod
    def _validate_identity(publisher_uri: str) -> None:
        if canonical_publisher_uri(publisher_uri) != publisher_uri:
            raise ValueError("publisher URI must be canonical under efs-uri-c14n-1")

    @staticmethod
    def _encode_cursor(published_at: datetime, release_id: uuid.UUID) -> str:
        payload = json.dumps(
            {"publishedAt": published_at.isoformat(), "releaseRecordId": str(release_id)},
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
            published_at = datetime.fromisoformat(payload["publishedAt"])
            release_id = uuid.UUID(payload["releaseRecordId"])
            if published_at.tzinfo is None:
                raise ValueError("cursor timestamp must include a timezone")
            return published_at, release_id
        except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
            raise ValueError("invalid release pagination cursor") from exc

    def get_factory(self, publisher_uri: str, factory_id: str) -> dict[str, Any]:
        self._validate_identity(publisher_uri)
        with self.session_factory() as session:
            factory = session.scalar(
                select(Factory)
                .join(Publisher, Factory.publisher_record_id == Publisher.publisher_record_id)
                .where(
                    Publisher.publisher_uri == publisher_uri,
                    Factory.factory_id == factory_id,
                )
            )
            if factory is None:
                raise RegistryNotFound("Factory not found")
            releases = session.scalars(
                select(FactoryRelease.release_record_id).where(
                    FactoryRelease.factory_record_id == factory.factory_record_id
                )
            ).all()
            if not releases:
                # A pending publication does not make a Factory discoverable.
                raise RegistryNotFound("Factory not found")
            publisher = session.get(Publisher, factory.publisher_record_id)
            return {
                "publisherId": publisher.publisher_uri,
                "factoryId": factory.factory_id,
                "releaseCount": len(releases),
                "lifecycleState": factory.lifecycle_state,
            }

    def list_releases(
        self,
        publisher_uri: str,
        factory_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._validate_identity(publisher_uri)
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self.session_factory() as session:
            factory = session.scalar(
                select(Factory)
                .join(Publisher, Factory.publisher_record_id == Publisher.publisher_record_id)
                .where(
                    Publisher.publisher_uri == publisher_uri,
                    Factory.factory_id == factory_id,
                )
            )
            if factory is None:
                raise RegistryNotFound("Factory not found")
            statement = select(FactoryRelease).where(
                FactoryRelease.factory_record_id == factory.factory_record_id
            )
            if cursor:
                timestamp, release_id = self._decode_cursor(cursor)
                statement = statement.where(
                    or_(
                        FactoryRelease.published_at < timestamp,
                        and_(
                            FactoryRelease.published_at == timestamp,
                            FactoryRelease.release_record_id < release_id,
                        ),
                    )
                )
            rows = session.scalars(
                statement.order_by(
                    FactoryRelease.published_at.desc(),
                    FactoryRelease.release_record_id.desc(),
                ).limit(limit + 1)
            ).all()
            has_more = len(rows) > limit
            page = rows[:limit]
            items = [
                {
                    "version": row.version,
                    "digest": {
                        "profile": row.digest_profile,
                        "algorithm": row.digest_algorithm,
                        "value": row.digest_value,
                    },
                    "publishedAt": row.published_at.isoformat(),
                }
                for row in page
            ]
            next_cursor = (
                self._encode_cursor(page[-1].published_at, page[-1].release_record_id)
                if has_more and page
                else None
            )
            return {"items": items, "nextCursor": next_cursor}

    def get_release(
        self, publisher_uri: str, factory_id: str, version: str
    ) -> dict[str, Any]:
        self._validate_identity(publisher_uri)
        with self.session_factory() as session:
            release = session.scalar(
                select(FactoryRelease)
                .join(Factory, FactoryRelease.factory_record_id == Factory.factory_record_id)
                .join(Publisher, Factory.publisher_record_id == Publisher.publisher_record_id)
                .where(
                    Publisher.publisher_uri == publisher_uri,
                    Factory.factory_id == factory_id,
                    FactoryRelease.version == version,
                )
            )
            if release is None:
                raise RegistryNotFound("Factory release not found")
            blob = session.get(ArtifactBlob, release.artifact_blob_id)
            location = session.scalar(
                select(ArtifactLocation)
                .where(
                    ArtifactLocation.artifact_blob_id == release.artifact_blob_id,
                    ArtifactLocation.location_state == "active",
                )
                .order_by(ArtifactLocation.provider, ArtifactLocation.object_key)
            )
            if blob is None or location is None:
                raise ArtifactLocationUnavailable("release artifact location is unavailable")
            return {
                "publisherId": publisher_uri,
                "factoryId": factory_id,
                "version": release.version,
                "digest": {
                    "profile": release.digest_profile,
                    "algorithm": release.digest_algorithm,
                    "value": release.digest_value,
                },
                "byteLength": blob.byte_length,
                "provider": location.provider,
                "objectKey": location.object_key,
                "generation": location.generation,
                "publishedAt": release.published_at.isoformat(),
            }
