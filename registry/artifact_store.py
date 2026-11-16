"""Immutable local filesystem ArtifactStore adapter (PSI-40).

The adapter is suitable for development and deterministic tests. It disables
automatic deletion because portable filesystem APIs do not provide a
cross-process generation-conditional unlink guarantee.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .digests import ReleaseDigestError, verify_canonical_payload
from .publication_contracts import (
    CanonicalReleasePayload,
    DigestIdentity,
    StoredArtifact,
)

_PROFILE = "efs-jcs-sha256-v1"
_ALGORITHM = "SHA-256"
_VALUE = re.compile(r"^[A-Za-z0-9_-]{43}$")


class ArtifactIntegrityError(RuntimeError):
    """An existing or retrieved artifact failed content verification."""


class LocalFilesystemArtifactStore:
    """Content-addressed, create-if-absent storage rooted at a private directory."""

    provider = "filesystem"

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_digest(digest: DigestIdentity) -> None:
        if (
            digest.profile != _PROFILE
            or digest.algorithm != _ALGORITHM
            or not _VALUE.fullmatch(digest.value)
        ):
            raise ValueError("unsupported or malformed EFS digest identity")

    def _path(self, digest: DigestIdentity) -> Path:
        self._validate_digest(digest)
        return self.root / digest.profile / digest.algorithm / f"{digest.value}.json"

    @staticmethod
    def _generation(path: Path) -> str:
        info = path.stat(follow_symlinks=False)
        return f"{info.st_dev}:{info.st_ino}:{info.st_mtime_ns}:{info.st_size}"

    def put_if_absent(self, payload: CanonicalReleasePayload) -> StoredArtifact:
        self._validate_digest(payload.digest)
        try:
            projection = verify_canonical_payload(payload.canonical_bytes, payload.digest)
        except ReleaseDigestError as exc:
            raise ArtifactIntegrityError("refusing to store an invalid canonical payload") from exc
        if not isinstance(projection, dict):
            raise ArtifactIntegrityError("canonical payload must contain an object projection")

        destination = self._path(payload.digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".incoming-", dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload.canonical_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Hard-link creation is atomic and fails rather than replacing an object.
                os.link(temporary, destination)
                directory_fd = os.open(destination.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except FileExistsError:
                if destination.is_symlink() or not destination.is_file():
                    raise ArtifactIntegrityError("existing digest object is not a regular file")
                existing = destination.read_bytes()
                try:
                    verify_canonical_payload(existing, payload.digest)
                except ReleaseDigestError as exc:
                    raise ArtifactIntegrityError("existing digest object is corrupt") from exc
                if len(existing) != payload.byte_length:
                    raise ArtifactIntegrityError("existing digest object has an unexpected byte length")
        finally:
            temporary.unlink(missing_ok=True)

        if destination.is_symlink() or not destination.is_file():
            raise ArtifactIntegrityError("stored digest object is not a regular file")
        return StoredArtifact(
            digest=payload.digest,
            byte_length=destination.stat().st_size,
            provider=self.provider,
            object_key=destination.relative_to(self.root).as_posix(),
            generation=self._generation(destination),
        )

    def read(self, digest: DigestIdentity) -> bytes:
        path = self._path(digest)
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError("artifact is absent or is not a regular file")
        raw = path.read_bytes()
        try:
            verify_canonical_payload(raw, digest)
        except ReleaseDigestError as exc:
            raise ArtifactIntegrityError("stored artifact failed digest verification") from exc
        return raw

    def describe(self, digest: DigestIdentity) -> StoredArtifact | None:
        path = self._path(digest)
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise ArtifactIntegrityError("digest object is not a regular file")
        raw = path.read_bytes()
        try:
            verify_canonical_payload(raw, digest)
        except ReleaseDigestError as exc:
            raise ArtifactIntegrityError("existing digest object is corrupt") from exc
        return StoredArtifact(
            digest=digest,
            byte_length=len(raw),
            provider=self.provider,
            object_key=path.relative_to(self.root).as_posix(),
            generation=self._generation(path),
        )

    def delete_if_match(self, artifact: StoredArtifact) -> bool:
        """Deletion is disabled until a portable conditional-unlink primitive exists."""
        self._validate_digest(artifact.digest)
        return False
