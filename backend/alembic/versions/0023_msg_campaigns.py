"""Shared multi-message campaign foundation.

Revision ID: 0023_msg_campaigns
Revises: 0022_broadcast_templates
"""
from alembic import op
import sqlalchemy as sa
revision="0023_msg_campaigns";down_revision="0022_broadcast_templates";branch_labels=None;depends_on=None

def upgrade():
    op.create_table("messaging_campaigns",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),
        sa.Column("workspace_id",sa.BigInteger(),sa.ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False),
        sa.Column("channel",sa.String(20),nullable=False),
        sa.Column("channel_account_id",sa.BigInteger(),nullable=False),
        sa.Column("name",sa.String(150),nullable=False),
        sa.Column("description",sa.Text(),nullable=True),
        sa.Column("status",sa.String(20),nullable=False,server_default="draft"),
        sa.Column("audience_type",sa.String(30),nullable=False,server_default="all"),
        sa.Column("audience_filter_json",sa.Text(),nullable=True),
        sa.Column("audience_segment_id",sa.BigInteger(),sa.ForeignKey("audience_segments.id",ondelete="SET NULL"),nullable=True),
        sa.Column("scheduled_at",sa.DateTime(),nullable=True),sa.Column("started_at",sa.DateTime(),nullable=True),sa.Column("completed_at",sa.DateTime(),nullable=True),
        sa.Column("created_by_user_id",sa.BigInteger(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("created_at",sa.DateTime(),nullable=False),sa.Column("updated_at",sa.DateTime(),nullable=False))
    op.create_index("ix_msg_campaign_workspace_channel","messaging_campaigns",["workspace_id","channel"])
    op.create_index("ix_msg_campaign_status","messaging_campaigns",["status"])
    op.create_index("ix_messaging_campaigns_account","messaging_campaigns",["channel_account_id"])
    op.create_index("ix_messaging_campaigns_segment","messaging_campaigns",["audience_segment_id"])
    op.create_table("messaging_campaign_steps",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),
        sa.Column("campaign_id",sa.BigInteger(),sa.ForeignKey("messaging_campaigns.id",ondelete="CASCADE"),nullable=False),
        sa.Column("position",sa.Integer(),nullable=False),sa.Column("name",sa.String(150),nullable=False),
        sa.Column("delay_seconds",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("message_mode",sa.String(20),nullable=False,server_default="freeform"),
        sa.Column("message_text",sa.Text(),nullable=False),sa.Column("provider_template_json",sa.Text(),nullable=True),
        sa.Column("parse_mode",sa.String(20),nullable=False,server_default="HTML"),
        sa.Column("media_url",sa.Text(),nullable=True),sa.Column("media_type",sa.String(20),nullable=True),
        sa.Column("created_at",sa.DateTime(),nullable=False),sa.Column("updated_at",sa.DateTime(),nullable=False),
        sa.UniqueConstraint("campaign_id","position",name="uq_msg_campaign_step_position"))
    op.create_index("ix_messaging_campaign_steps_campaign","messaging_campaign_steps",["campaign_id"])

def downgrade():
    op.drop_table("messaging_campaign_steps");op.drop_table("messaging_campaigns")
