"""Messaging campaign recipient runtime.

Revision ID: 0025_campaign_runtime
Revises: 0023_msg_campaigns
"""
from alembic import op
import sqlalchemy as sa
revision="0025_campaign_runtime";down_revision="0023_msg_campaigns";branch_labels=None;depends_on=None

def upgrade():
    op.create_table("messaging_campaign_recipients",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),
        sa.Column("campaign_id",sa.BigInteger(),sa.ForeignKey("messaging_campaigns.id",ondelete="CASCADE"),nullable=False),
        sa.Column("channel_contact_id",sa.BigInteger(),nullable=False),sa.Column("conversation_id",sa.BigInteger(),nullable=False),
        sa.Column("destination",sa.String(100),nullable=False),sa.Column("display_name",sa.String(200),nullable=True),
        sa.Column("field_values_json",sa.Text(),nullable=True),sa.Column("status",sa.String(20),nullable=False,server_default="pending"),
        sa.Column("current_step_position",sa.Integer(),nullable=False,server_default="1"),
        sa.Column("started_at",sa.DateTime(),nullable=True),sa.Column("completed_at",sa.DateTime(),nullable=True),
        sa.Column("failed_at",sa.DateTime(),nullable=True),sa.Column("last_error",sa.Text(),nullable=True),
        sa.Column("created_at",sa.DateTime(),nullable=False),sa.Column("updated_at",sa.DateTime(),nullable=False),
        sa.UniqueConstraint("campaign_id","channel_contact_id",name="uq_msg_campaign_recipient"))
    op.create_index("ix_msg_campaign_recipient_status","messaging_campaign_recipients",["campaign_id","status"])
    op.create_index("ix_messaging_campaign_recipients_contact","messaging_campaign_recipients",["channel_contact_id"])
    op.create_index("ix_messaging_campaign_recipients_conversation","messaging_campaign_recipients",["conversation_id"])
    op.create_table("messaging_campaign_deliveries",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),
        sa.Column("campaign_id",sa.BigInteger(),sa.ForeignKey("messaging_campaigns.id",ondelete="CASCADE"),nullable=False),
        sa.Column("recipient_id",sa.BigInteger(),sa.ForeignKey("messaging_campaign_recipients.id",ondelete="CASCADE"),nullable=False),
        sa.Column("step_id",sa.BigInteger(),sa.ForeignKey("messaging_campaign_steps.id",ondelete="CASCADE"),nullable=False),
        sa.Column("step_position",sa.Integer(),nullable=False),sa.Column("rendered_text",sa.Text(),nullable=False),
        sa.Column("media_url",sa.Text(),nullable=True),sa.Column("media_type",sa.String(20),nullable=True),
        sa.Column("parse_mode",sa.String(20),nullable=False,server_default="HTML"),sa.Column("status",sa.String(20),nullable=False,server_default="pending"),
        sa.Column("due_at",sa.DateTime(),nullable=False),sa.Column("attempts",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("provider_message_id",sa.String(255),nullable=True),sa.Column("sent_at",sa.DateTime(),nullable=True),
        sa.Column("last_error",sa.Text(),nullable=True),sa.Column("created_at",sa.DateTime(),nullable=False),sa.Column("updated_at",sa.DateTime(),nullable=False),
        sa.UniqueConstraint("recipient_id","step_id",name="uq_msg_campaign_recipient_step"))
    op.create_index("ix_msg_campaign_delivery_due","messaging_campaign_deliveries",["status","due_at"])
    op.create_index("ix_messaging_campaign_deliveries_campaign","messaging_campaign_deliveries",["campaign_id"])
    op.create_index("ix_messaging_campaign_deliveries_recipient","messaging_campaign_deliveries",["recipient_id"])
    op.create_index("ix_messaging_campaign_deliveries_step","messaging_campaign_deliveries",["step_id"])

def downgrade():
    op.drop_table("messaging_campaign_deliveries");op.drop_table("messaging_campaign_recipients")
