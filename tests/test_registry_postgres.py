"""PostgreSQL-only behavior tests; migrations are applied by the CI job."""
import os
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from registry.repositories import FactoryRepository, PublisherRepository, ReleaseRepository, RegistryConflict

URL=os.getenv("EFS_TEST_DATABASE_URL")
pytestmark=pytest.mark.skipif(not URL,reason="EFS_TEST_DATABASE_URL not configured")

@pytest.fixture
def session():
    engine=create_engine(URL)
    with Session(engine) as s:
        yield s
    engine.dispose()

def test_publisher_scoped_factory_identity(session):
    p=PublisherRepository(session); p.create("urn:example:publisher:a"); p.create("urn:example:publisher:b")
    a=FactoryRepository(session).create("urn:example:publisher:a","same")
    b=FactoryRepository(session).create("urn:example:publisher:b","same")
    assert a.factory_record_id!=b.factory_record_id

def test_duplicate_identity_conflicts(session):
    p=PublisherRepository(session); p.create("urn:example:publisher:dup")
    with pytest.raises(RegistryConflict): p.create("urn:example:publisher:dup")
    f=FactoryRepository(session); f.create("urn:example:publisher:dup","f")
    with pytest.raises(RegistryConflict): f.create("urn:example:publisher:dup","f")

def test_release_is_immutable_and_digest_bound(session):
    PublisherRepository(session).create("urn:example:publisher:r")
    FactoryRepository(session).create("urn:example:publisher:r","f")
    row=ReleaseRepository(session).publish("urn:example:publisher:r","f","1.0","efs-jcs-sha256-v1","SHA-256","abc",12,"test","abc",datetime.now(timezone.utc))
    with pytest.raises(DBAPIError):
        session.execute(text("UPDATE factory_releases SET digest_value='changed' WHERE release_record_id=:id"),{"id":str(row.release_record_id)})
        session.flush()

def test_publisher_identity_is_immutable(session):
    pub=PublisherRepository(session).create("urn:example:publisher:immutable")
    with pytest.raises(DBAPIError):
        session.execute(text("UPDATE publishers SET publisher_uri='urn:example:publisher:changed' WHERE publisher_record_id=:id"),{"id":str(pub.publisher_record_id)})
        session.flush()

def test_retired_factory_cannot_publish(session):
    PublisherRepository(session).create("urn:example:publisher:t")
    f=FactoryRepository(session); f.create("urn:example:publisher:t","f"); f.retire("urn:example:publisher:t","f")
    with pytest.raises(RegistryConflict):
        ReleaseRepository(session).publish("urn:example:publisher:t","f","1.0","p","SHA-256","d",1,"test","d",datetime.now(timezone.utc))
