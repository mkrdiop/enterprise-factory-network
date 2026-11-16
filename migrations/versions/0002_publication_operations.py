"""Durable publication operation/idempotency records.

Revision ID: 0002_publication_operations
Revises: 0001_initial_registry
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_publication_operations"
down_revision = "0001_initial_registry"
branch_labels = None
depends_on = None


def upgrade():
    uuid_type = postgresql.UUID(as_uuid=True)
    exact_text = lambda: sa.Text(collation="C")
    op.add_column("artifact_locations", sa.Column("generation", exact_text(), nullable=True))
    op.create_table(
        "publication_operations",
        sa.Column("publication_operation_id", uuid_type, primary_key=True),
        sa.Column("idempotency_key", exact_text(), nullable=False),
        sa.Column("request_fingerprint", exact_text(), nullable=False),
        sa.Column(
            "factory_record_id",
            uuid_type,
            sa.ForeignKey("factories.factory_record_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", exact_text(), nullable=False),
        sa.Column("digest_profile", exact_text(), nullable=False),
        sa.Column("digest_algorithm", exact_text(), nullable=False),
        sa.Column("digest_value", exact_text(), nullable=False),
        sa.Column("payload_length", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "release_record_id",
            uuid_type,
            sa.ForeignKey("factory_releases.release_record_id", ondelete="RESTRICT"),
        ),
        sa.Column("failure_code", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_publication_operations_idempotency_key"),
        sa.CheckConstraint(
            "state IN ('pending','committed','conflict','failed')",
            name="ck_publication_operations_state",
        ),
        sa.CheckConstraint("payload_length >= 0", name="ck_publication_payload_length"),
        sa.CheckConstraint(
            "(state = 'committed' AND release_record_id IS NOT NULL) OR "
            "(state <> 'committed' AND release_record_id IS NULL)",
            name="ck_publication_release_state",
        ),
    )
    op.create_index(
        "ix_publication_operations_digest_state",
        "publication_operations",
        ["digest_profile", "digest_algorithm", "digest_value", "state"],
    )
    op.create_index(
        "ix_publication_operations_state_created",
        "publication_operations",
        ["state", "created_at"],
    )


def downgrade():
    op.drop_index("ix_publication_operations_state_created", table_name="publication_operations")
    op.drop_index("ix_publication_operations_digest_state", table_name="publication_operations")
    op.drop_table("publication_operations")
    op.drop_column("artifact_locations", "generation")
