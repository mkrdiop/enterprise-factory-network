"""Versioned HTTP/JSON adapter for the EFS manifest registry (PSI-39)."""
from __future__ import annotations

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from .artifact_store import ArtifactIntegrityError
from .digests import ReleaseDigestError, reconstruct_manifest
from .publication_contracts import DigestIdentity
from .publication_service import ManifestValidationError, RegistryPublicationService
from .passports import (
    PassportSourceMismatch,
    build_factory_passport,
    canonical_passport_json,
    render_factory_passport_markdown,
)
from .query_repository import (
    ArtifactLocationUnavailable,
    RegistryQueryRepository,
)
from .repositories import RegistryConflict, RegistryNotFound


def _error(code: str, message: str, **extra):
    return {"error": {"code": code, "message": message, **extra}}


def create_app(
    publication_service: RegistryPublicationService,
    query_repository: RegistryQueryRepository,
    artifact_store,
) -> FastAPI:
    app = FastAPI(
        title="Enterprise Factory Network Registry API",
        version="1.0.0",
        description=(
            "EFS v1 manifest registration and exact release retrieval. "
            "No latest-compatible resolution, publisher trust or policy authorization."
        ),
    )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=_error(
                "EFS_REQUEST_INVALID",
                "Request parameters or headers are invalid.",
                diagnostics=[
                    {"path": "/" + "/".join(str(part) for part in item["loc"]), "message": item["msg"]}
                    for item in exc.errors()
                ],
            ),
        )

    @app.exception_handler(ManifestValidationError)
    async def manifest_validation_error(_request: Request, exc: ManifestValidationError):
        return JSONResponse(
            status_code=422,
            content=_error(
                "EFS_MANIFEST_NOT_CONFORMANT",
                "Factory Manifest failed EFS v1 conformance validation.",
                diagnostics=exc.report["diagnostics"],
            ),
        )

    @app.exception_handler(ReleaseDigestError)
    async def digest_error(_request: Request, exc: ReleaseDigestError):
        return JSONResponse(
            status_code=422,
            content=_error("EFS_RELEASE_DIGEST_INVALID", str(exc)),
        )

    @app.exception_handler(RegistryConflict)
    async def registry_conflict(_request: Request, exc: RegistryConflict):
        return JSONResponse(
            status_code=409,
            content=_error(exc.code, str(exc)),
        )

    @app.exception_handler(RegistryNotFound)
    async def registry_not_found(_request: Request, exc: RegistryNotFound):
        return JSONResponse(
            status_code=404,
            content=_error("EFS_REGISTRY_NOT_FOUND", str(exc)),
        )

    @app.exception_handler(ArtifactLocationUnavailable)
    async def artifact_location_unavailable(_request: Request, exc: ArtifactLocationUnavailable):
        return JSONResponse(
            status_code=503,
            content=_error("EFS_ARTIFACT_UNAVAILABLE", str(exc)),
        )

    @app.exception_handler(PassportSourceMismatch)
    async def passport_source_mismatch(_request: Request, _exc: PassportSourceMismatch):
        return JSONResponse(
            status_code=503,
            content=_error(
                "EFS_ARTIFACT_INTEGRITY_FAILURE",
                "Registry release coordinates disagree with the verified artifact.",
            ),
        )

    @app.exception_handler(ArtifactIntegrityError)
    async def artifact_integrity_error(_request: Request, _exc: ArtifactIntegrityError):
        return JSONResponse(
            status_code=503,
            content=_error(
                "EFS_ARTIFACT_INTEGRITY_FAILURE",
                "Stored release artifact failed integrity verification.",
            ),
        )

    @app.exception_handler(FileNotFoundError)
    async def artifact_not_found(_request: Request, _exc: FileNotFoundError):
        return JSONResponse(
            status_code=503,
            content=_error("EFS_ARTIFACT_UNAVAILABLE", "Release artifact is temporarily unavailable."),
        )

    @app.exception_handler(ValueError)
    async def invalid_request(_request: Request, exc: ValueError):
        return JSONResponse(
            status_code=400,
            content=_error("EFS_REQUEST_INVALID", str(exc)),
        )

    @app.post("/v1/releases", status_code=201, tags=["releases"])
    async def publish_release(
        request: Request,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    ):
        result = publication_service.publish(await request.body(), idempotency_key)
        payload = {
            "state": result.state,
            "operationId": result.operation_id,
            "releaseRecordId": result.release_record_id,
            "errorCode": result.error_code,
        }
        if result.state == "pending":
            return JSONResponse(status_code=202, content=payload)
        if result.state == "conflict":
            return JSONResponse(status_code=409, content=payload)
        return JSONResponse(status_code=201, content=payload)

    @app.get("/v1/publications/{operation_id}", tags=["publications"])
    async def get_publication(operation_id: str):
        operation = publication_service.operation_repository.get(operation_id)
        if operation is None:
            raise RegistryNotFound("Publication operation not found")
        return {
            "operationId": operation.operation_id,
            "state": operation.state,
            "errorCode": operation.failure_code,
            "releaseRecordId": operation.release_record_id,
        }

    @app.get("/v1/factories", tags=["factories"])
    async def get_factory(
        publisher_id: str = Query(..., min_length=1),
        factory_id: str = Query(..., min_length=1),
    ):
        return query_repository.get_factory(publisher_id, factory_id)

    @app.get("/v1/factories/releases", tags=["releases"])
    async def list_factory_releases(
        publisher_id: str = Query(..., min_length=1),
        factory_id: str = Query(..., min_length=1),
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = Query(None),
    ):
        return query_repository.list_releases(publisher_id, factory_id, limit, cursor)

    def load_verified_release(publisher_id: str, factory_id: str, version: str):
        record = query_repository.get_release(publisher_id, factory_id, version)
        digest = DigestIdentity(
            record["digest"]["profile"],
            record["digest"]["algorithm"],
            record["digest"]["value"],
        )
        if record["provider"] != getattr(artifact_store, "provider", None):
            raise ArtifactLocationUnavailable("no configured storage adapter for this artifact provider")
        raw = artifact_store.read(digest)
        manifest = reconstruct_manifest(raw, digest)
        if len(raw) != record["byteLength"]:
            raise ArtifactIntegrityError("artifact byte length differs from registry metadata")
        return manifest, record

    @app.get("/v1/releases", tags=["releases"])
    async def get_exact_release(
        publisher_id: str = Query(..., min_length=1),
        factory_id: str = Query(..., min_length=1),
        version: str = Query(..., min_length=1),
    ):
        manifest, _record = load_verified_release(publisher_id, factory_id, version)
        return manifest

    @app.get("/v1/passports", tags=["passports"])
    async def get_factory_passport(
        publisher_id: str = Query(..., min_length=1),
        factory_id: str = Query(..., min_length=1),
        version: str = Query(..., min_length=1),
        format: str = Query("json", pattern="^(json|markdown)$"),
    ):
        manifest, record = load_verified_release(publisher_id, factory_id, version)
        passport = build_factory_passport(manifest, record)
        if format == "markdown":
            return Response(
                content=render_factory_passport_markdown(passport),
                media_type="text/markdown; charset=utf-8",
            )
        return Response(
            content=canonical_passport_json(passport),
            media_type="application/json",
        )

    return app
