"""Run bounded recovery for durable pending EFS release publications."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import sessionmaker

from registry.artifact_store import LocalFilesystemArtifactStore
from registry.db import make_engine
from registry.digests import EFSReleaseDigestService
from registry.publication_repository import SQLPublicationOperationRepository
from registry.publication_service import RegistryPublicationService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="maximum pending operations to inspect (1..500)")
    args = parser.parse_args()
    if not 1 <= args.limit <= 500:
        parser.error("--limit must be between 1 and 500")

    artifact_root = os.getenv("EFS_ARTIFACT_ROOT")
    if not artifact_root:
        parser.error("EFS_ARTIFACT_ROOT must be configured")

    engine = make_engine()
    try:
        sessions = sessionmaker(engine, expire_on_commit=False)
        repository = SQLPublicationOperationRepository(sessions)
        store = LocalFilesystemArtifactStore(artifact_root)
        service = RegistryPublicationService(
            repository,
            EFSReleaseDigestService(),
            store,
            ROOT / "schemas/efs/v1/factory-manifest.schema.json",
        )
        result = service.recover_pending(limit=args.limit)
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
