"""Initial PostgreSQL schema and immutability triggers."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision="0001_initial_registry"
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    U=postgresql.UUID(as_uuid=True); T=lambda: sa.Text(collation="C")
    op.create_table("publishers",sa.Column("publisher_record_id",U,primary_key=True),sa.Column("publisher_uri",T(),nullable=False),sa.Column("lifecycle_state",sa.String(16),nullable=False,server_default="active"),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("retired_at",sa.DateTime(timezone=True)),sa.UniqueConstraint("publisher_uri",name="uq_publishers_publisher_uri"),sa.CheckConstraint("lifecycle_state IN ('active','retired')",name="ck_publishers_lifecycle"),sa.CheckConstraint("(lifecycle_state='active' AND retired_at IS NULL) OR (lifecycle_state='retired' AND retired_at IS NOT NULL)",name="ck_publishers_retired_at"))
    op.create_table("publisher_metadata",sa.Column("publisher_record_id",U,sa.ForeignKey("publishers.publisher_record_id",ondelete="RESTRICT"),primary_key=True),sa.Column("display_name",sa.Text()),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    op.create_table("factories",sa.Column("factory_record_id",U,primary_key=True),sa.Column("publisher_record_id",U,sa.ForeignKey("publishers.publisher_record_id",ondelete="RESTRICT"),nullable=False),sa.Column("factory_id",T(),nullable=False),sa.Column("lifecycle_state",sa.String(16),nullable=False,server_default="active"),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("retired_at",sa.DateTime(timezone=True)),sa.UniqueConstraint("publisher_record_id","factory_id",name="uq_factories_publisher_factory"),sa.CheckConstraint("lifecycle_state IN ('active','retired')",name="ck_factories_lifecycle"),sa.CheckConstraint("(lifecycle_state='active' AND retired_at IS NULL) OR (lifecycle_state='retired' AND retired_at IS NOT NULL)",name="ck_factories_retired_at"))
    op.create_table("artifact_blobs",sa.Column("artifact_blob_id",U,primary_key=True),sa.Column("digest_profile",T(),nullable=False),sa.Column("digest_algorithm",T(),nullable=False),sa.Column("digest_value",T(),nullable=False),sa.Column("byte_length",sa.BigInteger,nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.UniqueConstraint("digest_profile","digest_algorithm","digest_value",name="uq_artifact_digest"),sa.UniqueConstraint("artifact_blob_id","digest_profile","digest_algorithm","digest_value",name="uq_artifact_blob_digest_composite"),sa.CheckConstraint("byte_length >= 0",name="ck_artifact_byte_length"))
    op.create_table("artifact_locations",sa.Column("artifact_location_id",U,primary_key=True),sa.Column("artifact_blob_id",U,sa.ForeignKey("artifact_blobs.artifact_blob_id",ondelete="RESTRICT"),nullable=False),sa.Column("provider",T(),nullable=False),sa.Column("object_key",T(),nullable=False),sa.Column("location_state",sa.String(16),nullable=False,server_default="active"),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.UniqueConstraint("provider","object_key",name="uq_artifact_location_provider_key"))
    op.create_table("factory_releases",sa.Column("release_record_id",U,primary_key=True),sa.Column("factory_record_id",U,sa.ForeignKey("factories.factory_record_id",ondelete="RESTRICT"),nullable=False),sa.Column("version",T(),nullable=False),sa.Column("digest_profile",T(),nullable=False),sa.Column("digest_algorithm",T(),nullable=False),sa.Column("digest_value",T(),nullable=False),sa.Column("artifact_blob_id",U,nullable=False),sa.Column("published_at",sa.DateTime(timezone=True),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.UniqueConstraint("factory_record_id","version",name="uq_releases_factory_version"),sa.ForeignKeyConstraint(["artifact_blob_id","digest_profile","digest_algorithm","digest_value"],["artifact_blobs.artifact_blob_id","artifact_blobs.digest_profile","artifact_blobs.digest_algorithm","artifact_blobs.digest_value"],ondelete="RESTRICT",name="fk_release_matching_artifact_digest"))
    op.execute("""
    CREATE FUNCTION efs_guard_registry_rows() RETURNS trigger AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'registry identity and release rows are permanent'; END IF;
      IF TG_TABLE_NAME='publishers' AND NEW.publisher_uri IS DISTINCT FROM OLD.publisher_uri THEN RAISE EXCEPTION 'publisher URI is immutable'; END IF;
      IF TG_TABLE_NAME='factories' AND (NEW.publisher_record_id IS DISTINCT FROM OLD.publisher_record_id OR NEW.factory_id IS DISTINCT FROM OLD.factory_id) THEN RAISE EXCEPTION 'Factory identity is immutable'; END IF;
      IF TG_TABLE_NAME='artifact_blobs' AND (NEW.digest_profile IS DISTINCT FROM OLD.digest_profile OR NEW.digest_algorithm IS DISTINCT FROM OLD.digest_algorithm OR NEW.digest_value IS DISTINCT FROM OLD.digest_value OR NEW.byte_length IS DISTINCT FROM OLD.byte_length) THEN RAISE EXCEPTION 'artifact content identity is immutable'; END IF;
      IF TG_TABLE_NAME='factory_releases' THEN RAISE EXCEPTION 'published release is immutable'; END IF;
      IF TG_TABLE_NAME IN ('publishers','factories') AND OLD.lifecycle_state='retired' AND NEW.lifecycle_state<>'retired' THEN RAISE EXCEPTION 'retired identity cannot be reactivated'; END IF;
      IF TG_TABLE_NAME IN ('publishers','factories') AND (NEW.lifecycle_state IS DISTINCT FROM OLD.lifecycle_state OR NEW.retired_at IS DISTINCT FROM OLD.retired_at) AND NOT (OLD.lifecycle_state='active' AND NEW.lifecycle_state='retired' AND OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL) THEN RAISE EXCEPTION 'only one active-to-retired transition is permitted'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    """)
    op.execute("""
    CREATE FUNCTION efs_guard_parent_active() RETURNS trigger AS $$
    DECLARE state text;
    BEGIN
      IF TG_TABLE_NAME='factories' THEN SELECT lifecycle_state INTO state FROM publishers WHERE publisher_record_id=NEW.publisher_record_id FOR KEY SHARE;
      ELSE SELECT lifecycle_state INTO state FROM factories WHERE factory_record_id=NEW.factory_record_id FOR KEY SHARE; END IF;
      IF state IS DISTINCT FROM 'active' THEN RAISE EXCEPTION 'cannot register under missing or retired parent'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    """)
    for table,trigger in [("publishers","publishers_guard"),("factories","factories_guard"),("factory_releases","releases_guard")]:
        op.execute(f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION efs_guard_registry_rows()")
    op.execute("CREATE TRIGGER factories_parent_guard BEFORE INSERT ON factories FOR EACH ROW EXECUTE FUNCTION efs_guard_parent_active()")
    op.execute("CREATE TRIGGER releases_parent_guard BEFORE INSERT ON factory_releases FOR EACH ROW EXECUTE FUNCTION efs_guard_parent_active()")

def downgrade():
    raise RuntimeError("Destructive downgrade prohibited for permanent registry identity/release history; restore backup or apply a forward fix.")
