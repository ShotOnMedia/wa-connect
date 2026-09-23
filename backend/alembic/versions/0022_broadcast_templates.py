"""Reusable broadcast templates.

Revision ID: 0022_broadcast_templates
Revises: 0021_broadcast_segment_ref
"""
from alembic import op
import sqlalchemy as sa
revision="0022_broadcast_templates";down_revision="0021_broadcast_segment_ref";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("broadcast_templates",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),
        sa.Column("workspace_id",sa.BigInteger(),sa.ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False),
        sa.Column("name",sa.String(150),nullable=False),
        sa.Column("channel",sa.String(30),nullable=False,server_default="telegram"),
        sa.Column("message_text",sa.Text(),nullable=False),
        sa.Column("parse_mode",sa.String(20),nullable=False,server_default="HTML"),
        sa.Column("media_url",sa.Text(),nullable=True),
        sa.Column("media_type",sa.String(20),nullable=True),
        sa.Column("stagger_seconds",sa.Float(),nullable=False,server_default="0.05"),
        sa.Column("created_by_user_id",sa.BigInteger(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("created_at",sa.DateTime(),nullable=False),
        sa.Column("updated_at",sa.DateTime(),nullable=False),
        sa.UniqueConstraint("workspace_id","channel","name",name="uq_broadcast_template_name"),
    )
    op.create_index("ix_broadcast_templates_workspace_channel","broadcast_templates",["workspace_id","channel"])
def downgrade():op.drop_table("broadcast_templates")
