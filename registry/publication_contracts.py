"""Shared internal contracts for PSI-39 publication and PSI-40 artifact storage.

These protocols deliberately contain no HTTP, SQLAlchemy, PostgreSQL, publisher
trust, or product-specific identity behavior. See
docs/registry-publication-protocol.md for normative transaction semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class DigestIdentity:
    """Complete content identity; the tuple is never inferred from a key."""

    profile: str
    algorithm: str
    value: str


@dataclass(frozen=True, slots=True)
class CanonicalReleasePayload:
    """Exact canonical envelope bytes whose SHA-256 is identified by digest."""

    digest: DigestIdentity
    canonical_bytes: bytes

    @property
    def byte_length(self) -> int:
        return len(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """Storage receipt; provider keys are operational locators, not identities."""

    digest: DigestIdentity
    byte_length: int
    provider: str
    object_key: str
    generation: str | None = None


PublicationState = Literal["pending", "committed", "conflict", "failed"]


@dataclass(frozen=True, slots=True)
class PublicationRequest:
    """Validated intent reserved before any external storage I/O."""

    idempotency_key: str
    request_fingerprint: str
    publisher_uri: str
    factory_id: str
    version: str
    digest: DigestIdentity
    payload_length: int


@dataclass(frozen=True, slots=True)
class PublicationOperation:
    operation_id: str
    request: PublicationRequest
    state: PublicationState
    failure_code: str | None = None
    release_record_id: str | None = None


@dataclass(frozen=True, slots=True)
class PublicationResult:
    state: Literal["committed", "pending", "conflict", "rejected"]
    operation_id: str | None = None
    release_record_id: str | None = None
    error_code: str | None = None


class ReleaseDigestService(Protocol):
    """PSI-40 implementation of the one approved EFS release digest profile."""

    def canonicalize_and_verify(self, manifest_bytes: bytes) -> CanonicalReleasePayload:
        """Strictly parse, project, JCS-canonicalize and verify supplied digest."""
        ...


class ArtifactStore(Protocol):
    """PSI-40 content-addressed storage boundary; no publisher/factory concepts."""

    def put_if_absent(self, payload: CanonicalReleasePayload) -> StoredArtifact:
        """Durably create once, or verify and return an identical existing object."""
        ...

    def read(self, digest: DigestIdentity) -> bytes:
        """Return object bytes; caller independently recomputes the digest."""
        ...

    def describe(self, digest: DigestIdentity) -> StoredArtifact | None:
        """Return verified storage metadata, or None when the object is absent."""
        ...

    def delete_if_match(self, artifact: StoredArtifact) -> bool:
        """Conditionally delete one exact generation; maintenance/GC only."""
        ...


class PublicationOperationRepository(Protocol):
    """PSI-39 durable PostgreSQL operation boundary; each method owns its DB txn."""

    def prepare_or_get(self, request: PublicationRequest) -> PublicationOperation:
        """Reserve intent or return an existing operation after fingerprint checks."""
        ...

    def get(self, operation_id: str) -> PublicationOperation | None:
        ...

    def list_recoverable(self, limit: int) -> list[PublicationOperation]:
        """Return bounded pending operations in deterministic order."""
        ...

    def finalize_release(self, operation_id: str, artifact: StoredArtifact) -> str:
        """Atomically persist blob/location/release and mark operation committed."""
        ...

    def record_retryable_failure(self, operation_id: str, code: str) -> None:
        ...

    def record_terminal_conflict(self, operation_id: str, code: str) -> None:
        ...
