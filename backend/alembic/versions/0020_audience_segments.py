"""Reusable audience segments.

Revision ID: 0020_audience_segments
Revises: 0019_broadcast_audience_filters
"""
from alembic import op
import sqlalchemy as sa
revision="0020_audience_segments";down_revision="0019_broadcast_audience_filters";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("audience_segments",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),
        sa.Column("workspace_id",sa.BigInteger(),sa.ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False),
        sa.Column("name",sa.String(150),nullable=False),
        sa.Column("channel",sa.String(30),nullable=False,server_default="telegram"),
        sa.Column("filter_json",sa.Text(),nullable=False),
        sa.Column("created_by_user_id",sa.BigInteger(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("created_at",sa.DateTime(),nullable=False),
        sa.Column("updated_at",sa.DateTime(),nullable=False),
        sa.UniqueConstraint("workspace_id","channel","name",name="uq_audience_segment_workspace_channel_name"),
    )
    op.create_index("ix_audience_segments_workspace_channel","audience_segments",["workspace_id","channel"])
def downgrade():op.drop_table("audience_segments")
