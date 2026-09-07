"""media storage settings

Revision ID: 0009_media_storage_settings
Revises: 0008_image_contact_field_type
"""
from alembic import op
import sqlalchemy as sa
revision="0009_media_storage_settings";down_revision="0008_image_contact_field_type";branch_labels=None;depends_on=None

def upgrade():
    op.create_table("media_storage_settings",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),
        sa.Column("provider",sa.String(20),nullable=False,server_default="local"),
        sa.Column("local_path",sa.String(500),nullable=False,server_default="/app/storage/inbound-media"),
        sa.Column("public_base_url",sa.String(1000),nullable=True),
        sa.Column("max_upload_mb",sa.Integer(),nullable=False,server_default="25"),
        sa.Column("s3_endpoint_url",sa.String(1000),nullable=True),sa.Column("s3_region",sa.String(100),nullable=True),sa.Column("s3_bucket",sa.String(255),nullable=True),
        sa.Column("s3_access_key_enc",sa.Text(),nullable=True),sa.Column("s3_secret_key_enc",sa.Text(),nullable=True),sa.Column("s3_prefix",sa.String(500),nullable=True),
        sa.Column("s3_use_ssl",sa.Boolean(),nullable=False,server_default=sa.true()),sa.Column("s3_path_style",sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column("created_at",sa.DateTime(),nullable=False),sa.Column("updated_at",sa.DateTime(),nullable=False))

def downgrade():op.drop_table("media_storage_settings")
