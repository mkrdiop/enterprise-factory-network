"""PostgreSQL persistence mappings; UUIDs are local keys, never EFS identities."""
import uuid
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class Publisher(Base):
    __tablename__="publishers"
    __table_args__=(UniqueConstraint("publisher_uri",name="uq_publishers_publisher_uri"),CheckConstraint("lifecycle_state IN ('active','retired')",name="ck_publishers_lifecycle"),CheckConstraint("(lifecycle_state='active' AND retired_at IS NULL) OR (lifecycle_state='retired' AND retired_at IS NOT NULL)",name="ck_publishers_retired_at"))
    publisher_record_id: Mapped[uuid.UUID]=mapped_column(Uuid,primary_key=True,default=uuid.uuid4)
    publisher_uri: Mapped[str]=mapped_column(Text(collation="C"),nullable=False)
    lifecycle_state: Mapped[str]=mapped_column(String(16),nullable=False,default="active")
    created_at: Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)
    retired_at: Mapped[object|None]=mapped_column(DateTime(timezone=True))

class PublisherMetadata(Base):
    __tablename__="publisher_metadata"
    publisher_record_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("publishers.publisher_record_id",ondelete="RESTRICT"),primary_key=True)
    display_name: Mapped[str|None]=mapped_column(Text)
    updated_at: Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)

class Factory(Base):
    __tablename__="factories"
    __table_args__=(UniqueConstraint("publisher_record_id","factory_id",name="uq_factories_publisher_factory"),CheckConstraint("lifecycle_state IN ('active','retired')",name="ck_factories_lifecycle"),CheckConstraint("(lifecycle_state='active' AND retired_at IS NULL) OR (lifecycle_state='retired' AND retired_at IS NOT NULL)",name="ck_factories_retired_at"))
    factory_record_id: Mapped[uuid.UUID]=mapped_column(Uuid,primary_key=True,default=uuid.uuid4)
    publisher_record_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("publishers.publisher_record_id",ondelete="RESTRICT"),nullable=False)
    factory_id: Mapped[str]=mapped_column(Text(collation="C"),nullable=False)
    lifecycle_state: Mapped[str]=mapped_column(String(16),nullable=False,default="active")
    created_at: Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)
    retired_at: Mapped[object|None]=mapped_column(DateTime(timezone=True))

class ArtifactBlob(Base):
    __tablename__="artifact_blobs"
    __table_args__=(UniqueConstraint("digest_profile","digest_algorithm","digest_value",name="uq_artifact_digest"),UniqueConstraint("artifact_blob_id","digest_profile","digest_algorithm","digest_value",name="uq_artifact_blob_digest_composite"),CheckConstraint("byte_length >= 0",name="ck_artifact_byte_length"))
    artifact_blob_id: Mapped[uuid.UUID]=mapped_column(Uuid,primary_key=True,default=uuid.uuid4)
    digest_profile: Mapped[str]=mapped_column(Text(collation="C"),nullable=False)
    digest_algorithm: Mapped[str]=mapped_column(Text(collation="C"),nullable=False)
    digest_value: Mapped[str]=mapped_column(Text(collation="C"),nullable=False)
    byte_length: Mapped[int]=mapped_column(BigInteger,nullable=False)
    created_at: Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)

class ArtifactLocation(Base):
    __tablename__="artifact_locations"
    __table_args__=(UniqueConstraint("provider","object_key",name="uq_artifact_location_provider_key"),)
    artifact_location_id: Mapped[uuid.UUID]=mapped_column(Uuid,primary_key=True,default=uuid.uuid4)
    artifact_blob_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("artifact_blobs.artifact_blob_id",ondelete="RESTRICT"),nullable=False)
    provider: Mapped[str]=mapped_column(Text(collation="C"),nullable=False)
    object_key: Mapped[str]=mapped_column(Text(collation="C"),nullable=False)
    location_state: Mapped[str]=mapped_column(String(16),nullable=False,default="active")
    created_at: Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)

class FactoryRelease(Base):
    __tablename__="factory_releases"
    __table_args__=(UniqueConstraint("factory_record_id","version",name="uq_releases_factory_version"),ForeignKeyConstraint(["artifact_blob_id","digest_profile","digest_algorithm","digest_value"],["artifact_blobs.artifact_blob_id","artifact_blobs.digest_profile","artifact_blobs.digest_algorithm","artifact_blobs.digest_value"],ondelete="RESTRICT",name="fk_release_matching_artifact_digest"))
    release_record_id: Mapped[uuid.UUID]=mapped_column(Uuid,primary_key=True,default=uuid.uuid4)
    factory_record_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("factories.factory_record_id",ondelete="RESTRICT"),nullable=False)
    version: Mapped[str]=mapped_column(Text(collation="C"),nullable=False)
    digest_profile: Mapped[str]=mapped_column(Text(collation="C"),nullable=False)
    digest_algorithm: Mapped[str]=mapped_column(Text(collation="C"),nullable=False)
    digest_value: Mapped[str]=mapped_column(Text(collation="C"),nullable=False)
    artifact_blob_id: Mapped[uuid.UUID]=mapped_column(Uuid,nullable=False)
    published_at: Mapped[object]=mapped_column(DateTime(timezone=True),nullable=False)
    created_at: Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)
