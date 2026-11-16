"""PostgreSQL-only behavior tests; migrations are applied by the CI job."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from registry.repositories import (
    FactoryRepository,
    PublisherRepository,
    RegistryConflict,
    ReleaseRepository,
)

URL = os.getenv("EFS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="EFS_TEST_DATABASE_URL not configured")


@pytest.fixture
def session():
    engine = create_engine(URL)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_publisher_scoped_factory_identity(session):
    publishers = PublisherRepository(session)
    publishers.create("urn:example:publisher:a")
    publishers.create("urn:example:publisher:b")
    factories = FactoryRepository(session)
    first = factories.create("urn:example:publisher:a", "same")
    second = factories.create("urn:example:publisher:b", "same")
    assert first.factory_record_id != second.factory_record_id


def test_duplicate_identity_conflicts(session):
    publishers = PublisherRepository(session)
    publishers.create("urn:example:publisher:dup")
    with pytest.raises(RegistryConflict):
        publishers.create("urn:example:publisher:dup")
    factories = FactoryRepository(session)
    factories.create("urn:example:publisher:dup", "f")
    with pytest.raises(RegistryConflict):
        factories.create("urn:example:publisher:dup", "f")


def test_release_is_immutable_and_digest_bound(session):
    PublisherRepository(session).create("urn:example:publisher:r")
    FactoryRepository(session).create("urn:example:publisher:r", "f")
    row = ReleaseRepository(session).publish(
        "urn:example:publisher:r", "f", "1.0", "efs-jcs-sha256-v1",
        "SHA-256", "abc", 12, "test", "abc", datetime.now(UTC),
    )
    with pytest.raises(DBAPIError):
        session.execute(
            text("UPDATE factory_releases SET digest_value='changed' WHERE release_record_id=:id"),
            {"id": str(row.release_record_id)},
        )
        session.flush()


def test_publisher_identity_is_immutable(session):
    publisher = PublisherRepository(session).create("urn:example:publisher:immutable")
    with pytest.raises(DBAPIError):
        session.execute(
            text("UPDATE publishers SET publisher_uri='urn:example:publisher:changed' WHERE publisher_record_id=:id"),
            {"id": str(publisher.publisher_record_id)},
        )
        session.flush()


def test_retired_factory_cannot_publish(session):
    PublisherRepository(session).create("urn:example:publisher:t")
    factories = FactoryRepository(session)
    factories.create("urn:example:publisher:t", "f")
    factories.retire("urn:example:publisher:t", "f")
    with pytest.raises(RegistryConflict):
        ReleaseRepository(session).publish(
            "urn:example:publisher:t", "f", "1.0", "p", "SHA-256",
            "d", 1, "test", "d", datetime.now(UTC),
        )


def test_migration_revision_is_installed(session):
    revision = session.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == "0001_initial_registry"


def test_concurrent_factory_registration_has_one_winner():
    engine = create_engine(URL)
    with Session(engine) as seed:
        PublisherRepository(seed).create("urn:example:publisher:concurrent")
        seed.commit()

    def register():
        with Session(engine) as worker:
            try:
                FactoryRepository(worker).create("urn:example:publisher:concurrent", "race")
                worker.commit()
                return "created"
            except RegistryConflict:
                worker.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: register(), range(2)))
    assert sorted(outcomes) == ["conflict", "created"]
    engine.dispose()
