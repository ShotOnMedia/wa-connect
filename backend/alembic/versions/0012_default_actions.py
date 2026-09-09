"""Add channel-specific Default Actions.

Revision ID: 0012_default_actions
Revises: 0011_campaign_submissions
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_default_actions"
down_revision = "0011_campaign_submissions"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "default_actions" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "default_actions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("action_type", sa.String(40), nullable=False),
        sa.Column("flow_id", sa.BigInteger(), sa.ForeignKey("flows.id", ondelete="SET NULL"), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "channel", "action_type", name="uq_default_action_workspace_channel_type"),
    )
    op.create_index("ix_default_actions_workspace_id", "default_actions", ["workspace_id"])
    op.create_index("ix_default_actions_flow_id", "default_actions", ["flow_id"])
    op.create_index("ix_default_actions_workspace_channel", "default_actions", ["workspace_id", "channel"])


def downgrade():
    if "default_actions" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("default_actions")
