"""Add broadcast messaging tables.

Revision ID: 0016_broadcasts
Revises: 0015_flow_interrupt_flag
"""
from alembic import op
import sqlalchemy as sa
revision="0016_broadcasts";down_revision="0015_flow_interrupt_flag";branch_labels=None;depends_on=None

def upgrade():
    op.create_table("broadcasts",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),
        sa.Column("workspace_id",sa.BigInteger(),sa.ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False),
        sa.Column("channel",sa.String(20),nullable=False),sa.Column("channel_account_id",sa.BigInteger(),nullable=False),
        sa.Column("name",sa.String(150),nullable=False),sa.Column("message_text",sa.Text(),nullable=False),
        sa.Column("audience_type",sa.String(30),nullable=False,server_default="all"),sa.Column("status",sa.String(20),nullable=False,server_default="draft"),
        sa.Column("scheduled_at",sa.DateTime()),sa.Column("started_at",sa.DateTime()),sa.Column("completed_at",sa.DateTime()),
        sa.Column("created_by_user_id",sa.BigInteger(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("total_recipients",sa.Integer(),nullable=False,server_default="0"),sa.Column("sent_count",sa.Integer(),nullable=False,server_default="0"),sa.Column("failed_count",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("created_at",sa.DateTime(),nullable=False),sa.Column("updated_at",sa.DateTime(),nullable=False))
    op.create_index("ix_broadcasts_workspace_created","broadcasts",["workspace_id","created_at"]);op.create_index("ix_broadcasts_status_scheduled","broadcasts",["status","scheduled_at"]);op.create_index("ix_broadcasts_channel","broadcasts",["channel"]);op.create_index("ix_broadcasts_channel_account_id","broadcasts",["channel_account_id"])
    op.create_table("broadcast_recipients",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),sa.Column("broadcast_id",sa.BigInteger(),sa.ForeignKey("broadcasts.id",ondelete="CASCADE"),nullable=False),
        sa.Column("channel_contact_id",sa.BigInteger(),nullable=False),sa.Column("conversation_id",sa.BigInteger(),nullable=False),sa.Column("destination",sa.String(100),nullable=False),sa.Column("display_name",sa.String(200)),
        sa.Column("rendered_text",sa.Text(),nullable=False),sa.Column("status",sa.String(20),nullable=False,server_default="pending"),sa.Column("provider_message_id",sa.String(100)),sa.Column("attempts",sa.Integer(),nullable=False,server_default="0"),sa.Column("last_error",sa.Text()),sa.Column("sent_at",sa.DateTime()),sa.Column("created_at",sa.DateTime(),nullable=False),sa.Column("updated_at",sa.DateTime(),nullable=False),
        sa.UniqueConstraint("broadcast_id","channel_contact_id",name="uq_broadcast_channel_contact"))
    op.create_index("ix_broadcast_recipients_work","broadcast_recipients",["status","broadcast_id","id"]);op.create_index("ix_broadcast_recipients_broadcast_id","broadcast_recipients",["broadcast_id"]);op.create_index("ix_broadcast_recipients_channel_contact_id","broadcast_recipients",["channel_contact_id"]);op.create_index("ix_broadcast_recipients_conversation_id","broadcast_recipients",["conversation_id"]);op.create_index("ix_broadcast_recipients_status","broadcast_recipients",["status"])

def downgrade():
    op.drop_table("broadcast_recipients");op.drop_table("broadcasts")
