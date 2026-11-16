from registry.models import ArtifactBlob, Factory, FactoryRelease, Publisher


def test_required_unique_constraints_exist():
    for model,name in [(Publisher,"uq_publishers_publisher_uri"),(Factory,"uq_factories_publisher_factory"),(ArtifactBlob,"uq_artifact_digest"),(FactoryRelease,"uq_releases_factory_version")]:
        assert name in {c.name for c in model.__table__.constraints}

def test_identity_columns_are_bytewise_text():
    assert Publisher.__table__.c.publisher_uri.type.collation=="C"
    assert Factory.__table__.c.factory_id.type.collation=="C"

def test_release_has_composite_digest_foreign_key():
    fk=next(c for c in FactoryRelease.__table__.constraints if c.name=="fk_release_matching_artifact_digest")
    assert [c.name for c in fk.columns]==["artifact_blob_id","digest_profile","digest_algorithm","digest_value"]
