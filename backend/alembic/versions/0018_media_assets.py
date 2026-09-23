"""Workspace media asset library for broadcasts.

Revision ID: 0018_media_assets
Revises: 0017_broadcast_rich_delivery
"""
from alembic import op
import sqlalchemy as sa
revision="0018_media_assets";down_revision="0017_broadcast_rich_delivery";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("media_assets",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),
        sa.Column("workspace_id",sa.BigInteger(),sa.ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False),
        sa.Column("name",sa.String(255),nullable=False),
        sa.Column("content_type",sa.String(150),nullable=False),
        sa.Column("media_type",sa.String(20),nullable=False),
        sa.Column("size_bytes",sa.BigInteger(),nullable=False),
        sa.Column("provider",sa.String(20),nullable=False),
        sa.Column("storage_key",sa.Text(),nullable=False),
        sa.Column("url",sa.Text(),nullable=False),
        sa.Column("created_by_user_id",sa.BigInteger(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("created_at",sa.DateTime(),nullable=False),
    )
    op.create_index("ix_media_assets_workspace_created","media_assets",["workspace_id","created_at"])
def downgrade():op.drop_table("media_assets")
